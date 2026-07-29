import base64
import binascii
from dataclasses import dataclass
from typing import Any

import httpx

from core.exceptions import OpenRouterError


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    content: bytes
    content_type: str


class OpenRouterClient:
    """One shared OpenRouter HTTP client for the app lifetime. Reuse; do not create per task.

    Model IDs are always chosen by the caller (pipeline), never hardcoded here.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter api_key is required")
        if not base_url:
            raise ValueError("OpenRouter base_url is required")

        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def chat_completions(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /chat/completions. Returns the raw JSON body."""
        return self._post_json("/chat/completions", body)

    def create_image(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /images. Returns the raw JSON body."""
        return self._post_json("/images", body, timeout=120.0)

    def generate_text(self, prompt: str, *, model: str) -> str:
        """Generate text from a prompt. Caller picks the model."""
        if not model:
            raise ValueError("model is required")

        data = self.chat_completions(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        return self._message_text(data)

    def generate_image(self, prompt: str, *, model: str) -> GeneratedImage:
        """Generate an image via chat + modalities. Caller picks the model."""
        if not model:
            raise ValueError("model is required")

        data = self._post_json(
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "modalities": ["image", "text"],
            },
            timeout=120.0,
        )
        return self._image_from_chat(data)

    def close(self) -> None:
        self._http.close()

    def _post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._http.post(path, json=body, timeout=timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _message_text(data: dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter response missing message content") from exc

        if not isinstance(content, str) or not content.strip():
            raise OpenRouterError("OpenRouter returned empty text")

        return content.strip()

    @staticmethod
    def _image_from_chat(data: dict[str, Any]) -> GeneratedImage:
        try:
            url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter response missing image") from exc

        if not isinstance(url, str) or not url.startswith("data:"):
            raise OpenRouterError("OpenRouter image is not a data URL")

        try:
            header, b64_data = url.split(",", 1)
        except ValueError as exc:
            raise OpenRouterError("OpenRouter image data URL is malformed") from exc

        content_type = header.removeprefix("data:").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise OpenRouterError(f"Unexpected image content type: {content_type}")

        try:
            content = base64.b64decode(b64_data, validate=True)
        except binascii.Error as exc:
            raise OpenRouterError("OpenRouter returned invalid image base64") from exc

        if not content:
            raise OpenRouterError("OpenRouter returned empty image data")

        return GeneratedImage(content=content, content_type=content_type)
