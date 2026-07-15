from .models import ExportRequest, ExportPlan, TypeGroup


def collect_rows(rows: list[dict], request: ExportRequest) -> ExportPlan:
    if request.mode in ("work", "mylikeworks"):
        standalone, series_groups = _classify_works(rows)
        return ExportPlan(
            standalone=standalone,
            series_groups=series_groups,
            type_groups={},
            is_tag_mode=False,
        )

    if request.mode == "mylikeauthor":
        filtered = _filter_by_author_ids(rows, request)
    else:
        filtered = _filter_rows(rows, request)

    standalone, series_groups = _classify_works(filtered)

    if request.limit > 0:
        standalone, series_groups = _apply_like_cutoff(standalone, series_groups, request.limit)

    type_groups = _build_type_groups(standalone, series_groups)

    return ExportPlan(
        standalone=standalone,
        series_groups=series_groups,
        type_groups=type_groups,
        is_tag_mode=(request.mode == "tag"),
    )


def _filter_rows(rows: list[dict], request: ExportRequest) -> list[dict]:
    if request.author_ids:
        return _filter_by_author_ids(rows, request)

    query_tags = request.query.lower().split() if request.mode == "tag" else None
    result = []

    for row in rows:
        if request.mode == "tag":
            row_tags = row.get("标签", "").lower()
            if not all(qt in row_tags for qt in query_tags):
                continue
        else:
            if row.get("作者", "").lower() != request.query.lower():
                continue

        if request.filter_type:
            row_type = row.get("分类", "") or "未知"
            ft = request.filter_type.lower()
            if ft in ("novel", "小说"):
                if row_type not in ("小说",):
                    continue
            elif ft in ("illust", "漫画", "插画", "manga"):
                if row_type not in ("漫画",):
                    continue
            elif ft != row_type.lower():
                continue

        result.append(row)

    return result


def _classify_works(rows: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    standalone = []
    series_groups = {}

    for row in rows:
        series_name = row.get("系列", "").strip()
        if series_name:
            series_groups.setdefault(series_name, []).append(row)
        else:
            standalone.append(row)

    for sg in series_groups.values():
        sg.sort(key=lambda x: x.get("ID", ""))

    return standalone, series_groups


def _apply_like_cutoff(standalone: list[dict],
                       series_groups: dict[str, list[dict]],
                       limit: int) -> tuple[list[dict], dict[str, list[dict]]]:
    scored = []
    for row in standalone:
        likes = int(row.get("点赞", "0") or "0")
        scored.append({"type": "standalone", "likes": likes, "row": row})

    for name, srows in series_groups.items():
        total = sum(int(r.get("点赞", "0") or "0") for r in srows)
        avg = total / len(srows) if srows else 0
        scored.append({"type": "series", "likes": avg, "series_name": name, "rows": srows})

    scored.sort(key=lambda x: x["likes"], reverse=True)
    scored = scored[:limit]

    new_standalone = []
    new_series = {}
    for item in scored:
        if item["type"] == "standalone":
            new_standalone.append(item["row"])
        else:
            new_series[item["series_name"]] = item["rows"]

    return new_standalone, new_series


def _author_id_matches(book_id: str, author_id: str) -> bool:
    return len(book_id) >= 1 + len(author_id) and book_id[1:1 + len(author_id)] == author_id


def _filter_by_author_ids(rows: list[dict], request: ExportRequest) -> list[dict]:
    aid_set = set(request.author_ids)
    result = []
    for row in rows:
        bid = row.get("ID", "")
        if not any(_author_id_matches(bid, aid) for aid in aid_set):
            continue
        if request.filter_type:
            row_type = row.get("分类", "") or "未知"
            ft = request.filter_type.lower()
            if ft in ("novel", "小说"):
                if row_type not in ("小说",):
                    continue
            elif ft in ("illust", "漫画", "插画", "manga"):
                if row_type not in ("漫画",):
                    continue
            elif ft != row_type.lower():
                continue
        result.append(row)
    return result


def _build_type_groups(standalone: list[dict],
                        series_groups: dict[str, list[dict]]) -> dict[str, TypeGroup]:
    result = {}

    for row in standalone:
        ft = row.get("分类", "") or "未知"
        if ft not in result:
            result[ft] = TypeGroup(file_type=ft)
        result[ft].standalone.append(row)

    for sn, srows in series_groups.items():
        if not srows:
            continue
        ft = srows[0].get("分类", "") or "未知"
        if ft not in result:
            result[ft] = TypeGroup(file_type=ft)
        result[ft].series_groups[sn] = list(srows)

    for tg in result.values():
        tg.standalone.sort(key=lambda x: x.get("ID", ""))
        for sg in tg.series_groups.values():
            sg.sort(key=lambda x: x.get("ID", ""))

    return result
