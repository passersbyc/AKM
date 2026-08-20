#!/usr/bin/env python
"""一次性迁移脚本：为存量作者反推并写入主页（authors.homepage）。

从作者的作品 source URL 反推作者主页，写入 authors.homepage（已有主页则跳过）。

用法：
  python migrate_author_homepage.py            # 干跑，只打印
  python migrate_author_homepage.py --apply    # 实际写入
"""
import sys

from src.core.site import SITES
from src.core.database import get_site_db
from src.core.author_homepage import extract_author_homepage


def main() -> None:
    apply = "--apply" in sys.argv
    total = 0

    for site in SITES:
        db = get_site_db(site)
        authors = db.execute("SELECT id, name, homepage FROM authors").fetchall()
        for a in authors:
            if a["homepage"]:
                continue  # 已有主页，跳过
            row = db.execute(
                "SELECT source FROM works WHERE author_id = ? AND source != '' LIMIT 1",
                (a["id"],),
            ).fetchone()
            if not row:
                continue
            hp = extract_author_homepage(row["source"], a["name"])
            if not hp:
                continue
            if apply:
                db.execute(
                    "UPDATE authors SET homepage = ? WHERE id = ?",
                    (hp, a["id"]),
                )
            else:
                print(f"  {site}: {a['name']} -> {hp}")
            total += 1
        if apply:
            db.commit()

    print()
    if apply:
        print(f"完成：写入 {total} 个作者主页")
    else:
        print(f"干跑：共 {total} 个作者主页待写入（加 --apply 实际执行）")


if __name__ == "__main__":
    main()
