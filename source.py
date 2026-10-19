"""Single HTML GET transport. No cookies, telemetry, JS or image downloads."""

from __future__ import annotations

import asyncio

import aiohttp

from .core import DataError, http_url


async def fetch_html(url: str, timeout_seconds: int = 15, max_bytes: int = 3145728) -> str:
    if not http_url(url):
        raise DataError("请配置不含账号密码的有效 HTTP(S) 页面地址。")
    if max_bytes < 1 or timeout_seconds < 1:
        raise DataError("请求大小或超时配置无效。")
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    try:
        async with aiohttp.ClientSession(
            timeout=timeout, headers=headers, cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200:
                    raise DataError(f"数据源返回 HTTP {response.status}。")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise DataError("数据源未返回 HTML 页面。")
                if response.content_length and response.content_length > max_bytes:
                    raise DataError("页面响应超过大小限制。")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise DataError("页面响应超过大小限制。")
                try:
                    return body.decode(response.charset or "utf-8")
                except (UnicodeError, LookupError) as exc:
                    raise DataError("页面字符编码无效。") from exc
    except asyncio.TimeoutError as exc:
        raise DataError("数据源请求超时，请稍后重试。") from exc
    except aiohttp.ClientError as exc:
        raise DataError("数据源网络请求失败，请检查网络和页面配置。") from exc
