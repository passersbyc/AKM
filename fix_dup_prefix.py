"""修复双重前缀文件名: 0001_0001_标题.ext -> 0001_标题.ext,并同步数据库 file_path。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.core.paths import work_file_prefix

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")
PAT = re.compile(r"^(\d+)_\1_", re.I)

def main():
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT id, file_path FROM works").fetchall()
    plan = []
    for wid, fp in rows:
        base = os.path.basename(fp)
        m = PAT.match(base)
        if not m:
            continue
        new_base = base[m.end():]
        new_fp = os.path.join(os.path.dirname(fp), new_base)
        plan.append((wid, fp, new_fp, m.group(1)))
    print(f"待修复: {len(plan)} 个")

    ok = 0
    conflict = []
    for wid, old_fp, new_fp, prefix in plan:
        expected = work_file_prefix(wid)
        if expected != prefix:
            conflict.append((wid, prefix, expected))
            continue
        if os.path.exists(new_fp):
            conflict.append((wid, old_fp, "目标已存在: " + new_fp))
            continue
        os.rename(old_fp, new_fp)
        db.execute("UPDATE works SET file_path=? WHERE id=?", (new_fp, wid))
        ok += 1
    db.commit()
    db.close()
    print(f"修复完成: {ok} 个")
    if conflict:
        print("跳过(不一致/冲突):", len(conflict))
        for c in conflict[:10]:
            print("  ", c)

if __name__ == "__main__":
    main()
