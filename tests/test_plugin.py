"""AstrBot event -> real loopback HTTP -> parser -> message integration tests.

Only the AstrBot API boundary is stubbed; no test contacts external hosts.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))


def passthrough_decorator(*args, **kwargs):
    def decorate(function):
        return function
    return decorate


class FakeStar:
    def __init__(self, context, *args, **kwargs):
        self.context = context


def astrbot_stubs():
    root = types.ModuleType("astrbot")
    root.__path__ = []
    api = types.ModuleType("astrbot.api")
    api.__path__ = []
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    api.AstrBotConfig = dict
    api.logger = types.SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None, exception=lambda *a, **k: None)
    event.filter = types.SimpleNamespace(command=passthrough_decorator)
    event.AstrMessageEvent = object
    star.Context = object
    star.Star = FakeStar
    star.register = passthrough_decorator
    root.api = api
    api.event = event
    api.star = star
    return {"astrbot": root, "astrbot.api": api, "astrbot.api.event": event, "astrbot.api.star": star}


class FakeEvent:
    unified_msg_origin = "test:neutral-session"
    session_id = "neutral-session"

    def get_sender_id(self):
        return "neutral-user"

    def get_session_id(self):
        return self.session_id

    def plain_result(self, text):
        return text


def neutral_record(identifier, title, image, scope="science", year=2026):
    return {
        "videoId": identifier, "code": "DEMO-" + identifier,
        "title": title, "coverUrl": image,
        "description": "服务器响应内提供的中性学习简介。",
        "scope": scope, "year": year,
    }


def neutral_page(records):
    payload = {"years": [2025, 2026], "videos": records, "pools": {}, "initialVideo": None}
    return ('<!doctype html><script id="lucky-data" type="application/json">'
            + json.dumps(payload, ensure_ascii=False) + "</script>")


class ResponseHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        state = self.server.test_state
        state.requests.append({"path": self.path, "headers": dict(self.headers.items())})
        path = urlsplit(self.path).path
        count = len(state.requests)
        status = state.forced_status or (503 if path == "/failure" else 200)
        if path == "/malformed":
            body = "<html>neutral response without a data block</html>"
        elif path == "/pool":
            body = neutral_page([
                neutral_record("one", "HTTP 科学资料一", "https://images.example.test/one.jpg"),
                neutral_record("two", "HTTP 科学资料二", "https://images.example.test/two.jpg"),
                neutral_record("three", "HTTP 自然资料三", "https://images.example.test/three.jpg", scope="nature", year=2025),
            ])
        elif path == "/dynamic":
            body = neutral_page([neutral_record("dynamic-" + str(count), "动态响应资料 " + str(count), "https://images.example.test/dynamic-" + str(count) + ".jpg")])
        else:
            name = "B" if path == "/source-b" else "A"
            body = neutral_page([neutral_record(name, "HTTP 来源 " + name, "https://images.example.test/source-" + name + ".jpg")])
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        pass


@contextmanager
def response_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ResponseHandler)
    server.daemon_threads = True
    state = types.SimpleNamespace(requests=[], forced_status=None)
    server.test_state = state
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class PluginTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.patcher = patch.dict(sys.modules, astrbot_stubs())
        cls.patcher.start()
        try:
            cls.main = importlib.import_module(PLUGIN_ROOT.name + ".main")
        except Exception:
            cls.patcher.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()

    async def message(self, plugin):
        results = [result async for result in plugin.study(FakeEvent())]
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], str)
        return results[0]

    def assert_failure(self, message):
        self.assertTrue(message.startswith("学习失败："), message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("图片链接", message)
        self.assertNotIn("【测试数据", message)

    async def test_inherits_star(self):
        self.assertTrue(issubclass(self.main.StudyPickPlugin, FakeStar))

    async def test_unconfigured_url_fails_without_network_or_local_data(self):
        plugin = self.main.StudyPickPlugin(None, {})
        with patch("aiohttp.ClientSession", side_effect=AssertionError("an empty URL must not open a session")) as session:
            try:
                await plugin.initialize()
                text = await self.message(plugin)
                self.assert_failure(text)
                self.assertIn("配置", text)
                session.assert_not_called()
            finally:
                await plugin.terminate()

    async def test_real_http_response_becomes_message(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/source-a"})
            try:
                await plugin.initialize()
                self.assertEqual(state.requests, [], "initialization should remain lazy")
                text = await self.message(plugin)
                self.assertIn("HTTP 来源 A", text)
                self.assertIn("服务器响应内提供的中性学习简介。", text)
                self.assertIn("https://images.example.test/source-A.jpg", text)
                self.assertNotIn("【测试数据", text)
                self.assertNotIn("占位链接", text)
                self.assertEqual(len(state.requests), 1)
                headers = {key.lower(): value for key, value in state.requests[0]["headers"].items()}
                self.assertIn("Mozilla/5.0", headers.get("user-agent", ""))
                self.assertIn("text/html", headers.get("accept", ""))
                self.assertNotIn("cookie", headers)
            finally:
                await plugin.terminate()

    async def test_legacy_fixture_mode_does_not_override_http_url(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_mode": "fixture", "source_url": base + "/source-b"})
            try:
                text = await self.message(plugin)
                self.assertIn("HTTP 来源 B", text)
                self.assertIn("https://images.example.test/source-B.jpg", text)
                self.assertEqual([request["path"] for request in state.requests], ["/source-b"])
                self.assertNotIn("【测试数据", text)
            finally:
                await plugin.terminate()

    async def test_default_zero_cache_reads_new_title_and_image_every_time(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/dynamic"})
            try:
                first = await self.message(plugin)
                second = await self.message(plugin)
                self.assertIn("动态响应资料 1", first)
                self.assertIn("https://images.example.test/dynamic-1.jpg", first)
                self.assertIn("动态响应资料 2", second)
                self.assertIn("https://images.example.test/dynamic-2.jpg", second)
                self.assertNotEqual(first, second)
                self.assertEqual(len(state.requests), 2)
            finally:
                await plugin.terminate()

    async def test_positive_cache_uses_response_but_url_change_invalidates_it(self):
        with response_server() as (base, state):
            config = {"source_url": base + "/dynamic", "cache_ttl_seconds": 300}
            plugin = self.main.StudyPickPlugin(None, config)
            try:
                first = await self.message(plugin)
                second = await self.message(plugin)
                self.assertEqual(first, second)
                self.assertIn("动态响应资料 1", second)
                self.assertEqual(len(state.requests), 1)
                config["source_url"] = base + "/source-b"
                changed = await self.message(plugin)
                self.assertIn("HTTP 来源 B", changed)
                self.assertIn("https://images.example.test/source-B.jpg", changed)
                self.assertNotIn("动态响应资料", changed)
                self.assertEqual(len(state.requests), 2)
            finally:
                await plugin.terminate()

    async def test_http_failure_does_not_fallback_to_local_data(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/failure", "source_mode": "fixture"})
            try:
                text = await self.message(plugin)
                self.assert_failure(text)
                self.assertIn("503", text)
                self.assertEqual(len(state.requests), 1)
            finally:
                await plugin.terminate()

    async def test_parse_failure_does_not_fallback_to_local_data(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/malformed"})
            try:
                self.assert_failure(await self.message(plugin))
                self.assertEqual(len(state.requests), 1)
            finally:
                await plugin.terminate()

    async def test_failed_refresh_does_not_reuse_an_old_response_by_default(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/source-a"})
            try:
                self.assertIn("HTTP 来源 A", await self.message(plugin))
                state.forced_status = 503
                self.assert_failure(await self.message(plugin))
                self.assertEqual(len(state.requests), 2)
            finally:
                await plugin.terminate()

    async def test_empty_candidate_pool_is_friendly_after_http(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/pool", "scope": "no-such-neutral-scope"})
            try:
                text = await self.message(plugin)
                self.assert_failure(text)
                self.assertIn("没有符合", text)
                self.assertEqual(len(state.requests), 1)
            finally:
                await plugin.terminate()

    async def test_scope_and_year_apply_to_the_http_response(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/pool", "scope": "nature", "year": 2025})
            try:
                text = await self.message(plugin)
                self.assertIn("HTTP 自然资料三", text)
                self.assertIn("https://images.example.test/three.jpg", text)
                self.assertEqual(len(state.requests), 1)
            finally:
                await plugin.terminate()

    async def test_http_pool_avoids_adjacent_repetition(self):
        with response_server() as (base, state):
            plugin = self.main.StudyPickPlugin(None, {"source_url": base + "/pool"})
            try:
                previous = None
                for _ in range(10):
                    text = await self.message(plugin)
                    self.assertIn("HTTP ", text)
                    self.assertNotEqual(text, previous)
                    previous = text
                self.assertEqual(len(state.requests), 10)
            finally:
                await plugin.terminate()

    async def test_invalid_configuration_is_friendly_and_does_not_request(self):
        cases = ({"year": "invalid"}, {"year": True}, {"scope": ""}, {"cache_ttl_seconds": -1}, {"timeout_seconds": 0})
        with response_server() as (base, state):
            for bad_options in cases:
                with self.subTest(options=bad_options):
                    config = {"source_url": base + "/pool", **bad_options}
                    plugin = self.main.StudyPickPlugin(None, config)
                    try:
                        self.assert_failure(await self.message(plugin))
                    finally:
                        await plugin.terminate()
            self.assertEqual(state.requests, [])

    async def test_invalid_url_does_not_open_network_session(self):
        plugin = self.main.StudyPickPlugin(None, {"source_url": "file:///not-an-http-page"})
        with patch("aiohttp.ClientSession", side_effect=AssertionError("invalid URL must not open a session")) as session:
            try:
                self.assert_failure(await self.message(plugin))
                session.assert_not_called()
            finally:
                await plugin.terminate()

    async def test_unexpected_error_does_not_disclose_source_url(self):
        secret_url = "https://example.test/private?token=NEUTRAL_SECRET"
        plugin = self.main.StudyPickPlugin(None, {"source_url": secret_url})
        fetch = AsyncMock(side_effect=RuntimeError("request failed: " + secret_url))
        with patch.object(self.main, "fetch_html", fetch):
            try:
                text = await self.message(plugin)
                self.assert_failure(text)
                self.assertNotIn(secret_url, text)
                self.assertNotIn("NEUTRAL_SECRET", text)
                fetch.assert_awaited_once()
            finally:
                await plugin.terminate()


if __name__ == "__main__":
    unittest.main()
