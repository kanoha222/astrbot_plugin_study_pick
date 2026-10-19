"""Neutral-data unit tests and loopback-only HTTP integration tests."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import random
import sys
import threading
import time
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT.parent))
core = importlib.import_module(PLUGIN_ROOT.name + ".core")
source = importlib.import_module(PLUGIN_ROOT.name + ".source")


def page(videos, **extra):
    payload = {"years": [2025, 2026], "videos": videos, "pools": {}, "initialVideo": None}
    payload.update(extra)
    return '<!doctype html><html><script id="lucky-data" type="application/json">' + json.dumps(payload, ensure_ascii=False) + "</script></html>"


def item(identifier="neutral-1", title="中性测试记录", **extra):
    value = {
        "videoId": identifier,
        "code": "DEMO-001",
        "title": title,
        "coverUrl": "https://example.test/neutral-cover.jpg",
        "scope": "demo",
        "year": 2026,
        "description": "这是用于接口测试的虚构学习资料。",
    }
    value.update(extra)
    return value


class ParseTests(unittest.TestCase):
    def test_data_error_is_a_value_error(self):
        self.assertTrue(issubclass(core.DataError, ValueError))

    def test_array_payload(self):
        records = core.parse_html(page([item()]))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].video_id, "neutral-1")
        self.assertEqual(records[0].title, "中性测试记录")
        self.assertEqual(records[0].cover_url, "https://example.test/neutral-cover.jpg")

    def test_object_payload(self):
        records = core.parse_html(page({"neutral-1": item()}))
        self.assertEqual([record.title for record in records], ["中性测试记录"])

    def test_invalid_rows_are_ignored(self):
        rows = [item(), item("missing-title", title=""), item("unsafe", coverUrl="javascript:alert(1)"), None, "not an object"]
        records = core.parse_html(page(rows))
        self.assertEqual([record.video_id for record in records], ["neutral-1"])

    def test_no_executable_script_evaluation(self):
        with self.assertRaises(core.DataError):
            core.parse_html('<script id="lucky-data">window.location="https://example.test/";</script>')

    def test_missing_malformed_and_empty_payloads(self):
        for html in ("<html></html>", '<script id="lucky-data">{</script>', page([]), page([item(title="")])):
            with self.subTest(html=html), self.assertRaises(core.DataError):
                core.parse_html(html)

    def test_record_is_immutable(self):
        record = core.Record("1", "DEMO", "标题", "https://example.test/one.jpg")
        with self.assertRaises(FrozenInstanceError):
            record.title = "changed"


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            core.Record("a", "A", "资料 A", "https://example.test/a.jpg", scope="first", year=2025),
            core.Record("b", "B", "资料 B", "https://example.test/b.jpg", scope="first", year=2026),
            core.Record("c", "C", "资料 C", "https://example.test/c.jpg", scope="second", year=2026),
        ]

    def test_default_filter_retains_all(self):
        self.assertEqual(core.filter_records(self.records), self.records)

    def test_scope_and_year_filter(self):
        self.assertEqual(core.filter_records(self.records, scope="first", year=2026), [self.records[1]])
        self.assertEqual(core.filter_records(self.records, year=2026), self.records[1:])
        self.assertEqual(core.filter_records(self.records, scope="absent"), [])

    def test_previous_record_is_excluded(self):
        for seed in range(20):
            chosen = core.choose_record(self.records, previous_id="a", rng=random.Random(seed))
            self.assertIn(chosen, self.records[1:])

    def test_single_record_may_repeat(self):
        self.assertEqual(core.choose_record(self.records[:1], previous_id="a"), self.records[0])

    def test_empty_pool_is_a_data_error(self):
        with self.assertRaises(core.DataError):
            core.choose_record([])


class FormattingTests(unittest.TestCase):
    def test_description_and_image_link_are_present(self):
        record = core.Record("1", "DEMO-001", "测试学习资料", "https://example.test/one.jpg", description="中性测试简介。")
        message = core.format_record(record)
        for value in ("测试学习资料", "中性测试简介。", "https://example.test/one.jpg"):
            self.assertIn(value, message)

    def test_missing_description_uses_metadata(self):
        record = core.Record("2", "DEMO-002", "无简介测试资料", "https://example.test/two.jpg", year=2026, duration_minutes=15, categories=("测试", "学习"))
        message = core.format_record(record)
        for value in ("DEMO-002", "2026", "15", "测试", "学习", "https://example.test/two.jpg"):
            self.assertIn(value, message)
        self.assertNotIn("这是用于接口测试的虚构学习资料", message)


class LoopbackHandler(BaseHTTPRequestHandler):
    requests_seen = []

    def do_GET(self):
        type(self).requests_seen.append({"path": self.path, "headers": dict(self.headers.items())})
        if self.path == "/status":
            self.send_response(503)
            body = b"temporary test failure"
        elif self.path in ("/large", "/stream-large"):
            self.send_response(200)
            body = b"x" * 4096
        elif self.path == "/slow":
            time.sleep(1.15)
            self.send_response(200)
            body = b"slow neutral test page"
        else:
            self.send_response(200)
            body = page([item()]).encode("utf-8")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if self.path != "/stream-large":
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, format, *args):
        pass


@contextmanager
def loopback_server():
    LoopbackHandler.requests_seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_get_headers_and_parse(self):
        with loopback_server() as base:
            html = await source.fetch_html(base + "/ok")
        self.assertEqual(len(core.parse_html(html)), 1)
        request = LoopbackHandler.requests_seen[-1]
        self.assertEqual(request["path"], "/ok")
        headers = {name.lower(): value for name, value in request["headers"].items()}
        self.assertIn("Mozilla/5.0", headers.get("user-agent", ""))
        self.assertIn("text/html", headers.get("accept", ""))
        self.assertNotIn("cookie", headers)

    async def test_non_success_status_is_data_error(self):
        with loopback_server() as base, self.assertRaises(core.DataError):
            await source.fetch_html(base + "/status")

    async def test_response_size_limit(self):
        with loopback_server() as base, self.assertRaises(core.DataError):
            await source.fetch_html(base + "/large", max_bytes=128)

    async def test_response_size_limit_without_content_length(self):
        with loopback_server() as base, self.assertRaises(core.DataError):
            await source.fetch_html(base + "/stream-large", max_bytes=128)

    async def test_timeout_is_data_error(self):
        with loopback_server() as base, self.assertRaises(core.DataError) as caught:
            await source.fetch_html(base + "/slow", timeout_seconds=1)
        self.assertIn("超时", str(caught.exception))
        self.assertEqual(LoopbackHandler.requests_seen[-1]["path"], "/slow")


if __name__ == "__main__":
    unittest.main()
