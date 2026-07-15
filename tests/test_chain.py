#!/usr/bin/env python3
"""akm 核心命令测试链路 v3.0

用法:
  python3 tests/test_chain.py                          # 默认测试目录
  python3 tests/test_chain.py /path/to/test_files      # 自定义测试目录

验证链条（规范化命令）:
  delete all → import → open → list → search → stats → delete
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AKM = [sys.executable, str(PROJECT_ROOT / "run.py")]
TEST_DIR = Path(
    sys.argv[1] if len(sys.argv) > 1
    else os.environ.get("TEST_DIR", str(Path("/Users/passersbyc/Desktop/test")))
)
QUIET_MODE = "--quiet" in sys.argv

G, R, C, Y, D, B, N = "\033[92m", "\033[91m", "\033[96m", "\033[93m", "\033[2m", "\033[1m", "\033[0m"

passed = failed = 0
failures = []
phase = ""


def _run(*a, timeout=120):
    return subprocess.run(AKM + list(a), capture_output=True, text=True, timeout=timeout, cwd=PROJECT_ROOT)


def _json(*a, timeout=120):
    res = _run(*a, "--json", timeout=timeout)
    try:
        out = res.stdout.strip()
        if out:
            return json.loads(out)
        err = res.stderr.strip()
        if err and err.startswith("{"):
            return json.loads(err)
    except Exception:
        pass
    return None


def _unwrap(data):
    if not isinstance(data, dict):
        return {}
    result = dict(data)
    if "data" in result and isinstance(result["data"], dict):
        result.update(result["data"])
        del result["data"]
    return result


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        if not QUIET_MODE:
            print(f"  {G}[PASS]{N} {label}")
    else:
        failed += 1
        print(f"  {R}[FAIL]{N} {label}")
        if detail:
            print(f"        {D}{detail}{N}")
        failures.append((phase, label, detail))


def ph(name):
    global phase
    phase = name
    if not QUIET_MODE:
        print(f"\n{B}Phase {name}{N}")


def say(msg):
    if not QUIET_MODE:
        print(f"    {C}> {msg}{N}")


BASE36_RE = re.compile(r"^[0-9a-z]{10}$")
TYPE_CHARS = set("ncmfi0")


def check_id(id_, label=""):
    ctx = f" [{label}]" if label else ""
    assert len(id_) == 10, f"ID 长度应为10{ctx}, 实际 {len(id_)}: {id_}"
    assert id_[0] in TYPE_CHARS, f"无效类型字符{ctx}: {id_!r}"
    assert BASE36_RE.match(id_), f"非 base36 字符{ctx}: {id_!r}"
    return {"type": id_[0], "author": id_[1:4], "series": id_[4:6], "work": id_[6:]}


def _ids_from_import(data):
    ids = []
    for r in data.get("results", []):
        if r.get("success"):
            ids.append(r.get("book_id", ""))
    return ids


print(f"\n{B}{' akm 核心命令测试链路 v3.0 ':─^50}{N}\n")

if not TEST_DIR.is_dir():
    print(f"{R}测试目录不存在: {TEST_DIR}{N}")
    print(f"  用法: python3 tests/test_chain.py /path/to/test_files")
    sys.exit(1)

all_files = sorted([f for f in TEST_DIR.iterdir() if f.is_file() and not f.name.startswith(".")])
epubs = [f for f in all_files if f.suffix.lower() == ".epub"]
txts = [f for f in all_files if f.suffix.lower() == ".txt"]
say(f"测试目录: {TEST_DIR}")
say(f"测试文件: {len(all_files)} 个 ({len(epubs)} EPUB, {len(txts)} TXT)")

# ======================== Phase 0: 清空库 ========================
ph("0: 清空库 (delete all)")
res = _json("delete", "all", "--yes", "--no-confirm")
check(res and res.get("success"), "delete all 执行成功")

# ======================== Phase 1: 导入 ========================
ph("1: 导入 (import)")
import_rounds = []
if epubs:
    import_rounds.append(("R1 基础导入", epubs[:1], ["--author", "testchain", "--yes"]))
    r2 = epubs[1:3]
    if r2:
        import_rounds.append(("R2 含系列+标签+收藏", r2, [
            "--author", "testchain", "--series", "都市系列",
            "--tags", "测试,TSF", "--favorite", "--rating", "8.5",
            "--description", "测试简介", "--source", "https://example.com/test",
            "--yes",
        ]))
if txts:
    import_rounds.append(("R3 TXT 导入", txts[:2], ["--author", "testchain", "--yes"]))

all_imported_ids = []
for round_name, files, extra_args in import_rounds:
    say(round_name)
    res = _json("import", *[str(f) for f in files], *extra_args)
    data = _unwrap(res or {})
    check(res and res.get("success"), f"{round_name}: 执行成功")
    imported = data.get("imported", 0)
    check(imported == len(files), f"{round_name}: 全部导入 ({imported}/{len(files)})")
    rids = _ids_from_import(data)
    all_imported_ids.extend(rids)
    for i, id_ in enumerate(rids):
        try:
            parsed = check_id(id_)
            check(parsed["author"] == "001", f"{round_name} ID[{i}] author=001", f"实际: {parsed['author']}")
        except AssertionError as e:
            check(False, f"{round_name} ID[{i}]: 格式", str(e))

# ======================== Phase 1.5: MD5 重复拒绝 ========================
ph("1.5: MD5 重复拒绝")
if epubs:
    res = _json("import", str(epubs[0]), "--author", "testchain", "--yes")
    data = _unwrap(res or {})
    skipped = sum(1 for r in data.get("results", []) if r.get("duplicate_of"))
    check(skipped >= 1, "MD5 重复被跳过", f"skipped={skipped}")

# ======================== Phase 2: 打开 (open) ========================
ph("2: 打开 (open)")
if all_imported_ids:
    test_id = all_imported_ids[0]
    res = _json("open", test_id)
    data = _unwrap(res or {})
    check(res and res.get("success"), "open 执行成功")
    check(data.get("id") == test_id, "open 返回正确 ID", f"got {data.get('id')}")
    check(bool(data.get("file_path")), "open 包含文件路径")
    # 不存在的 ID
    res = _json("open", "nZZZ000000")
    check(res and not res.get("success"), "open 不存在 ID 返回失败")

# ======================== Phase 3: 列表 (list) ========================
ph("3: 列表 (list)")
res = _json("list")
data = _unwrap(res or {})
check(res and res.get("success"), "list 执行成功")
works = data.get("works", [])
check(len(works) == len(all_imported_ids), "list 返回数量等于导入数",
      f"list={len(works)} imported={len(all_imported_ids)}")

res = _json("list", "author")
data = _unwrap(res or {})
check(res and res.get("success"), "list author 执行成功")

# ======================== Phase 4: 搜索 (search) ========================
ph("4: 搜索 (search)")
res = _json("search", "novel", "--author", "testchain")
data = _unwrap(res or {})
check(res and res.get("success"), "search 执行成功")
check(data.get("total", 0) == len(all_imported_ids), "search 按作者返回全部",
      f"total={data.get('total')} expected={len(all_imported_ids)}")

res = _json("search", "author", "testchain")
data = _unwrap(res or {})
check(res and res.get("success"), "search author 执行成功")

# ======================== Phase 5: 统计 (stats) ========================
ph("5: 统计 (stats)")
res = _json("stats")
data = _unwrap(res or {})
check(res and res.get("success"), "stats 执行成功")
check(data.get("total_books", 0) == len(all_imported_ids), "stats total_books 等于导入数",
      f"got {data.get('total_books')} expected {len(all_imported_ids)}")
check(isinstance(data.get("id_type_distribution"), dict), "stats 包含 id_type_distribution")

# ======================== Phase 6: 删除 (delete) ========================
ph("6: 删除 (delete)")
if len(all_imported_ids) >= 2:
    res = _json("list")
    before_count = len(_unwrap(res or {}).get("works", []))
    del_count = 0

    for _ in range(2):
        res = _json("list")
        works = _unwrap(res or {}).get("works", [])
        if not works:
            break
        del_id = works[-1]["ID"]
        res = _json("delete", del_id, "--yes", "--no-confirm")
        check(res and res.get("success"), f"delete {del_id} 执行成功")
        del_count += 1

    res = _json("list")
    after_count = len(_unwrap(res or {}).get("works", []))
    check(after_count == before_count - del_count, f"删除后减少 {del_count} 项",
          f"before={before_count} after={after_count}")

# ======================== Phase 7: 清空 (delete all) ========================
ph("7: 清空 (delete all)")
res = _json("delete", "all", "--yes", "--no-confirm")
check(res and res.get("success"), "delete all 执行成功")
res = _json("list")
check(len(_unwrap(res or {}).get("works", [])) == 0, "清空后 list 为空")

# ======================== Summary ========================
print(f"\n{B}{' 测试总结 ':─^50}{N}")
print(f"  {G}通过: {passed}{N}  {R}失败: {failed}{N}")
if failures:
    print(f"\n{R}失败详情:{N}")
    for p, label, detail in failures:
        print(f"  [{p}] {label}" + (f" — {D}{detail}{N}" if detail else ""))
sys.exit(0 if failed == 0 else 1)
