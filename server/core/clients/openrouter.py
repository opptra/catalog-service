import base64
import binascii
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from core.exceptions import OpenRouterError

_RETRY_STATUSES = {429, 502, 503, 529}
_RETRY_ATTEMPTS = 3


def _payload_error(data: dict[str, Any]) -> str | None:
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
        return str(message) if message else str(error)
    if isinstance(error, str) and error.strip():
        return error.strip()
    return None


def _short_http_detail(response: httpx.Response) -> str:
    text = (response.text or "").strip()
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type or text.startswith("<!"):
        return f"HTTP {response.status_code}"
    return text[:500]


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    """An input image (remote or ``data:`` URL) with an optional label describing its role."""

    url: str
    label: str | None = None


def attribution_session_id(*, user_external_id: UUID, brand_external_id: UUID) -> str:
    """OpenRouter ``session_id`` for spend grouping: ``{user}:{brand}`` (≤256 chars)."""
    return f"{user_external_id}:{brand_external_id}"


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
        timeout: float | None = None,
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
        return self._tool_arguments(
            self.chat_completions(body, timeout=timeout),
            tool_name=tool_name,
        )

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
        session_id: str | None = None,
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

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": aspect_ratio},
        }
        if session_id:
            body["session_id"] = session_id
        return self._image_from_chat(self.chat_completions(body, timeout=self._image_timeout))

    def generate_gpt_image(
        self,
        prompt: str,
        *,
        model: str,
        references: list[ReferenceImage] | None = None,
        aspect_ratio: str = "1:1",
        session_id: str | None = None,
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
            session_id=session_id,
        )

    def _generate_via_images_api(
        self,
        prompt: str,
        *,
        model: str,
        references: list[ReferenceImage] | None,
        aspect_ratio: str,
        quality: str | None = None,
        session_id: str | None = None,
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
        if session_id:
            body["session_id"] = session_id

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
        last_error: OpenRouterError | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = self._http.post(path, json=body, timeout=timeout)
                if response.status_code in _RETRY_STATUSES and attempt < _RETRY_ATTEMPTS - 1:
                    last_error = OpenRouterError(
                        f"OpenRouter {path} failed [{response.status_code}]: "
                        f"{_short_http_detail(response)}"
                    )
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = OpenRouterError(
                    f"OpenRouter {path} failed [{exc.response.status_code}]: "
                    f"{_short_http_detail(exc.response)}"
                )
                if exc.response.status_code in _RETRY_STATUSES and attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(2**attempt)
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                raise OpenRouterError(f"OpenRouter {path} request error: {exc}") from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise OpenRouterError(
                    f"OpenRouter {path} returned non-JSON [{response.status_code}]"
                ) from exc
            if not isinstance(data, dict):
                raise OpenRouterError(f"OpenRouter {path} returned a non-object")
            payload_error = _payload_error(data)
            if payload_error:
                raise OpenRouterError(f"OpenRouter error: {payload_error}")
            return data
        raise last_error or OpenRouterError(f"OpenRouter {path} failed")

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
        payload_error = _payload_error(data)
        if payload_error:
            raise OpenRouterError(f"OpenRouter error: {payload_error}")
        try:
            choice = data["choices"][0]
            message = choice["message"]
            tool_calls = message["tool_calls"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter response missing tool_calls") from exc

        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        finish_note = f" finish_reason={finish_reason!r}" if finish_reason is not None else ""

        if not isinstance(tool_calls, list) or not tool_calls:
            raise OpenRouterError(f"OpenRouter returned empty tool_calls{finish_note}")

        chosen: dict[str, Any] | None = None
        for call in tool_calls:
            try:
                if call["function"]["name"] == tool_name:
                    chosen = call
                    break
            except (KeyError, TypeError):
                continue
        if chosen is None:
            names: list[str] = []
            for call in tool_calls:
                try:
                    names.append(str(call["function"]["name"]))
                except (KeyError, TypeError):
                    names.append("<unreadable>")
            raise OpenRouterError(
                f"OpenRouter did not call required tool {tool_name!r}; got {names!r}{finish_note}"
            )

        try:
            raw_args = chosen["function"]["arguments"]
        except (KeyError, TypeError) as exc:
            raise OpenRouterError(
                f"OpenRouter tool call missing arguments tool={tool_name!r}{finish_note}"
            ) from exc

        if isinstance(raw_args, dict):
            return raw_args
        if not isinstance(raw_args, str) or not raw_args.strip():
            raise OpenRouterError(
                f"OpenRouter tool arguments were empty tool={tool_name!r}{finish_note}"
            )

        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise OpenRouterError(
                "OpenRouter tool arguments were not valid JSON "
                f"tool={tool_name!r}{finish_note}; "
                f"{_tool_args_debug(raw_args, decode_error=exc)}"
            ) from exc
        if not isinstance(parsed, dict):
            raise OpenRouterError(
                "OpenRouter tool arguments were not a JSON object "
                f"tool={tool_name!r} type={type(parsed).__name__}{finish_note}; "
                f"{_tool_args_debug(raw_args)}"
            )
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


def _tool_args_debug(
    raw_args: str,
    *,
    decode_error: json.JSONDecodeError | None = None,
) -> str:
    """Compact, log-safe detail for malformed tool argument strings."""
    parts = [f"args_len={len(raw_args)}"]
    stripped = raw_args.rstrip()
    if stripped and stripped[-1] not in ("}", "]"):
        parts.append("looks_truncated=true")
    if decode_error is not None:
        parts.append(f"json_msg={decode_error.msg!r}")
        parts.append(f"json_pos={decode_error.pos}")
        start = max(0, decode_error.pos - 120)
        end = min(len(raw_args), decode_error.pos + 120)
        parts.append(f"near={raw_args[start:end]!r}")
    else:
        parts.append(f"preview={raw_args[:400]!r}")
    return "; ".join(parts)
