import json
import copy
from pathlib import Path
from typing import Any, Optional

from src.core.config import get_project_root, load_config
from src.core.logging import get_logger

_logger = get_logger("akm.pixiv_config")

DEFAULTS = {
    "refresh_token": "",
    "cookie": "",
    "base_url": "https://www.pixiv.net",
    "ajax_url": "https://www.pixiv.net/ajax/illust",
    "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.pixiv.net/",
        "Origin": "https://www.pixiv.net",
        "Accept-Language": "zh-CN,zh;q=0.9",
    },
    "download": {
        "max_workers": 6,
        "timeout": 20,
        "rate_limit_rps": 1.5,
        "rate_limit_rps_authenticated": 3.0,
        "image_rate_limit_rps": 6.0,
        "image_rate_limit_rps_authenticated": 10.0,
        "retry_429": True,
        "retry_429_delay_seconds": 30,
    },
    "extractor": {
        "pixiv-user": {
            "rate_limit_rps": 1.5,
        },
        "pixiv-series": {
            "rate_limit_rps": 1.5,
        },
        "pixiv-work": {
            "rate_limit_rps": 1.5,
            "book_format": "epub",
            "ugoira_format": "gif",
            "image_quality": "high",
        },
        "pixiv-novel": {
            "embeds": True,
            "covers": True,
            "book_format": "epub",
        },
        "pixiv-search": {
            "max_pages": 10,
            "rate_limit_rps": 1.5,
        },
        "pixiv-ranking": {
            "rate_limit_rps": 1.5,
        },
    },
}


class PixivConfig:
    def __init__(self, data: dict[str, Any]):
        self._data = copy.deepcopy(data)

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self._data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key, {})
        return current if current != {} else default

    @property
    def refresh_token(self) -> str:
        return self.get("refresh_token", default="") or ""

    @property
    def cookie(self) -> str:
        return self.get("cookie", default="") or ""

    @cookie.setter
    def cookie(self, value: str):
        self._data["cookie"] = value

    @property
    def cookie_pool(self) -> list[str]:
        pool = self.get("cookie_pool")
        return pool if isinstance(pool, list) else []

    def add_to_pool(self, cookie: str) -> bool:
        cookie = cookie.strip()
        if not cookie:
            return False
        pool: list = self._data.setdefault("cookie_pool", [])
        if cookie not in pool:
            pool.append(cookie)
            return True
        return False

    def rotate_cookie(self, current_index: int) -> tuple[int, str] | tuple[None, None]:
        pool = self.cookie_pool
        if not pool:
            return None, None
        if len(pool) == 1:
            return current_index, pool[0]
        next_index = current_index
        for _ in range(len(pool)):
            next_index = (next_index + 1) % len(pool)
            if pool[next_index] != self.cookie:
                break
        self.cookie = pool[next_index]
        self._save_to_file()
        return next_index, pool[next_index]

    @property
    def base_url(self) -> str:
        return self.get("base_url", default=DEFAULTS["base_url"])

    @property
    def ajax_url(self) -> str:
        return self.get("ajax_url", default=DEFAULTS["ajax_url"])

    @property
    def headers(self) -> dict[str, str]:
        return self.get("headers", default=DEFAULTS["headers"])

    @property
    def max_workers(self) -> int:
        return int(self.get("download", "max_workers", default=DEFAULTS["download"]["max_workers"]))

    @property
    def timeout(self) -> int:
        return int(self.get("download", "timeout", default=DEFAULTS["download"]["timeout"]))

    @property
    def rate_limit_rps(self) -> float:
        return float(self.get("download", "rate_limit_rps", default=DEFAULTS["download"]["rate_limit_rps"]))

    @property
    def rate_limit_rps_authenticated(self) -> float:
        return float(self.get("download", "rate_limit_rps_authenticated", default=DEFAULTS["download"]["rate_limit_rps_authenticated"]))

    @property
    def image_rate_limit_rps(self) -> float:
        return float(self.get("download", "image_rate_limit_rps", default=DEFAULTS["download"]["image_rate_limit_rps"]))

    @property
    def image_rate_limit_rps_authenticated(self) -> float:
        return float(self.get("download", "image_rate_limit_rps_authenticated", default=DEFAULTS["download"]["image_rate_limit_rps_authenticated"]))

    @property
    def retry_429(self) -> bool:
        return bool(self.get("download", "retry_429", default=True))

    @property
    def retry_429_delay(self) -> int:
        return int(self.get("download", "retry_429_delay_seconds", default=30))

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "PixivConfig":
        if path is None:
            path = get_project_root() / "config.json"

        data = copy.deepcopy(DEFAULTS)

        if path.exists():
            try:
                file_data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                file_data = {}

            pixiv_raw = file_data.get("pixiv", {})
            if pixiv_raw:
                for key in pixiv_raw:
                    data[key] = pixiv_raw[key]

        if data.get("cookie") and not data.get("cookie_pool"):
            data["cookie_pool"] = [data["cookie"]]

        return cls(data)

    def to_session_headers(self) -> dict[str, str]:
        h = dict(self.headers)
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def _save_to_file(self):
        config_path = get_project_root() / "config.json"
        try:
            file_data = {}
            if config_path.exists():
                file_data = json.loads(config_path.read_text(encoding="utf-8"))
            pixiv_data = file_data.setdefault("pixiv", {})
            if "cookie" in self._data:
                pixiv_data["cookie"] = self._data["cookie"]
            if "cookie_pool" in self._data:
                pixiv_data["cookie_pool"] = self._data["cookie_pool"]
            config_path.write_text(json.dumps(file_data, ensure_ascii=False, indent=4), encoding="utf-8")
        except Exception as e:
            _logger.error("保存 Cookie 池配置失败: %s", e)
