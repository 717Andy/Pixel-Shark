import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from pixelshark_perception.backends import (
    MockBackend,
    OpenAICompatibleBackend,
    TransformersQwenBackend,
    VlmRequest,
    backend_from_env,
    chat_completions_body,
    message_text,
)
from pixelshark_perception.errors import PerceptionError


def test_chat_body_embeds_the_image_and_optional_json_mode():
    body = chat_completions_body(
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        prompt="read the table",
        image=b"\x89PNG\r\n",
        json_mode=True,
        max_tokens=128,
        temperature=0,
    )
    assert body["model"].startswith("Qwen/")
    assert body["response_format"] == {"type": "json_object"}
    content = body["messages"][1]["content"]
    assert content[0]["text"] == "read the table"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_message_text_accepts_a_string_or_a_list():
    assert message_text({"choices": [{"message": {"content": '{"a": 1}'}}]}) == '{"a": 1}'
    payload = {"choices": [{"message": {"content": [{"type": "text", "text": "hi"}]}}]}
    assert message_text(payload) == "hi"


def test_local_and_hosted_are_selected_by_env_without_a_network_call():
    local = backend_from_env({"PIXELSHARK_VLM": "local"})
    assert local.name == "local"
    assert local.base_url == "http://127.0.0.1:8001/v1"
    assert local.model == "Qwen/Qwen2.5-VL-7B-Instruct"
    assert local.json_mode is False
    hosted = backend_from_env(
        {
            "PIXELSHARK_VLM": "hosted",
            "PIXELSHARK_VLM_API_KEY": "sk-test",
            "PIXELSHARK_VLM_MODEL": "gpt-4o",
        }
    )
    assert hosted.name == "hosted"
    assert hosted.base_url == "https://api.openai.com/v1"
    assert hosted.json_mode is True
    with pytest.raises(PerceptionError, match="PIXELSHARK_VLM_API_KEY"):
        backend_from_env({"PIXELSHARK_VLM": "hosted"})


def test_mock_json_file_is_the_script(tmp_path):
    script = tmp_path / "one.json"
    script.write_text('{"ok": true}')
    backend = backend_from_env({"PIXELSHARK_VLM": "mock", "PIXELSHARK_VLM_MOCK_JSON": str(script)})
    assert isinstance(backend, MockBackend)
    assert backend.complete(VlmRequest(image=b"x", prompt="p")) == '{"ok": true}'


def test_http_backend_posts_the_picture_and_reads_the_reply():
    seen: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            length = int(self.headers["Content-Length"])
            seen["body"] = json.loads(self.rfile.read(length))
            seen["auth"] = self.headers["Authorization"]
            seen["path"] = self.path
            data = json.dumps({"choices": [{"message": {"content": '{"street":"flop"}'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        backend = OpenAICompatibleBackend(
            name="hosted",
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key="sk-test",
            model="gpt-4o",
            json_mode=True,
            timeout=5,
        )
        text = backend.complete(VlmRequest(image=b"\x89PNG", prompt="look"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert text == '{"street":"flop"}'
    assert seen["auth"] == "Bearer sk-test"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["messages"][1]["content"][0]["text"] == "look"


def test_http_error_does_not_include_a_successful_parse():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            data = b'{"error":"nope"}'
            self.send_response(401)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        backend = OpenAICompatibleBackend(
            name="hosted",
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key="sk-test",
            model="gpt-4o",
            timeout=5,
        )
        with pytest.raises(PerceptionError, match="HTTP 401"):
            backend.complete(VlmRequest(image=b"png", prompt="look"))
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_qwen_backend_explains_a_missing_install(monkeypatch):
    real_import = __import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name.split(".")[0] in {"torch", "transformers"}:
            raise ImportError("blocked for the test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded)
    backend = TransformersQwenBackend()
    with pytest.raises(PerceptionError, match="transformers"):
        backend.complete(VlmRequest(image=b"png", prompt="hi"))
