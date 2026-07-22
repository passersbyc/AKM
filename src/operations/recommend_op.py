"""推荐算法 — TF-IDF + 余弦相似度 + MMR 多样性选择，输出纯数据。"""
from __future__ import annotations

import math
from collections import Counter

from src.core.database import get_db, short_id


def get_recommendations(limit: int = 8) -> list[dict]:
    """返回推荐作品列表（纯数据，不含渲染逻辑）。

    算法：
    1. 收集最近活动（打开×3 / 下载×2 / 导入×1）构建兴趣画像
    2. 全库 TF-IDF 标签加权 + 作者/系列/分类特征向量
    3. 余弦相似度评分 + 评分/收藏加成
    4. MMR 多样性选择（避免全是同一作者/系列）
    5. 冷启动 fallback（无兴趣画像时按收藏/评分排序）

    Returns:
        list[dict]，每项：
        {"kind": "work"|"series", "work_id": str, "title": str,
         "reasons": [str], "series_count": int|None,
         "author_id": str, "series_id": str, "score": float}
    """
    db = get_db()

    recent_open = db.execute(
        "SELECT work_id, title, opened_at FROM recent_opens "
        "ORDER BY opened_at DESC LIMIT 5"
    ).fetchall()
    recent_import = db.execute(
        "SELECT id, title, imported_at FROM works "
        "WHERE imported_at != '' AND (source = '' OR source = 'local' OR source = 'demo' OR source NOT LIKE 'http%') "
        "ORDER BY imported_at DESC LIMIT 5"
    ).fetchall()
    recent_download = db.execute(
        "SELECT id, title, imported_at, source FROM works "
        "WHERE imported_at != '' AND source LIKE 'http%' "
        "ORDER BY imported_at DESC LIMIT 5"
    ).fetchall()

    if not recent_open and not recent_import and not recent_download:
        return []

    # ── 收集三栏已展示的 work_id 和 series_id ──
    shown_ids: set[str] = set()
    shown_series_ids: set[str] = set()
    for row in recent_open:
        if row and row["work_id"]:
            shown_ids.add(row["work_id"])
    for row in recent_import + recent_download:
        if row and row["id"]:
            shown_ids.add(row["id"])
    for wid in shown_ids:
        srow = db.execute("SELECT series_id FROM works WHERE id = ?", (wid,)).fetchone()
        if srow and srow["series_id"]:
            shown_series_ids.add(srow["series_id"])

    # ── 计算全库 TF-IDF ──
    all_works = db.execute(
        "SELECT id, title, tags, author_id, series_id, file_type, favorite, rating "
        "FROM works ORDER BY imported_at DESC"
    ).fetchall()
    total_works = len(all_works)

    tag_doc_freq: Counter = Counter()
    for w in all_works:
        for t in (w["tags"] or "").split(","):
            t = t.strip()
            if t:
                tag_doc_freq[t] += 1

    def _idf(tag: str) -> float:
        df = tag_doc_freq.get(tag, 0)
        if df == 0:
            return 0.0
        return math.log((total_works + 1) / (df + 1)) + 1.0

    # ── 构建兴趣画像（TF-IDF 加权 + 时间衰减） ──
    interest_tags: dict[str, float] = {}
    interest_authors: Counter = Counter()
    interest_series: Counter = Counter()
    interest_types: Counter = Counter()

    def _feed(row, weight):
        if not row:
            return
        wid = row["work_id"] if "work_id" in row.keys() else row["id"]
        if not wid:
            return
        w = db.execute(
            "SELECT tags, author_id, series_id, file_type FROM works WHERE id = ?",
            (wid,),
        ).fetchone()
        if not w:
            return
        for t in (w["tags"] or "").split(","):
            t = t.strip()
            if t:
                idf = _idf(t)
                interest_tags[t] = interest_tags.get(t, 0.0) + weight * idf
        if w["author_id"]:
            interest_authors[w["author_id"]] += weight
        if w["series_id"]:
            interest_series[w["series_id"]] += weight
        if w["file_type"]:
            interest_types[w["file_type"]] += weight

    for row in recent_open:
        _feed(row, 3)
    for row in recent_download:
        _feed(row, 2)
    for row in recent_import:
        _feed(row, 1)

    has_interest = any(interest_tags) or any(interest_authors) or any(interest_series) or any(interest_types)

    # ── 兴趣向量归一化 ──
    vec_norm = math.sqrt(
        sum(v * v for v in interest_tags.values())
        + sum(v * v for v in interest_authors.values())
        + sum(v * v for v in interest_series.values())
        + sum(v * v for v in interest_types.values())
    ) or 1.0

    def _build_item_vector(w) -> dict[str, float]:
        vec: dict[str, float] = {}
        for t in (w["tags"] or "").split(","):
            t = t.strip()
            if t:
                vec[f"tag:{t}"] = _idf(t)
        if w["author_id"]:
            vec[f"author:{w['author_id']}"] = 1.0
        if w["series_id"]:
            vec[f"series:{w['series_id']}"] = 1.0
        if w["file_type"]:
            vec[f"type:{w['file_type']}"] = 1.0
        return vec

    interest_vec: dict[str, float] = {}
    for tag, val in interest_tags.items():
        interest_vec[f"tag:{tag}"] = val
    for aid, val in interest_authors.items():
        interest_vec[f"author:{aid}"] = float(val)
    for sid, val in interest_series.items():
        interest_vec[f"series:{sid}"] = float(val)
    for ft, val in interest_types.items():
        interest_vec[f"type:{ft}"] = val

    def _cosine_similarity(item_vec: dict[str, float]) -> float:
        if not interest_vec or not item_vec:
            return 0.0
        dot = sum(v * interest_vec.get(k, 0.0) for k, v in item_vec.items())
        item_norm = math.sqrt(sum(v * v for v in item_vec.values())) or 1.0
        if item_norm == 0 or vec_norm == 0:
            return 0.0
        return dot / (item_norm * vec_norm)

    def _score_work(w) -> tuple[float, list[str]]:
        item_vec = _build_item_vector(w)
        cos_sim = _cosine_similarity(item_vec)
        reasons: list[str] = []

        matched = []
        for t in (w["tags"] or "").split(","):
            t = t.strip()
            if t and t in interest_tags:
                matched.append((t, interest_tags[t], "tag"))
        if w["author_id"] and w["author_id"] in interest_authors:
            matched.append(("同作者", float(interest_authors[w["author_id"]]), "author"))
        if w["series_id"] and w["series_id"] in interest_series:
            matched.append(("同系列", float(interest_series[w["series_id"]]), "series"))
        matched.sort(key=lambda x: x[1], reverse=True)
        for label, _, kind in matched[:2]:
            if kind == "tag":
                reasons.append(f"同标签:{label}")
            else:
                reasons.append(label)

        score = cos_sim * 100.0
        if w["favorite"]:
            score += 3.0
            if not reasons:
                reasons.append("收藏")
        score += (w["rating"] or 0) * 0.3
        score += 1.0
        return score, reasons

    # ── 分组：独立作品 vs 系列组 ──
    standalone_candidates = []
    series_groups: dict[tuple[str, str], list] = {}

    for w in all_works:
        if w["id"] in shown_ids:
            continue
        if w["series_id"]:
            key = (w["author_id"], w["series_id"])
            series_groups.setdefault(key, []).append(w)
        else:
            standalone_candidates.append(w)

    all_candidates: list[tuple[float, str, object, list[str], str, str]] = []

    for w in standalone_candidates:
        score, reasons = _score_work(w)
        all_candidates.append((score, "work", w, reasons, w["author_id"] or "", w["series_id"] or ""))

    for (author_id, series_id), members in series_groups.items():
        member_scores = []
        all_reasons: list[str] = []
        for m in members:
            s, r = _score_work(m)
            member_scores.append(s)
            all_reasons.extend(r)
        avg_score = sum(member_scores) / len(member_scores) if member_scores else 0
        if series_id in shown_series_ids:
            avg_score *= 0.5
        unique_reasons = []
        seen = set()
        for r in all_reasons:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)
        srow = db.execute(
            "SELECT name FROM series WHERE id = ? AND author_id = ?",
            (series_id, author_id),
        ).fetchone()
        series_name = srow["name"] if srow else f"系列{series_id}"
        first_work = min(members, key=lambda m: m["id"])
        all_candidates.append((avg_score, "series", (series_name, len(members), first_work["id"]),
                               unique_reasons[:2], author_id, series_id))

    if not all_candidates:
        return []

    # ── 冷启动 fallback ──
    if not has_interest:
        def _cold_key(c):
            if c[1] == "series":
                name, count = c[2][:2]
                return (count, c[0])
            w = c[2]
            return (w["favorite"] or 0, c[0])
        all_candidates.sort(key=_cold_key, reverse=True)
        picked = all_candidates[:limit]
    else:
        # ── MMR 多样性选择 ──
        all_candidates.sort(key=lambda c: c[0], reverse=True)
        picked: list[tuple[float, str, object, list[str], str, str]] = []
        remaining = list(all_candidates)
        lambda_div = 0.4

        while remaining and len(picked) < limit:
            best_idx = 0
            best_mmr = -1.0
            for i, cand in enumerate(remaining):
                rel = cand[0]
                max_sim = 0.0
                for p in picked:
                    sim = 0.0
                    if cand[4] and cand[4] == p[4]:
                        sim += 0.5
                    if cand[5] and cand[5] == p[5]:
                        sim += 0.5
                    max_sim = max(max_sim, sim)
                mmr = (1 - lambda_div) * rel - lambda_div * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i
            picked.append(remaining.pop(best_idx))

    # ── 输出纯数据 ──
    results: list[dict] = []
    for score, kind, payload, reasons, author_id, series_id in picked:
        if kind == "work":
            w = payload
            results.append({
                "kind": "work",
                "work_id": w["id"],
                "short_id": short_id(w["id"]),
                "title": (w["title"] or ""),
                "reasons": reasons,
                "series_count": None,
                "author_id": author_id,
                "series_id": series_id,
                "score": round(score, 2),
            })
        else:
            name, count, first_id = payload
            results.append({
                "kind": "series",
                "work_id": first_id,
                "short_id": short_id(first_id),
                "title": name,
                "reasons": reasons,
                "series_count": count,
                "author_id": author_id,
                "series_id": series_id,
                "score": round(score, 2),
            })
    return results
