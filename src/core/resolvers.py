"""ID 解析器 — author name/ series name → ID。
提取自 work_repository 以打破与 series_manager 的循环依赖。"""
from src.core.database import get_db
from src.core.registry import _get_author_id, _get_series_id


def resolve_author_id(name: str) -> str:
    if not name or name == "佚名":
        db = get_db()
        row = db.execute("SELECT id FROM authors WHERE id = '000'").fetchone()
        if not row:
            db.execute("INSERT OR IGNORE INTO authors (id, name, source) VALUES ('000', '佚名', 'local')")
        return "000"
    from src.core.author_manager import get_by_name, register
    found = get_by_name(name)
    if found:
        return found["id"]
    result = register(name=name)
    return result["id"] if result else _get_author_id(name)


def resolve_series_id(author_id: str, name: str) -> str:
    if not name:
        return ""
    from src.core.series_manager import get_or_create
    sid, _ = get_or_create(name=name, author_id=author_id)
    return sid
