"""ID 解析器 — author name/ series name → ID。
提取自 work_repository 以打破与 series_manager 的循环依赖。"""
from src.core.database import get_db
from src.core.registry import _get_author_id, _get_series_id


def resolve_author_id(name: str, uid: str = "") -> str:
    if not name or name == "佚名":
        db = get_db()
        row = db.execute("SELECT id FROM authors WHERE id = '000'").fetchone()
        if not row:
            db.execute("INSERT OR IGNORE INTO authors (id, name, source) VALUES ('000', '佚名', 'local')")
        return "000"
    from src.core.author_manager import get_by_pixiv_uid, get_by_name, register
    # 优先按 pixiv_uid 关联作者（作者改名后仍能挂到同一编号）
    if uid and uid != "local":
        found = get_by_pixiv_uid(uid)
        if found:
            return found["id"]
    found = get_by_name(name)
    if found:
        # 名字兜底：命中行无 pixiv 身份（本地作者）才复用；
        # 命中行已有其他 pixiv_uid → 重名作者，不能错误合并
        if not uid or not found.get("pixiv_uid"):
            return found["id"]
    result = register(name=name, uid=uid)
    return result["id"] if result else _get_author_id(name)


def resolve_series_id(author_id: str, name: str) -> str:
    if not name:
        return ""
    from src.core.series_manager import get_or_create
    sid, _ = get_or_create(name=name, author_id=author_id)
    return sid
