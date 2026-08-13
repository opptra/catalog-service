import base64
import binascii
import json
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
        # High-quality GPT Image can take several minutes with references.
        image_timeout: float = 600.0,
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
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Generate free-form text from a prompt. Caller picks the model.

        ``image_urls`` (remote or ``data:`` URLs) attach reference images to the user message so a
        vision-capable model can reason over them. For structured JSON outputs, use
        ``call_tool`` instead of asking the model to emit JSON in the message body.

        ``cache_prefix`` (when set) is sent as a leading text block with ``cache_control`` so
        OpenRouter can reuse stable context across sequential calls. ``session_id`` enables
        sticky routing for higher cache-hit rates.
        """
        if not model:
            raise ValueError("model is required")

        body = self._chat_body(
            prompt,
            model=model,
            image_urls=image_urls,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            cache_prefix=cache_prefix,
            session_id=session_id,
        )
        return self._message_text(self.chat_completions(body))

    def call_tool(
        self,
        prompt: str,
        *,
        model: str,
        tool: dict[str, Any],
        image_urls: list[str] | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Force the model to call ``tool`` and return its parsed arguments as a dict.

        Used for structured outputs: the tool is never executed — its JSON Schema parameters
        *are* the payload. Prefer this over free-form ``response_format: json_object`` strings.
        """
        if not model:
            raise ValueError("model is required")
        try:
            tool_name = tool["function"]["name"]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "tool must be an OpenAI-style function tool with function.name"
            ) from exc
        if not tool_name:
            raise ValueError("tool function.name is required")

        body = self._chat_body(
            prompt,
            model=model,
            image_urls=image_urls,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            cache_prefix=cache_prefix,
            session_id=session_id,
        )
        body["tools"] = [tool]
        body["tool_choice"] = {"type": "function", "function": {"name": tool_name}}
        return self._tool_arguments(self.chat_completions(body), tool_name=tool_name)

    def _chat_body(
        self,
        prompt: str,
        *,
        model: str,
        image_urls: list[str] | None,
        system: str | None,
        temperature: float | None,
        max_tokens: int | None,
        cache_prefix: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        prefix = cache_prefix or ""
        cache_prefix_block = bool(prefix.strip())
        use_multipart = cache_prefix_block or bool(image_urls)

        if use_multipart:
            user_content: Any = []
            if cache_prefix_block:
                user_content.append(
                    {
                        "type": "text",
                        "text": prefix,
                        "cache_control": {"type": "ephemeral"},
                    }
                )
            user_content.append({"type": "text", "text": prompt})
            if image_urls:
                user_content.extend(
                    {"type": "image_url", "image_url": {"url": url}} for url in image_urls
                )
        else:
            user_content = prompt

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})

        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if session_id:
            body["session_id"] = session_id
        return body

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
        label, so the model knows each image's role (e.g. which product-angle it is).
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
        """Generate an image via OpenRouter's dedicated Images API (POST /images) for GPT Image.

        Different endpoint and request shape than ``generate_gemini_image`` (chat + modalities).
        ``references`` go under ``input_references`` with no per-reference text labels — any role
        context must live in ``prompt``. Always requests ``quality=auto``. One attempt, no retry.
        """
        return self._generate_via_images_api(
            prompt,
            model=model,
            references=references,
            aspect_ratio=aspect_ratio,
            quality="auto",
        )

    def _generate_via_images_api(
        self,
        prompt: str,
        *,
        model: str,
        references: list[ReferenceImage] | None,
        aspect_ratio: str,
        quality: str | None = None,
    ) -> GeneratedImage:
        if not model:
            raise ValueError("model is required")

        body: dict[str, Any] = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio}
        if quality is not None:
            body["quality"] = quality
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
    def _tool_arguments(data: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
        try:
            tool_calls = data["choices"][0]["message"]["tool_calls"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter response missing tool_calls") from exc

        if not isinstance(tool_calls, list) or not tool_calls:
            raise OpenRouterError("OpenRouter returned empty tool_calls")

        chosen: dict[str, Any] | None = None
        for call in tool_calls:
            try:
                if call["function"]["name"] == tool_name:
                    chosen = call
                    break
            except (KeyError, TypeError):
                continue
        if chosen is None:
            raise OpenRouterError(f"OpenRouter did not call required tool {tool_name!r}")

        try:
            raw_args = chosen["function"]["arguments"]
        except (KeyError, TypeError) as exc:
            raise OpenRouterError("OpenRouter tool call missing arguments") from exc

        if isinstance(raw_args, dict):
            return raw_args
        if not isinstance(raw_args, str) or not raw_args.strip():
            raise OpenRouterError("OpenRouter tool arguments were empty")

        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise OpenRouterError("OpenRouter tool arguments were not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OpenRouterError("OpenRouter tool arguments were not a JSON object")
        return parsed

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
            content_type = entry.get("media_type") or "image/png"
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
