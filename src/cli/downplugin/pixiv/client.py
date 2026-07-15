import time
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import PixivConfig
from src.core.logging import get_logger

logger = get_logger("akm.pixiv_client")

OAUTH_URL = "https://oauth.secure.pixiv.net/auth/token"
OAUTH_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
OAUTH_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
OAUTH_HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"


class PixivClient:
    def __init__(self, config: "PixivConfig"):
        self._config = config
        self._session = requests.Session()
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._api_rate_lock = threading.Lock()
        self._api_rate_next_ts = 0.0
        self._image_rate_lock = threading.Lock()
        self._image_rate_next_ts = 0.0
        self._429_pause = threading.Event()
        self._429_count = 0
        self._cookie_index = 0
        self._cookie_lock = threading.Lock()

        retry_strategy = Retry(
            total=0,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=50,
            pool_maxsize=50,
        )
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update(config.to_session_headers())

        token_str = config.refresh_token
        if token_str:
            self._refresh_token = token_str

    @property
    def access_token(self) -> Optional[str]:
        return self._access_token

    def authenticate(self) -> bool:
        if not self._refresh_token:
            logger.info("未配置 refresh_token，只能获取公开作品。关注/收藏等鉴权功能不可用。")
            return False

        with self._token_lock:
            if self._access_token:
                return True

            import hashlib as _hashlib

            local_time = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime())
            hash_input = (local_time + OAUTH_HASH_SECRET).encode()
            client_hash = _hashlib.md5(hash_input).hexdigest()

            headers = {
                "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Client-Time": local_time,
                "X-Client-Hash": client_hash,
            }
            data = {
                "client_id": OAUTH_CLIENT_ID,
                "client_secret": OAUTH_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "include_policy": "true",
            }

            for attempt in range(3):
                try:
                    r = requests.post(OAUTH_URL, headers=headers, data=data, timeout=30)
                    if r.status_code == 429:
                        time.sleep(30)
                        continue
                    if not r.ok:
                        logger.error("OAuth 登录失败: HTTP %d - %s", r.status_code, r.text[:200])
                        return False
                    result = r.json()
                    self._access_token = result.get("access_token")
                    if not self._access_token:
                        logger.error("OAuth 响应中无 access_token")
                        return False
                    new_refresh = result.get("refresh_token")
                    if new_refresh and new_refresh != self._refresh_token:
                        self._refresh_token = new_refresh
                    logger.debug("Pixiv OAuth 登录成功")
                    return True
                except Exception as e:
                    logger.error("OAuth 登录异常 (尝试 %d/3): %s", attempt + 1, e)
                    if attempt < 2:
                        time.sleep(2 * (attempt + 1))
            return False

    def get_json(self, url: str, params: Optional[dict] = None,
                  timeout: Optional[int] = None, max_retries: int = 8) -> Optional[dict]:
        last_status = 0
        for attempt in range(max_retries):
            if self._stop_event.is_set():
                return None
            try:
                self._wait_429()
                effective_timeout = timeout or self._config.timeout
                self._api_rate_limit()

                headers = self._build_request_headers()
                r = self._session.get(url, params=params, headers=headers, timeout=effective_timeout)
                last_status = r.status_code

                if self._handle_429(r):
                    continue
                if r.status_code in (401, 403):
                    self._access_token = None
                    if self.authenticate():
                        continue
                    raise Exception(f"HTTP {r.status_code} at {url}")
                if r.status_code == 404:
                    logger.warning("404 Not Found: %s", url)
                    return None

                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException as e:
                if self._stop_event.is_set():
                    return None
                if attempt < max_retries - 1:
                    self._stop_event.wait(2 * (attempt + 1))
                    continue
                logger.warning("API 请求最终失败 (%d/%d): %s 状态码=%d 异常=%s",
                                attempt + 1, max_retries, url, last_status, e)
                return None

    def _download_get(self, url: str, timeout: int = 30,
                      image_limit: bool = False) -> Optional["requests.Response"]:
        for attempt in range(3):
            if self._stop_event.is_set():
                return None
            try:
                if image_limit:
                    self._image_rate_limit()
                else:
                    self._api_rate_limit()

                headers = self._build_request_headers()
                headers["Referer"] = "https://www.pixiv.net/"
                r = self._session.get(url, headers=headers, timeout=timeout)

                if self._handle_429(r):
                    continue
                if not r.ok or not r.content:
                    if attempt < 2:
                        self._stop_event.wait(2)
                        continue
                    return None
                return r
            except Exception:
                if attempt < 2:
                    self._stop_event.wait(2)
                    continue
                return None
        return None

    def download_binary(self, url: str, timeout: int = 30,
                        image_limit: bool = False) -> tuple[Optional[bytes], str, str]:
        import mimetypes
        r = self._download_get(url, timeout, image_limit)
        if r is None:
            return None, "", ""

        content_type = r.headers.get("Content-Type", "")
        mime = content_type.split(";")[0].strip() if content_type else None
        ext = mimetypes.guess_extension(mime) if mime else None
        if not ext and url:
            ext = Path(urlparse(url).path).suffix
        if not ext:
            ext = ".jpg"
        if not mime:
            mime = mimetypes.types_map.get(ext.lower(), "image/jpeg")

        return r.content, ext, mime

    def download_to_file(self, url: str, save_path: Path,
                         timeout: int = 30, image_limit: bool = True) -> bool:
        r = self._download_get(url, timeout, image_limit)
        if r is None:
            if save_path.exists():
                try:
                    save_path.unlink()
                except OSError:
                    pass
            return False

        try:
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception:
            if save_path.exists():
                try:
                    save_path.unlink()
                except OSError:
                    pass
            return False

    def get_text(self, url: str, timeout: int = 15) -> Optional[str]:
        try:
            self._api_rate_limit()
            headers = self._build_request_headers()
            r = self._session.get(url, headers=headers, timeout=timeout)
            if self._handle_429(r):
                r = self._session.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.debug("get_text 失败: %s - %s", url, e)
            return None

    def stop(self):
        self._stop_event.set()

    def clear_stop(self):
        self._stop_event.clear()

    @property
    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def _build_request_headers(self) -> dict:
        h = dict(self._config.to_session_headers())
        if self._access_token:
            h["Authorization"] = f"Bearer {self._access_token}"
        return h

    def _is_authenticated(self) -> bool:
        return bool(self._access_token or self._config.cookie)

    def _api_rate_limit(self):
        if self._is_authenticated():
            rps = self._config.rate_limit_rps_authenticated
        else:
            rps = self._config.rate_limit_rps
        if rps <= 0:
            return
        interval = 1.0 / rps
        wait = 0.0
        now = time.monotonic()
        with self._api_rate_lock:
            if self._api_rate_next_ts <= now:
                self._api_rate_next_ts = now + interval
            else:
                wait = self._api_rate_next_ts - now
                self._api_rate_next_ts += interval
        if wait > 0:
            time.sleep(wait)

    def _image_rate_limit(self):
        if self._is_authenticated():
            rps = self._config.image_rate_limit_rps_authenticated
        else:
            rps = self._config.image_rate_limit_rps
        if rps <= 0:
            return
        interval = 1.0 / rps
        wait = 0.0
        now = time.monotonic()
        with self._image_rate_lock:
            if self._image_rate_next_ts <= now:
                self._image_rate_next_ts = now + interval
            else:
                wait = self._image_rate_next_ts - now
                self._image_rate_next_ts += interval
        if wait > 0:
            time.sleep(wait)

    def _switch_cookie(self) -> bool:
        with self._cookie_lock:
            result = self._config.rotate_cookie(self._cookie_index)
            if result[0] is not None:
                self._cookie_index = result[0]
                self._session.headers["Cookie"] = result[1]
                return True
        return False

    def _handle_429(self, response) -> bool:
        if not self._config.retry_429:
            return False
        if response.status_code == 429:
            if self._switch_cookie():
                self._429_count += 1
                if self._429_count == 1:
                    logger.warning("HTTP 429 限流，已切换 Cookie，不等待")
                else:
                    logger.debug("HTTP 429，再次切换 Cookie")
                return True
            retry_after = response.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else float(self._config.retry_429_delay)
            was_set = self._429_pause.is_set()
            if was_set:
                self._429_pause.wait()
                return True
            self._429_pause.set()
            logger.warning("HTTP 429 限流，Cookie 池已耗尽，全局暂停 %.0fs", wait)
            time.sleep(wait)
            self._429_pause.clear()
            self._429_count = 0
            return True
        return False

    def _wait_429(self):
        if self._429_pause.is_set():
            self._429_pause.wait()
