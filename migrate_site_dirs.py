#!/usr/bin/env python
"""一次性迁移脚本：作品文件从 library/{分类}/{作者}/ 移到 library/{站点}/{分类}/{作者}/。

用法：
  python migrate_site_dirs.py            # 干跑，只打印映射，不实际移动
  python migrate_site_dirs.py --apply    # 实际移动文件 + 更新 works.file_path

幂等：相对路径首段已是站点名时自动跳过，可重复执行。
"""
import sys
import shutil
from pathlib import Path

from src.core.site import SITES
from src.core.database import get_site_db
from src.core.config import get_library_path


def main() -> None:
    apply = "--apply" in sys.argv
    lib = get_library_path()
    total_move = 0
    total_skip = 0

    for site in SITES:
        db = get_site_db(site)
        rows = db.execute(
            "SELECT id, file_path FROM works WHERE file_path != ''"
        ).fetchall()
        for row in rows:
            work_id = row["id"]
            fp = Path(row["file_path"])
            if not fp.exists():
                total_skip += 1
                continue
            try:
                rel = fp.relative_to(lib)
            except ValueError:
                # 不在书库根目录下，跳过
                total_skip += 1
                continue
            parts = rel.parts
            if not parts or parts[0] == site:
                # 已在正确站点目录，跳过（幂等）
                continue

            new_path = lib / site / rel
            if apply:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                if new_path.exists():
                    print(f"  [跳过-目标已存在] {rel}")
                    continue
                shutil.move(str(fp), str(new_path))
                db.execute(
                    "UPDATE works SET file_path = ? WHERE id = ?",
                    (str(new_path.absolute()), work_id),
                )
            else:
                print(f"  {site}: {rel}  ->  {site}/{rel}")
            total_move += 1
        if apply:
            db.commit()

    print()
    if apply:
        print(f"完成：移动 {total_move} 个文件，跳过 {total_skip} 个（不存在/在库外）")
    else:
        print(f"干跑：共 {total_move} 个文件待移动（加 --apply 实际执行）")


if __name__ == "__main__":
    main()
