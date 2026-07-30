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
        return self._post_json("/images", body, timeout=360.0)

    def generate_text(
        self,
        prompt: str,
        *,
        model: str,
        reference_image_urls: list[str] | None = None,
        json_object: bool = False,
    ) -> str:
        """Generate text from a prompt. Optional image URLs for vision briefing."""
        if not model:
            raise ValueError("model is required")

        content: str | list[dict[str, Any]]
        refs = [url for url in (reference_image_urls or []) if isinstance(url, str) and url.strip()]
        if refs:
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for url in refs:
                parts.append({"type": "image_url", "image_url": {"url": url.strip()}})
            content = parts
        else:
            content = prompt

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        data = self.chat_completions(body)
        return self._message_text(data)

    @staticmethod
    def _uses_images_api(model: str) -> bool:
        """OpenAI GPT image models return bytes via POST /images, not chat modalities."""
        lowered = model.lower()
        return "gpt" in lowered and "image" in lowered

    def generate_image(
        self,
        prompt: str,
        *,
        model: str,
        reference_image_urls: list[str] | None = None,
    ) -> GeneratedImage:
        """Generate an image. Caller picks the model.

        GPT image models use POST /images with optional input_references (raw product photo).
        Other models use chat completions + modalities.
        """
        if not model:
            raise ValueError("model is required")

        refs = [url for url in (reference_image_urls or []) if isinstance(url, str) and url.strip()]

        if self._uses_images_api(model):
            body: dict[str, Any] = {"model": model, "prompt": prompt}
            if refs:
                body["input_references"] = [
                    {"type": "image_url", "image_url": {"url": url}} for url in refs
                ]
            data = self.create_image(body)
            return self._image_from_images_api(data)

        content: str | list[dict[str, Any]]
        if refs:
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for url in refs:
                parts.append({"type": "image_url", "image_url": {"url": url}})
            content = parts
        else:
            content = prompt

        data = self._post_json(
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "modalities": ["image", "text"],
            },
            timeout=180.0,
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
        try:
            response = self._http.post(path, json=body, timeout=timeout)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OpenRouterError(f"OpenRouter timeout on {path}") from exc
        except httpx.HTTPStatusError as exc:
            detail = (exc.response.text or "")[:500]
            raise OpenRouterError(
                f"OpenRouter HTTP {exc.response.status_code} on {path}: {detail}"
            ) from exc
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
    def _image_from_images_api(data: dict[str, Any]) -> GeneratedImage:
        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter /images response missing data") from exc

        b64_data = item.get("b64_json") if isinstance(item, dict) else None
        if isinstance(b64_data, str) and b64_data.strip():
            try:
                content = base64.b64decode(b64_data, validate=True)
            except binascii.Error as exc:
                raise OpenRouterError("OpenRouter returned invalid image base64") from exc
            if not content:
                raise OpenRouterError("OpenRouter returned empty image data")
            return GeneratedImage(content=content, content_type="image/png")

        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith("data:"):
            try:
                header, encoded = url.split(",", 1)
            except ValueError as exc:
                raise OpenRouterError("OpenRouter image data URL is malformed") from exc
            content_type = header.removeprefix("data:").split(";", 1)[0]
            try:
                content = base64.b64decode(encoded, validate=True)
            except binascii.Error as exc:
                raise OpenRouterError("OpenRouter returned invalid image base64") from exc
            if not content:
                raise OpenRouterError("OpenRouter returned empty image data")
            return GeneratedImage(content=content, content_type=content_type or "image/png")

        raise OpenRouterError("OpenRouter /images response missing b64_json/url")

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
