"""编辑操作 - 按资源类型分发。"""
from src.core.work_manager import WorkManager
from src.core.author_manager import (
    update as author_update,
    rename as author_rename,
    resolve as author_resolve,
    set_author_favorite,
)


def edit_book(book_id: str, field_updates: dict,
              new_author: str = "", new_series: str = "") -> dict | None:
    return WorkManager.update_entry_full(
        book_id, field_updates,
        new_author=new_author, new_series=new_series,
    )


def get_book(book_id: str) -> dict | None:
    return WorkManager.get_by_id(book_id)


def edit_author(target: str, name: str | None = None,
                note: str | None = None,
                favorite: str | None = None) -> dict | None:
    author = author_resolve(target)
    if not author:
        return None

    uid = author.get("pixiv_uid", "")
    if name and name.strip() != author.get("name", ""):
        name = name.strip()
        from src.core.author_manager import get_by_name
        conflict = get_by_name(name)
        if conflict and conflict.get("pixiv_uid") != uid:
            return {"error": "名称冲突"}
        author_rename(author["id"], name)

    if note is not None:
        author_update(uid, note=note.strip())

    if favorite is not None:
        fav = favorite == "yes"
        set_author_favorite(author["id"], fav)
        if fav:
            from src.core.config import get_project_root
            nf = get_project_root() / ".new_favorites"
            existing = nf.read_text(encoding="utf-8").strip() if nf.exists() else ""
            existing_ids = [x.strip() for x in existing.split(",") if x.strip()] if existing else []
            if author["id"] not in existing_ids:
                existing_ids.append(author["id"])
                nf.write_text(",".join(existing_ids), encoding="utf-8")

    return {"ok": True}


def edit_series(target: str, name: str | None = None,
                author: str | None = None) -> dict | None:
    from src.core.series_manager import rename as series_rename
    if not name or not author:
        return {"error": "需要 --name 和 --author"}
    count = series_rename(target, author, name.strip())
    if count:
        return {"ok": True}
    return {"error": "未找到系列"}


def edit(target: str, target_type: str = "book",
         **fields) -> dict | None:
    if target_type in ("book", "b"):
        new_author = fields.pop("author", "")
        new_series = fields.pop("series", "")
        return edit_book(target, fields, new_author=new_author,
                         new_series=new_series)
    if target_type in ("author", "a"):
        name = fields.pop("name", None)
        note = fields.pop("note", None)
        favorite = fields.pop("favorite", None)
        return edit_author(target, name=name, note=note, favorite=favorite)
    if target_type in ("series", "s"):
        name = fields.pop("name", None)
        author = fields.pop("author", None)
        return edit_series(target, name=name, author=author)
    return None