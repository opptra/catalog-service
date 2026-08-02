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


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    """An input image (remote or ``data:`` URL) with an optional label describing its role."""

    url: str
    label: str | None = None


class OpenRouterClient:
    """One shared OpenRouter HTTP client for the app lifetime. Reuse; do not create per task.

    Every LLM call in the app goes through this client. Model IDs are always chosen by the
    caller, never hardcoded here. HTTP failures are normalised to ``OpenRouterError`` so callers
    only ever handle one error type.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout: float = 60.0,
        image_timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter api_key is required")
        if not base_url:
            raise ValueError("OpenRouter base_url is required")

        self._image_timeout = image_timeout
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def chat_completions(
        self, body: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        """POST /chat/completions. Returns the raw JSON body."""
        return self._post_json("/chat/completions", body, timeout=timeout)

    def create_image(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /images. Returns the raw JSON body."""
        return self._post_json("/images", body, timeout=self._image_timeout)

    def generate_text(
        self,
        prompt: str,
        *,
        model: str,
        image_urls: list[str] | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """Generate text from a prompt. Caller picks the model; extra params are sent when given.

        ``image_urls`` (remote or ``data:`` URLs) attach reference images to the user message so a
        vision-capable model can reason over them (e.g. see the product before writing prompts).
        ``json_mode`` constrains the model's decoding so it cannot emit syntactically invalid JSON
        (a stray token breaking ``json.loads``); it does not guarantee the JSON's *content* is what
        the caller asked for, only that it parses.
        """
        if not model:
            raise ValueError("model is required")

        user_content: Any = prompt
        if image_urls:
            user_content = [{"type": "text", "text": prompt}]
            user_content.extend(
                {"type": "image_url", "image_url": {"url": url}} for url in image_urls
            )

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})

        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        return self._message_text(self.chat_completions(body))

    def generate_gemini_image(
        self,
        prompt: str,
        *,
        model: str,
        references: list[ReferenceImage] | None = None,
        aspect_ratio: str = "1:1",
    ) -> GeneratedImage:
        """Generate an image via chat + modalities, using Gemini's request shape specifically.

        Named for the provider (not just "generate_image") because the request body here is NOT
        provider-agnostic: ``aspect_ratio`` is sent nested under ``image_config``, which is Gemini's
        own convention on OpenRouter. A different image-capable model (e.g. an OpenAI image model)
        expects aspect/size controlled a different way, so swapping ``model`` alone would silently
        stop honoring aspect ratio — a genuinely different provider needs its own method here, not
        a param on this one.

        ``references`` (remote or ``data:`` URLs) are attached to the message, each preceded by its
        label, so the model knows each image's role (e.g. product source-of-truth, brand logo).
        One attempt, no retry.
        """
        if not model:
            raise ValueError("model is required")

        content: Any = prompt
        if references:
            content = [{"type": "text", "text": prompt}]
            for ref in references:
                if ref.label:
                    content.append({"type": "text", "text": ref.label})
                content.append({"type": "image_url", "image_url": {"url": ref.url}})

        body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": aspect_ratio},
        }
        return self._image_from_chat(self.chat_completions(body, timeout=self._image_timeout))

    def generate_gpt_image(
        self,
        prompt: str,
        *,
        model: str,
        references: list[ReferenceImage] | None = None,
        aspect_ratio: str = "1:1",
    ) -> GeneratedImage:
        """Generate an image via OpenAI's dedicated Images API (POST /images) — a different
        endpoint and request shape than Gemini's chat-completions-with-modalities approach (see
        ``generate_gemini_image``); OpenRouter documents gpt-image models as generating through
        this dedicated Images API, not chat completions.

        ``references`` go under ``input_references`` — confirmed live against the real API; unlike
        ``generate_gemini_image``, there is no per-reference text label here, so role context (e.g.
        "this is the product photo") has to live in ``prompt`` itself if it matters.

        ``aspect_ratio`` support is far narrower than Gemini's: confirmed live, gpt-image-1 only
        accepts ``"1:1"``, ``"3:2"``, ``"2:3"``, or ``"auto"`` — anything else is rejected with a
        400. One attempt, no retry.
        """
        if not model:
            raise ValueError("model is required")

        body: dict[str, Any] = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio}
        if references:
            body["input_references"] = [
                {"type": "image_url", "image_url": {"url": ref.url}} for ref in references
            ]

        return self._image_from_images_api(self.create_image(body))

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
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise OpenRouterError(
                f"OpenRouter {path} failed [{exc.response.status_code}]: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenRouterError(f"OpenRouter {path} request error: {exc}") from exc
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
        return OpenRouterClient._decode_b64_image(b64_data, content_type)

    @staticmethod
    def _image_from_images_api(data: dict[str, Any]) -> GeneratedImage:
        try:
            entry = data["data"][0]
            b64_data = entry["b64_json"]
            content_type = entry["media_type"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter images response missing image data") from exc

        return OpenRouterClient._decode_b64_image(b64_data, content_type)

    @staticmethod
    def _decode_b64_image(b64_data: str, content_type: str) -> GeneratedImage:
        if not content_type.startswith("image/"):
            raise OpenRouterError(f"Unexpected image content type: {content_type}")

        try:
            content = base64.b64decode(b64_data, validate=True)
        except binascii.Error as exc:
            raise OpenRouterError("OpenRouter returned invalid image base64") from exc

        if not content:
            raise OpenRouterError("OpenRouter returned empty image data")

        return GeneratedImage(content=content, content_type=content_type)
