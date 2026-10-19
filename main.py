"""AstrBot /学习: records are read exclusively from an HTTP HTML response."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .core import DataError, choose_record, filter_records, format_record, http_url, parse_html
from .source import fetch_html


class StudyPickPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._cache = []
        self._cache_until = 0.0
        self._cache_key = None
        self._load_lock = asyncio.Lock()
        self._previous: OrderedDict[str, str] = OrderedDict()

    async def initialize(self):
        # Lazy loading avoids network requests when installing/loading the plugin.
        pass

    def _integer_option(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            raise DataError(f"配置 {key} 必须是整数。")
        try:
            result = int(str(value))
        except (ValueError, TypeError) as exc:
            raise DataError(f"配置 {key} 必须是整数。") from exc
        if not minimum <= result <= maximum:
            raise DataError(f"配置 {key} 必须在 {minimum} 到 {maximum} 之间。")
        return result

    async def _records(self):
        url = self.config.get("source_url", "")
        if not http_url(url):
            raise DataError("请先在插件配置中填写 source_url（有效的 HTTP(S) HTML 页面地址）。")
        ttl = self._integer_option("cache_ttl_seconds", 0, 0, 3600)
        timeout = self._integer_option("timeout_seconds", 15, 1, 60)
        key = (url, ttl, timeout)
        async with self._load_lock:
            if self._cache and self._cache_key == key and time.monotonic() < self._cache_until:
                return self._cache
            html = await fetch_html(url, timeout_seconds=timeout)
            records = parse_html(html)
            self._cache = records
            self._cache_key = key
            self._cache_until = time.monotonic() + ttl
            return records

    @filter.command("学习")
    async def study(self, event: AstrMessageEvent):
        """随机返回一条记录的介绍和图片链接。"""
        try:
            year = self._integer_option("year", 0, 0, 9999)
            scope = self.config.get("scope", "all")
            if not isinstance(scope, str) or not scope.strip():
                raise DataError("scope 必须是分类字符串或 all。")
            records = await self._records()
            pool = filter_records(records, scope=scope.strip(), year=year)
            origin = str(getattr(event, "unified_msg_origin", "") or "default")
            avoid_repeat = self.config.get("avoid_repeat", True) is True
            record = choose_record(pool, self._previous.get(origin) if avoid_repeat else None)
            self._previous[origin] = record.video_id
            self._previous.move_to_end(origin)
            if len(self._previous) > 512:
                self._previous.popitem(last=False)
            text = format_record(record)
            yield event.plain_result(text)
        except DataError as exc:
            yield event.plain_result(f"学习失败：{exc}")
        except Exception as exc:
            # Never log the response body, configured URL, tokens or cookies.
            logger.warning("study_pick internal error: %s", type(exc).__name__)
            yield event.plain_result("学习失败：插件内部错误，请检查文件或联系管理员。")

    async def terminate(self):
        self._cache = []
        self._cache_until = 0.0
        self._cache_key = None
        self._previous.clear()
