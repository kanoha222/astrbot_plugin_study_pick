"""Neutral record parsing, filtering and rendering; independent of AstrBot."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urlsplit


class DataError(ValueError):
    """An expected, user-readable source or selection error."""


@dataclass(frozen=True)
class Record:
    video_id: str
    code: str
    title: str
    cover_url: str
    scope: str = ""
    year: int | None = None
    release_date: str = ""
    duration_minutes: int | None = None
    score: str = ""
    description: str = ""
    categories: tuple[str, ...] = ()


def http_url(value: object) -> str:
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        _ = parsed.port
    except ValueError:
        return ""
    return value


def _text(value: object, limit: int = 600) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    return " ".join(str(value).split())[:limit]


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(str(value))
    except (ValueError, TypeError):
        return None
    return result if result >= 0 else None


class _DataScript(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.active = False
        self.chunks: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script" and dict(attrs).get("id") == "lucky-data":
            self.active = True
            self.chunks = []

    def handle_data(self, data):
        if self.active:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.active:
            self.scripts.append("".join(self.chunks))
            self.active = False


def parse_html(html: str) -> list[Record]:
    """Read ONLY script#lucky-data; never run page JavaScript or telemetry."""
    if len(html.encode("utf-8")) > 3 * 1024 * 1024:
        raise DataError("页面数据过大。")
    parser = _DataScript()
    parser.feed(html)
    if len(parser.scripts) != 1:
        raise DataError("页面必须包含唯一的 script#lucky-data 数据块。")
    try:
        payload = json.loads(parser.scripts[0])
    except (ValueError, RecursionError) as exc:
        raise DataError("页面内的 JSON 数据无效。") from exc
    if not isinstance(payload, dict):
        raise DataError("页面数据的顶层必须是对象。")
    videos = payload.get("videos")
    if isinstance(videos, dict):
        entries = list(videos.items())
    elif isinstance(videos, list):
        entries = list(enumerate(videos))
    else:
        raise DataError("页面数据缺少 videos 对象或数组。")
    records: list[Record] = []
    seen: set[str] = set()
    for key, item in entries:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 160)
        cover = http_url(item.get("coverUrl"))
        if not title or not cover or len(cover) > 2048:
            continue
        video_id = _text(item.get("videoId", key), 120) or str(key)
        if video_id in seen:
            continue
        seen.add(video_id)
        cats = item.get("categories", [])
        categories = tuple(_text(c, 60) for c in cats if _text(c, 60)) if isinstance(cats, list) else ()
        records.append(Record(
            video_id=video_id, code=_text(item.get("code"), 80), title=title,
            cover_url=cover, scope=_text(item.get("scope"), 80),
            year=_integer(item.get("year")), release_date=_text(item.get("releaseDate"), 40),
            duration_minutes=_integer(item.get("durationMinutes")),
            score=_text(item.get("score"), 30), description=_text(item.get("description")),
            categories=categories[:10],
        ))
    if not records:
        raise DataError("页面中没有包含标题和有效图片链接的记录。")
    return records


def filter_records(records: Iterable[Record], scope: str = "all", year: int = 0) -> list[Record]:
    return [r for r in records if (scope == "all" or r.scope == scope)
            and (not year or r.year == year)]


def choose_record(records: Iterable[Record], previous_id: str | None = None, rng=None) -> Record:
    pool = list(records)
    if not pool:
        raise DataError("没有符合当前分类和年份条件的记录。")
    candidates = [r for r in pool if r.video_id != previous_id]
    return (rng if rng is not None else random).choice(candidates or pool)


def format_record(record: Record) -> str:
    details = []
    if record.code:
        details.append(f"编号：{record.code}")
    if record.release_date:
        details.append(f"日期：{record.release_date}")
    elif record.year is not None:
        details.append(f"年份：{record.year}")
    if record.duration_minutes is not None:
        details.append(f"时长：{record.duration_minutes} 分钟")
    if record.score:
        details.append(f"评分：{record.score}")
    if record.categories:
        details.append(f"标签：{'、'.join(record.categories)}")
    description = record.description or "；".join(details) or "数据源未提供简介。"
    lines = [record.title, f"介绍：{description}"]
    if record.description and details:
        lines.append("；".join(details))
    lines.append(f"图片链接：{record.cover_url}")
    return "\n".join(lines)
