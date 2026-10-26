"""Where a vision-language model actually runs.

Tests and CI use :class:`MockBackend`, which returns text you wrote down. A
laptop with an NVIDIA GPU can run an open Qwen-VL model in-process
(:class:`TransformersQwenBackend`) or a local server that speaks the OpenAI
chat API (:class:`OpenAICompatibleBackend` with ``PIXELSHARK_VLM=local``).
The same HTTP class talks to a hosted API (``PIXELSHARK_VLM=hosted``).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pixelshark_perception.errors import PerceptionError

QWEN_INSTALL = "uv pip install torch torchvision transformers accelerate qwen-vl-utils pillow"
_DEFAULT_QWEN = "Qwen/Qwen2.5-VL-7B-Instruct"


@dataclass(frozen=True)
class VlmRequest:
    """One completion: the screenshot bytes and the prompt."""

    image: bytes
    prompt: str


class VlmBackend(Protocol):
    """Something that looks at a screenshot and returns text."""

    name: str

    def complete(self, request: VlmRequest) -> str:
        """Return the model's raw text. JSON parsing happens in the reader."""


class MockBackend:
    """Return scripted replies, in order. Never opens a network connection or a GPU."""

    name = "mock"

    def __init__(
        self,
        responses: Sequence[str] | Callable[[VlmRequest], str] | None = None,
    ) -> None:
        self._fn = responses if callable(responses) else None
        self._responses = [] if responses is None or callable(responses) else list(responses)
        self._index = 0
        self.calls: list[VlmRequest] = []

    def complete(self, request: VlmRequest) -> str:
        self.calls.append(request)
        if self._fn is not None:
            return self._fn(request)
        if self._index >= len(self._responses):
            raise PerceptionError(
                "The mock backend has no scripted answer. "
                "Pass responses=... in tests, or set PIXELSHARK_VLM_MOCK_JSON to a file. "
                "Choose a real model with PIXELSHARK_VLM=local, qwen, or hosted."
            )
        text = self._responses[self._index]
        self._index += 1
        return text


class OracleBackend:
    """Return ground truth the eval harness just stored. This is not a model.

    It exists so you can check that the report scores a perfect read as perfect,
    with no GPU and no API key.
    """

    name = "oracle"

    def __init__(self) -> None:
        self.response = ""

    def complete(self, request: VlmRequest) -> str:
        del request
        if not self.response:
            raise PerceptionError("the oracle backend has no ground truth for this frame")
        return self.response


class OpenAICompatibleBackend:
    """POST ``/chat/completions`` with an image, the way OpenAI's HTTP API does.

    Point ``base_url`` at a host (OpenAI, OpenRouter, or similar) or at a server
    on the laptop (vLLM, llama.cpp, or another OpenAI-compatible runtime)
    serving a Qwen-VL checkpoint.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        json_mode: bool = False,
        timeout: float = 120,
        max_tokens: int = 4096,
        temperature: float = 0,
        transport: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.json_mode = json_mode
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._transport = transport

    def complete(self, request: VlmRequest) -> str:
        url = f"{self.base_url}/chat/completions"
        body = chat_completions_body(
            model=self.model,
            prompt=request.prompt,
            image=request.image,
            json_mode=self.json_mode,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self._transport is not None:
            payload = self._transport(url, body, headers)
            return message_text(payload)
        encoded = json.dumps(body).encode()
        http_request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise PerceptionError(
                f"{self.name} backend returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise PerceptionError(
                f"{self.name} backend could not be reached at {url}: {exc.reason}"
            ) from exc
        if not isinstance(payload, dict):
            raise PerceptionError(f"{self.name} backend returned a non-object response")
        return message_text(payload)


class TransformersQwenBackend:
    """Run a Qwen-VL checkpoint in this process, on the NVIDIA GPU when one is present.

    The weights are not installed with the project. CI never constructs this
    class's model. See ``docs/perception.md`` for the laptop install.
    """

    name = "qwen"

    def __init__(
        self,
        model_id: str = _DEFAULT_QWEN,
        *,
        device: str = "cuda",
        load_in_4bit: bool = False,
        max_new_tokens: int = 4096,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.load_in_4bit = load_in_4bit
        self.max_new_tokens = max_new_tokens
        self._model: Any = None
        self._processor: Any = None

    def complete(self, request: VlmRequest) -> str:
        model, processor = self._ensure()
        return _qwen_generate(
            model,
            processor,
            image=request.image,
            prompt=request.prompt,
            max_new_tokens=self.max_new_tokens,
        )

    def _ensure(self) -> tuple[Any, Any]:
        if self._model is not None and self._processor is not None:
            return self._model, self._processor
        try:
            import torch
            from transformers import AutoProcessor
        except ImportError as exc:
            raise PerceptionError(
                "The local Qwen backend needs PyTorch and Transformers, which are not "
                "installed in CI. On the NVIDIA laptop run: "
                f"{QWEN_INSTALL}. Then set PIXELSHARK_VLM=qwen. "
                "Or serve the same weights with vLLM and set PIXELSHARK_VLM=local."
            ) from exc
        model_cls = _qwen_class(self.model_id)
        kwargs: dict[str, Any] = {}
        if self.load_in_4bit:
            kwargs["load_in_4bit"] = True
        elif self.device == "cpu":
            kwargs["torch_dtype"] = torch.float32
        else:
            kwargs["torch_dtype"] = torch.bfloat16
            kwargs["device_map"] = "auto"
        try:
            model = model_cls.from_pretrained(self.model_id, **kwargs)
            processor = AutoProcessor.from_pretrained(self.model_id)
        except Exception as exc:
            raise PerceptionError(
                f"could not load {self.model_id}. Check the model id, the GPU, and "
                f"that `{QWEN_INSTALL}` finished. Original error: {exc}"
            ) from exc
        if self.device == "cpu":
            model = model.to("cpu")
        model.eval()
        self._model = model
        self._processor = processor
        return model, processor


def chat_completions_body(
    *,
    model: str,
    prompt: str,
    image: bytes,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """The JSON body both the local server and the hosted API receive."""

    mime = "image/jpeg" if image.startswith(b"\xff\xd8") else "image/png"
    encoded = base64.b64encode(image).decode("ascii")
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "system",
                "content": "You output only one JSON object matching the user's schema.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ],
            },
        ],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def message_text(payload: dict[str, Any]) -> str:
    """Read the assistant text out of a chat-completions response."""

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PerceptionError(
            f"the model response had no message text: {str(payload)[:300]}"
        ) from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        if any(part.strip() for part in parts):
            return "".join(parts)
    raise PerceptionError("the model response content was not text")


def backend_from_env(env: Mapping[str, str] | None = None) -> VlmBackend:
    """Build the backend named by ``PIXELSHARK_VLM``.

    ``mock`` (the default) returns scripted JSON and is what CI uses.
    ``local`` calls an OpenAI-compatible server, meant for open weights on the
    laptop GPU. ``qwen`` loads Qwen-VL in-process. ``hosted`` calls a hosted
    chat API. ``oracle`` is only for the eval command.
    """

    values = os.environ if env is None else env
    kind = values.get("PIXELSHARK_VLM", "mock").strip().lower()
    if kind in {"", "mock"}:
        path = values.get("PIXELSHARK_VLM_MOCK_JSON", "").strip()
        if not path:
            return MockBackend([])
        return MockBackend([Path(path).read_text()])
    if kind == "oracle":
        raise PerceptionError(
            "PIXELSHARK_VLM=oracle is only valid as `pixelshark-perceive eval --backend oracle`"
        )
    if kind == "local":
        return OpenAICompatibleBackend(
            name="local",
            base_url=values.get("PIXELSHARK_VLM_BASE_URL", "http://127.0.0.1:8001/v1"),
            api_key=values.get("PIXELSHARK_VLM_API_KEY", "EMPTY"),
            model=values.get("PIXELSHARK_VLM_MODEL", _DEFAULT_QWEN),
            json_mode=_flag(values, "PIXELSHARK_VLM_JSON_MODE", default=False),
            timeout=_float(values, "PIXELSHARK_VLM_TIMEOUT", 180),
            max_tokens=_int(values, "PIXELSHARK_VLM_MAX_TOKENS", 4096),
            temperature=_float(values, "PIXELSHARK_VLM_TEMPERATURE", 0),
        )
    if kind == "hosted":
        key = (
            values.get("PIXELSHARK_VLM_API_KEY", "").strip()
            or values.get("OPENAI_API_KEY", "").strip()
        )
        if not key:
            raise PerceptionError(
                "the hosted backend needs PIXELSHARK_VLM_API_KEY (or OPENAI_API_KEY). "
                "CI does not set one; use the mock backend there."
            )
        return OpenAICompatibleBackend(
            name="hosted",
            base_url=values.get("PIXELSHARK_VLM_BASE_URL", "https://api.openai.com/v1"),
            api_key=key,
            model=values.get("PIXELSHARK_VLM_MODEL", "gpt-4o"),
            json_mode=_flag(values, "PIXELSHARK_VLM_JSON_MODE", default=True),
            timeout=_float(values, "PIXELSHARK_VLM_TIMEOUT", 120),
            max_tokens=_int(values, "PIXELSHARK_VLM_MAX_TOKENS", 4096),
            temperature=_float(values, "PIXELSHARK_VLM_TEMPERATURE", 0),
        )
    if kind == "qwen":
        return TransformersQwenBackend(
            model_id=values.get("PIXELSHARK_VLM_MODEL", _DEFAULT_QWEN),
            device=values.get("PIXELSHARK_QWEN_DEVICE", "cuda"),
            load_in_4bit=_flag(values, "PIXELSHARK_QWEN_4BIT", default=False),
            max_new_tokens=_int(values, "PIXELSHARK_VLM_MAX_TOKENS", 4096),
        )
    raise PerceptionError(f"unknown PIXELSHARK_VLM={kind!r}. Use mock, local, qwen, or hosted.")


def _flag(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _qwen_class(model_id: str) -> Any:
    import transformers

    lowered = model_id.lower()
    if "qwen3" in lowered:
        order = ("Qwen3VLForConditionalGeneration", "Qwen2_5_VLForConditionalGeneration")
    elif "qwen2.5" in lowered or "qwen2_5" in lowered:
        order = ("Qwen2_5_VLForConditionalGeneration", "Qwen2VLForConditionalGeneration")
    else:
        order = (
            "Qwen2_5_VLForConditionalGeneration",
            "Qwen3VLForConditionalGeneration",
            "Qwen2VLForConditionalGeneration",
        )
    for class_name in order:
        model_cls = getattr(transformers, class_name, None)
        if model_cls is not None:
            return model_cls
    raise PerceptionError(
        "transformers is installed but has no Qwen-VL model class. "
        "Upgrade transformers, or serve the checkpoint with vLLM and set PIXELSHARK_VLM=local."
    )


def _qwen_generate(
    model: Any, processor: Any, *, image: bytes, prompt: str, max_new_tokens: int
) -> str:
    import io

    import torch
    from PIL import Image

    try:
        picture = Image.open(io.BytesIO(image)).convert("RGB")
    except (OSError, ValueError) as exc:
        raise PerceptionError(
            f"the frame was not an image the Qwen backend can open: {exc}"
        ) from exc
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": picture},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    try:
        from qwen_vl_utils import process_vision_info

        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
    except ImportError:
        inputs = processor(text=[text], images=[picture], padding=True, return_tensors="pt")
    inputs = inputs.to(model.device)
    with torch.inference_mode():
        generated = model.generate(**inputs, max_new_tokens=max_new_tokens)
    trimmed = generated[:, inputs["input_ids"].shape[-1] :]
    decoded = processor.batch_decode(trimmed, skip_special_tokens=True)
    if not decoded:
        raise PerceptionError("Qwen returned no text")
    return str(decoded[0])
