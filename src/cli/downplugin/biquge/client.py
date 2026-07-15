"""笔趣阁小说下载客户端 — API 加密 + 内容抓取。"""
import hashlib
import json
import time
import base64
from typing import Optional
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from src.core.logging import get_logger

logger = get_logger("akm.biquge")


class BiqugeClient:
    """笔趣阁 API 客户端，处理 token 加密与请求。"""

    API_HOSTS = [
        "https://7e59f968e71c.bqg971.xyz",
        "https://apibi.cc",
    ]
    TOKEN_KEY = "book@token.html"

    def __init__(self, timeout: int = 15):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://7e59f968e71c.bqg971.xyz/",
        })
        self.timeout = timeout
        self._api_host: Optional[str] = None
        self._rate_last = 0.0
        self._rate_gap = 0.05

    def _rate_limit(self):
        now = time.monotonic()
        gap = now - self._rate_last
        if gap < self._rate_gap:
            time.sleep(self._rate_gap - gap)
        self._rate_last = time.monotonic()

    def _make_token(self, book_id: int, chapter_id: int) -> str:
        code = hashlib.md5(self.TOKEN_KEY.encode()).hexdigest()
        key = code[16:].encode()
        iv = code[:16].encode()
        payload = json.dumps({"id": book_id, "chapterid": chapter_id}, separators=(",", ":"))
        cipher = AES.new(key, AES.MODE_CBC, iv)
        ct = cipher.encrypt(pad(payload.encode(), 16))
        return base64.b64encode(ct).decode()

    def _api_get(self, path: str, params: dict = None, host_idx: int = 0) -> dict:
        self._rate_limit()
        host = self.API_HOSTS[host_idx % len(self.API_HOSTS)]
        url = f"{host}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            if host_idx + 1 < len(self.API_HOSTS):
                logger.debug("API %s 失败，切换备用", host)
                return self._api_get(path, params, host_idx + 1)
            raise

    def get_book(self, book_id: int) -> dict:
        return self._api_get("/api/book", {"id": book_id})

    def get_booklist(self, dir_id: int) -> list[str]:
        data = self._api_get("/api/booklist", {"id": dir_id})
        return data.get("list", [])

    def get_chapter(self, book_id: int, chapter_id: int) -> dict:
        token = self._make_token(book_id, chapter_id)
        return self._api_get("/api/chapter", {"token": token}, host_idx=1)
