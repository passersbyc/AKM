"""作者主页提取 — 从作品/作者 URL 反推作者主页。

纯字符串解析，零网络请求（避免每下载一部作品都发请求）。
每个站点一个提取函数，按 infer_site(url) 分派。
"""
import re
from urllib.parse import urlparse, unquote

from src.core.site import infer_site


def _pixiv_homepage(url: str, author_name: str = "") -> str:
    """pixiv 作品 URL（/novel/show.php）不含 uid，无法反推 → 返回空（依赖 follow 已存的主页）。"""
    m = re.search(r"/users/(\d+)", url)
    return f"https://www.pixiv.net/users/{m.group(1)}" if m else ""


def _pawchive_homepage(url: str, author_name: str = "") -> str:
    """/fanbox|patreon/user/{uid}/... → {host}/{service}/user/{uid}。"""
    m = re.search(r"/(?:fanbox|patreon)/user/(\d+)", url)
    if not m:
        return ""
    p = urlparse(url)
    host = f"{p.scheme}://{p.netloc}"
    service = "patreon" if "/patreon/" in url else "fanbox"
    return f"{host}/{service}/user/{m.group(1)}"


def _asmrmoon_homepage(url: str, author_name: str = "") -> str:
    """{host}/分类/作者名/[文件] → {host}/分类/作者名（取前两段）。"""
    p = urlparse(url)
    path = unquote(p.path or "")
    parts = [x for x in path.split("/") if x]
    if len(parts) >= 2:
        return f"{p.scheme}://{p.netloc}/{parts[0]}/{parts[1]}"
    return ""


def _biquge_homepage(url: str, author_name: str = "") -> str:
    """笔趣阁作者主页格式待确认，暂返回空（站点库当前无数据）。"""
    return ""


_DISPATCH = {
    "pixiv": _pixiv_homepage,
    "pawchive": _pawchive_homepage,
    "asmrmoon": _asmrmoon_homepage,
    "biquge": _biquge_homepage,
}


def extract_author_homepage(url: str, author_name: str = "") -> str:
    """从作品/作者 URL 反推作者主页；无法推导返回空串。"""
    if not url:
        return ""
    fn = _DISPATCH.get(infer_site(url))
    return fn(url, author_name) if fn else ""
