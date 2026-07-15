import re

from src.core.work_repository import read_all, write_all
from src.core.work_index import reindex_groups


def _extract_order(title: str) -> tuple:
    cn_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    patterns = [
        r'第\s*([一二三四五六七八九十百千]+)\s*[章回卷部集]',
        r'第\s*(\d+)\s*[章回卷部集]',
        r'[（(]\s*(\d+)\s*[）)]',
        r'[（(]\s*([一二三四五六七八九十百千]+)\s*[）)]',
        r'\s*[-—]\s*(\d+)\s+',
    ]
    for pat in patterns:
        m = re.search(pat, title)
        if m:
            val = m.group(1).strip()
            if val in cn_map:
                return (0, int(cn_map[val]))
            try:
                return (0, int(val))
            except ValueError:
                pass
    return (1, 0)


def reindex_for_source(source_filter: str = None) -> None:
    all_rows = read_all()
    if not all_rows:
        return

    if source_filter:
        target_rows = [r for r in all_rows if r.get("来源", "") == source_filter]
        if not target_rows:
            return
    else:
        target_rows = all_rows

    reindex_groups(target_rows, sort_key=lambda r: _extract_order(r.get("标题", "")))

    if source_filter:
        write_all(all_rows)
    else:
        write_all(target_rows)
