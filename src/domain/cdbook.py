import re
from collections import defaultdict
from pathlib import Path


_FULLWIDTH_MAP = str.maketrans({
    ',': '，', '!': '！', '?': '？', ':': '：', ';': '；',
    '(': '（', ')': '）',
    '<': '＜', '>': '＞', '"': '＂',
    '/': '／', '\\': '＼', '|': '｜', '*': '＊',
})


def normalize_series_name(series: str) -> str:
    if not series:
        return ""
    result = series.translate(_FULLWIDTH_MAP)
    result = re.sub(r'\s+', '', result)
    return result


def parse_cdbook_filename(filename: str, fallback_tag: str = "") -> dict:
    name = filename.strip()
    if name.startswith("."):
        name = name[1:]
    if name.endswith("["):
        name = name[:-1]

    suffix = Path(name).suffix.lower()
    name = Path(name).stem

    result = {
        "tag": "",
        "extra_tags": [],
        "title": name,
        "author": "",
        "series": "",
        "chapter": "",
        "order": "",
        "status": "",
    }

    while True:
        tag_match = re.match(r'^\[([^\]]+)\]\s*', name)
        if not tag_match:
            break
        tag_val = tag_match.group(1).strip()
        name = name[tag_match.end():].strip()
        if not result["tag"]:
            result["tag"] = tag_val
        else:
            result["extra_tags"].append(tag_val)

    extra_matches = re.findall(r'【([^】]+)】', name)
    if extra_matches:
        result["extra_tags"].extend([t.strip() for t in extra_matches])
        for em in re.findall(r'【[^】]+】', name):
            name = name.replace(em, "").strip()

    chapter_patterns = [
        (r'[（(]\s*(\d+[-~]\d+)\s*章[）)]', "range"),
        (r'[（(]\s*(\d+[-~]\d+)\s*[）)]', "range"),
        (r'(\d+[-~]\d+)\s*章', "range"),
        (r'第?\s*(\d+[-~]\d+)\s*[章回卷部集]', "range"),
        (r'[（(]\s*([一二三四五六七八九十百千]+)\s*[）)]', "cn"),
        (r'第\s*([一二三四五六七八九十百千]+)\s*[章回卷部集]', "cn"),
        (r'[（(]\s*第?\s*(\d+)\s*[）)]', "num"),
        (r'第\s*(\d+)\s*[章回卷部集]', "num"),
        (r'\s*[-—]\s*(\d+)\s+', "dash_num"),
        (r'_?(\d+)$', "num"),
        (r'^(\d+)[\.\s、．]', "num"),
    ]

    cn_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}

    for pat, ptype in chapter_patterns:
        cm = re.search(pat, name)
        if cm:
            val = cm.group(1).strip()
            if ptype == "cn":
                order_val = cn_map.get(val, val)
                result["order"] = order_val
                result["chapter"] = val
            elif ptype == "range":
                result["chapter"] = val
                start = re.split(r'[-~]', val)[0].strip()
                result["order"] = start
            elif ptype == "dash_num":
                result["order"] = val
                result["chapter"] = val
            elif ptype == "num":
                result["order"] = val
                result["chapter"] = val
            name = name[:cm.start()].strip() + " " + name[cm.end():].strip()
            break

    status_match = re.search(r'[（(]\s*(完|完结|END|结束)\s*[）)]', name)
    if status_match:
        result["status"] = status_match.group(1)
        name = name[:status_match.start()].strip() + " " + name[status_match.end():].strip()

    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[\.\s]*$', '', name)
    name = re.sub(r'^[\.\s]*', '', name)

    if not result["tag"]:
        result["tag"] = fallback_tag

    name = name.rstrip("-—,.，。")
    name = name.strip()
    if not name:
        name = filename.rsplit(".", 1)[0] if "." in filename else filename

    result["title"] = name
    result["extra_tags"] = ",".join(result["extra_tags"])

    return result


def detect_cdbook_series(file_metas: list[dict]) -> dict:
    def normalize_title(title: str) -> str:
        t = title
        t = re.sub(r'\s*第?\s*\d+\s*[章回卷部集]\s*', ' ', t)
        t = re.sub(r'\s*[第]?\s*[一二三四五六七八九十百千]+\s*[章回卷部集]\s*', ' ', t)
        t = re.sub(r'\s*[（(]\s*\d+\s*[）)]\s*', ' ', t)
        t = re.sub(r'\s*[（(]\s*[一二三四五六七八九十百千]+\s*[）)]\s*', ' ', t)
        t = re.sub(r'\s*[（(][^)]*(?:完|完结|END|结束)[^)]*[）)]\s*', ' ', t)
        t = re.sub(r'\s*[-—]\s*\d+\s*', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t.lower()

    def clean_prefix(prefix: str) -> str:
        prefix = prefix.rstrip()
        if prefix and prefix[-1].isalpha():
            prefix = re.sub(r'[a-zA-Z]*$', '', prefix).rstrip()
        prefix = re.sub(r'\s*\[[^\]]*\]\s*$', '', prefix).rstrip()
        return prefix

    prefix_indices = defaultdict(set)
    n = len(file_metas)
    for i in range(n):
        for j in range(i + 1, n):
            t1 = normalize_title(file_metas[i]["title"])
            t2 = normalize_title(file_metas[j]["title"])
            prefix = ""
            for a, b in zip(t1, t2):
                if a == b:
                    prefix += a
                else:
                    break
            prefix = clean_prefix(prefix)
            if len(prefix) >= 2 and not prefix.startswith('['):
                prefix_indices[prefix].add(i)
                prefix_indices[prefix].add(j)

    sorted_prefixes = sorted(prefix_indices.items(), key=lambda x: (-len(x[1]), -len(x[0])))

    assigned = set()
    for prefix, indices in sorted_prefixes:
        unassigned = indices - assigned
        if len(unassigned) >= 2:
            series_name = prefix.title()
            for idx in unassigned:
                file_metas[idx]["series"] = series_name
                meta = file_metas[idx]
                if meta["title"].lower() == prefix or meta["title"].lower() == series_name.lower():
                    if meta.get("chapter"):
                        meta["title"] = f'{meta["title"]}（{meta["chapter"]}）'
            assigned |= unassigned

    for i, meta in enumerate(file_metas):
        if i not in assigned:
            meta["series"] = ""
            meta["order"] = ""

    return {}
