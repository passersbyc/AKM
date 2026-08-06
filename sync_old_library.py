"""从旧书库 cli-book-manager 同步作品到 AKM。

用法:
    python sync_old_library.py                     # 全量迁移
    python sync_old_library.py --limit-authors 10  # 只迁移前 N 个作者(按旧库作者ID排序)
    python sync_old_library.py --dry-run           # 只统计,不写库(生成缺失文件清单)

迁移内容:
    - works         作品(标题/作者/系列/标签/来源/收藏/评分/简介/点赞/日期)
    - pixiv_trackings  follow 表(按作者名映射到新库作者ID,保留 pixiv_uid/homepage/状态/最新作品/检查时间)
    - download_queue   待下载队列

说明:
    - 文件路径从旧前缀(历史失效路径)映射到本机实际路径后,复制到新库书库(copy 模式)
    - ID 由新库重新生成,不保留旧 ID
    - 中断后可直接重跑,MD5 去重自动跳过已导入作品
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.core.importer import import_one

OLD_DB = "/Users/Shared/test/cli-book-manager/data/library.db"
OLD_PREFIX = "/Users/passersbyc/代码/cli-book-manager"
NEW_PREFIX = "/Users/Shared/test/cli-book-manager"
NEW_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")
MISSING_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "missing_files.txt"
)

WORKS_SQL = """
    SELECT w.id, w.title, a.name AS author_name, s.name AS series_name,
           w.tags, w.source, w.file_ext, w.file_type, w.favorite, w.rating,
           w.description, w.likes, w.imported_at, w.published_at, w.file_path
    FROM works w
    LEFT JOIN authors a ON w.author_id = a.id
    LEFT JOIN series s ON w.series_id = s.id AND s.author_id = w.author_id
"""


def connect(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def load_authors(db: sqlite3.Connection, limit: int = 0) -> list:
    if limit > 0:
        return db.execute(
            "SELECT id, name FROM authors ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    return db.execute("SELECT id, name FROM authors ORDER BY id").fetchall()


def load_rows(db: sqlite3.Connection, author_ids: list[str]) -> list:
    if author_ids:
        placeholders = ",".join("?" * len(author_ids))
        return db.execute(
            f"{WORKS_SQL} WHERE w.author_id IN ({placeholders}) ORDER BY w.id",
            author_ids,
        ).fetchall()
    return db.execute(f"{WORKS_SQL} ORDER BY w.id").fetchall()


def map_path(fpath: str) -> str:
    return fpath.replace(OLD_PREFIX, NEW_PREFIX)


def make_clean_copy(src: Path, title: str, seq: str) -> tuple[str, Path]:
    """复制一份文件名干净的临时副本(标题+后缀),避免旧库序号前缀与新ID前缀叠加成双前缀。

    - 标题按 UTF-8 字节截断(≤180字节), 防 macOS 255 字节文件名上限
    - 清洗换行/制表符等不可见字符
    - 标题为空时用旧文件名去序号前缀的部分兜底
    返回 (临时目录, 临时文件); 调用方负责清理临时目录。
    """
    tmpdir = tempfile.mkdtemp(prefix="akm_sync_")
    ext = src.suffix or ""
    safe = re.sub(r'[\r\n\t]', ' ', title or "").strip()
    if not safe:
        safe = re.sub(r'^\s*[0-9a-z]{1,4}_\s*', '', src.stem).strip() or src.stem
    safe = re.sub(r'[\\/:*?"<>|]', ' ', safe).strip()
    safe = safe.lstrip('.')
    while len(safe.encode("utf-8", errors="ignore")) > 180:
        safe = safe[:-1]
    safe = safe.rstrip() or "untitled"
    tmp = Path(tmpdir) / f"{safe}{ext}"
    shutil.copy2(src, tmp)
    return tmpdir, tmp


def write_missing_report(rows: list) -> tuple[int, int]:
    missing = []
    for row in rows:
        new_path = map_path(row["file_path"])
        if not os.path.exists(new_path):
            missing.append((row["id"], row["title"] or "", new_path))
    with open(MISSING_FILE, "w", encoding="utf-8") as f:
        f.write(f"# 共 {len(rows)} 条记录, {len(missing)} 条文件缺失\n\n")
        for wid, title, path in missing:
            f.write(f"{wid}\t{title}\t{path}\n")
    return len(rows), len(missing)


def migrate_follows(old_db: sqlite3.Connection, new_db: sqlite3.Connection,
                    author_names: set[str]) -> tuple[int, int]:
    """按作者名把旧库 pixiv_trackings 迁移到新库。返回 (成功, 失败)。"""
    rows = old_db.execute("""
        SELECT t.pixiv_uid, t.homepage, t.follow_status, t.latest_work_id,
               t.last_checked, t.note, a.name
        FROM pixiv_trackings t
        LEFT JOIN authors a ON a.id = t.author_id
    """).fetchall()
    rows = [r for r in rows if r["name"] and r["name"] in author_names]

    name_to_id = {
        r["name"]: r["id"]
        for r in new_db.execute("SELECT id, name FROM authors").fetchall()
    }
    ok = miss = 0
    for row in rows:
        new_id = name_to_id.get(row["name"])
        if not new_id:
            miss += 1
            continue
        new_db.execute(
            "INSERT OR REPLACE INTO pixiv_trackings "
            "(author_id, pixiv_uid, homepage, follow_status, latest_work_id,"
            " last_checked, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id, row["pixiv_uid"], row["homepage"] or "",
             row["follow_status"] or "active", row["latest_work_id"] or "",
             row["last_checked"] or "", row["note"] or ""),
        )
        ok += 1
    new_db.commit()
    return ok, miss


def migrate_author_meta(old_db: sqlite3.Connection, new_db: sqlite3.Connection,
                        author_names: set[str]) -> tuple[int, int]:
    """把旧库 authors 的作者级元数据(别名/备注/收藏/来源)按名迁移到新库。返回 (成功, 失败)。"""
    if not author_names:
        return 0, 0
    rows = old_db.execute("""
        SELECT name, aliases, source, note, favorite FROM authors
        WHERE name IS NOT NULL AND name IN ({})
    """.format(",".join("?" * len(author_names))), sorted(author_names)).fetchall()
    name_to_id = {
        r["name"]: r["id"]
        for r in new_db.execute("SELECT id, name FROM authors").fetchall()
    }
    ok = miss = 0
    for row in rows:
        new_id = name_to_id.get(row["name"])
        if not new_id:
            miss += 1
            continue
        new_db.execute(
            "UPDATE authors SET aliases = ?, source = ?, note = ?, favorite = ? WHERE id = ?",
            (row["aliases"] or "", row["source"] or "local",
             row["note"] or "", int(row["favorite"] or 0), new_id),
        )
        ok += 1
    new_db.commit()
    return ok, miss


def migrate_queue(old_db: sqlite3.Connection, new_db: sqlite3.Connection) -> int:
    rows = old_db.execute(
        "SELECT url, author_id, status, added_at FROM download_queue"
    ).fetchall()
    for row in rows:
        new_db.execute(
            "INSERT OR IGNORE INTO download_queue (url, author_id, status, added_at)"
            " VALUES (?, ?, ?, ?)",
            (row["url"], row["author_id"] or "", row["status"] or "pending",
             row["added_at"] or ""),
        )
    new_db.commit()
    return len(rows)


def run_dry(old_db: sqlite3.Connection, rows: list, author_names: set[str]) -> None:
    total, missing = write_missing_report(rows)
    follows = old_db.execute("""
        SELECT count(*) FROM pixiv_trackings t
        LEFT JOIN authors a ON a.id = t.author_id
        WHERE a.name IS NOT NULL AND a.name IN ({})
    """.format(",".join("?" * len(author_names))), sorted(author_names)).fetchone()[0]
    author_meta = old_db.execute("""
        SELECT count(*) FROM authors
        WHERE name IS NOT NULL AND name IN ({})
          AND (aliases != '' OR note != '' OR favorite != 0)
    """.format(",".join("?" * len(author_names))), sorted(author_names)).fetchone()[0]
    queue = old_db.execute("SELECT count(*) FROM download_queue").fetchone()[0]
    print(f"作者: {len(author_names)} 个")
    print(f"作品: {total} 条 (缺失文件 {missing} 条, 清单见 {MISSING_FILE})")
    print(f"follow: {follows} 条, 作者元数据: {author_meta} 条, download_queue: {queue} 条")
    if missing:
        print("缺失文件示例:")
        for row in rows:
            new_path = map_path(row["file_path"])
            if not os.path.exists(new_path):
                print(f"  {row['id']} {row['title'][:30]} -> {new_path}")


def run_migrate(old_db: sqlite3.Connection, rows: list,
                author_names: set[str]) -> int:
    new_db = connect(NEW_DB)
    # 佚名作者固定 ID 000(registry 硬编码), 必须先建行, 否则系列表外键悬空
    new_db.execute(
        "INSERT OR IGNORE INTO authors (id, name, source) VALUES ('000', '佚名', 'local')"
    )
    new_db.commit()
    ok = skip = fail = 0
    fail_details = []
    t0 = time.time()
    for i, row in enumerate(rows):
        src = Path(map_path(row["file_path"]))
        if not src.exists():
            fail += 1
            fail_details.append((row["id"], row["title"], f"文件不存在: {src}"))
            continue
        seq = row["id"][-4:] if len(row["id"]) >= 4 else row["id"]
        title = row["title"] or ""
        tmpdir = tmp = None
        try:
            tmpdir, tmp = make_clean_copy(src, title, seq)
            result = import_one(
                file_path=str(tmp),
                author=row["author_name"] or "佚名",
                series=row["series_name"] or "",
                tags=row["tags"] or "",
                source=row["source"] or "local",
                favorited=bool(row["favorite"]),
                rating=float(row["rating"] or 0),
                description=row["description"] or "",
                like_count=int(row["likes"] or 0),
                # 新库无 published_at 字段, 用"导入时间"承载作品发布日期(优先), 无则退回旧库导入时间
                create_date=row["published_at"] or row["imported_at"] or "",
                title=title,
                target_format="epub",
            )
            if not result.success and result.error and "目标已存在" in result.error:
                alt = tmp.with_name(f"{tmp.stem}({seq}){tmp.suffix}")
                shutil.copy2(tmp, alt)
                result = import_one(
                    file_path=str(alt),
                    author=row["author_name"] or "佚名",
                    series=row["series_name"] or "",
                    tags=row["tags"] or "",
                    source=row["source"] or "local",
                    favorited=bool(row["favorite"]),
                    rating=float(row["rating"] or 0),
                    description=row["description"] or "",
                    like_count=int(row["likes"] or 0),
                    create_date=row["published_at"] or row["imported_at"] or "",
                    title=title,
                    target_format="epub",
                )
            if result.success:
                ok += 1
            elif result.duplicate_of:
                skip += 1
            else:
                fail += 1
                fail_details.append((row["id"], row["title"], result.error))
        except Exception as e:
            fail += 1
            fail_details.append((row["id"], row["title"], str(e)))
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"进度 {i+1}/{len(rows)} 成功:{ok} 跳过:{skip} 失败:{fail} 耗时:{elapsed:.0f}s")
    elapsed = time.time() - t0
    print(f"作品迁移完成 成功:{ok} 跳过:{skip} 失败:{fail} 耗时:{elapsed:.0f}s")

    f_ok, f_miss = migrate_follows(old_db, new_db, author_names)
    print(f"follow 迁移完成 成功:{f_ok} 失败:{f_miss}")

    m_ok, m_miss = migrate_author_meta(old_db, new_db, author_names)
    print(f"作者元数据迁移完成 成功:{m_ok} 失败:{m_miss}")

    q = migrate_queue(old_db, new_db)
    print(f"download_queue 迁移完成 共 {q} 条")

    if fail_details:
        print(f"\n失败详情(前20条, 共 {len(fail_details)} 条):")
        for wid, title, err in fail_details[:20]:
            print(f"  {wid} {title[:30]}: {err}")
    new_db.close()
    return fail


def main() -> int:
    parser = argparse.ArgumentParser(description="从旧书库 cli-book-manager 同步到 AKM")
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计并输出缺失文件清单, 不写库")
    parser.add_argument("--limit-authors", type=int, default=0,
                        help="只迁移前 N 个作者(按旧库作者ID排序)")
    args = parser.parse_args()

    old_db = connect(OLD_DB)
    authors = load_authors(old_db, args.limit_authors)
    author_names = {a["name"] for a in authors}
    author_ids = [a["id"] for a in authors]
    rows = load_rows(old_db, author_ids)

    print(f"旧库记录: {len(rows)} 条, 涉及作者 {len(author_names)} 个")

    if args.dry_run:
        run_dry(old_db, rows, author_names)
        old_db.close()
        return 0

    fail = run_migrate(old_db, rows, author_names)
    old_db.close()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
