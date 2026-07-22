"""source 操作 — 作者订阅管理与同步的业务逻辑层。"""
from __future__ import annotations

import time
import requests
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.core.author_manager import (
    list_all, resolve, upsert, update, unfollow,
    migrate_follows_csv,
)
from src.core.config import get_project_root
from src.core.download import append_to_download_json
from src.core.logging import get_logger
from src.core.work_manager import WorkManager
from src.downloader.pixiv.extractors import extract_pixiv_id

logger = get_logger("akm.source_op")

_TYPE_MAP: dict[str, str] = {
    "0": "[dim][插][/dim]",
    "1": "[dim][漫][/dim]",
    "2": "[dim][动][/dim]",
    "novel": "[dim][小][/dim]",
}


# ── 列表 ──────────────────────────────────────────────────


def list_sources_data() -> dict:
    """返回所有已关注来源及作品计数。

    Returns:
        {"sources": [{"uid", "name", "local_id", "status", "works_count",
                       "last_checked", "favorite"}], "total": int}
    """
    migrate_follows_csv()
    rows = list_all()
    if not rows:
        return {"sources": [], "total": 0}

    author_counts = Counter()
    for r in WorkManager.read():
        a = r.get("作者", "")
        if a:
            author_counts[a] += 1

    data = []
    for row in sorted(rows, key=lambda r: (not r.get("favorite", False), r.get("id", ""))):
        name = row.get("name", "")
        uid = row.get("pixiv_uid", "") or "-"
        lid = row.get("id", "") or "-"
        checked = row.get("last_checked", "") or "-"
        if checked and len(checked) > 10:
            checked = checked[:10]
        data.append({
            "uid": uid, "name": name, "local_id": lid,
            "status": row.get("follow_status", ""),
            "works_count": author_counts.get(name, 0),
            "last_checked": checked,
            "favorite": row.get("favorite", False),
        })
    return {"sources": data, "total": len(rows)}


# ── 关注 / 取消 ──────────────────────────────────────────


def follow_author_by_url(url: str) -> dict | None:
    """通过 URL 关注作者。

    Returns:
        {"uid", "name", "local_id", "already_followed", "row"} or None on failure.
    """
    from src.downloader import registry
    cls = registry.resolve(url)
    if not cls:
        return None
    downloader = cls()
    info = downloader.get_author_info(url)
    if not info:
        return None
    name, _ = info
    uid = downloader.extract_uid(url)
    already = resolve(uid) if uid else None
    row = upsert(uid=uid, name=name, homepage=url)
    if not row:
        return None
    return {"uid": uid, "name": name, "local_id": row.get("id", ""),
            "already_followed": bool(already), "row": row}


def queue_author_works(url: str) -> dict | None:
    """关注作者并排队其全部作品到下载队列。

    完整封装：resolve → get_author_info → extract_uid → upsert
    → get_user_works → source_set 去重 → 构建 entries → append_or_update。
    get_author_info 全程只调用一次（消除原 _follow_url 的重复网络调用）。

    Returns:
        {"uid", "name", "local_id", "already_followed", "row",
         "total", "skipped", "queued"} or None on failure.
        - total=0 表示作者已关注但无作品（仍 upsert，不入队）。
    """
    from src.downloader import registry
    cls = registry.resolve(url)
    if not cls:
        return None
    downloader = cls()

    info = downloader.get_author_info(url)
    if not info:
        return None
    name, _ = info
    uid = downloader.extract_uid(url)

    # 关注（upsert）——与 follow_author_by_url 相同的几行，独立实现以避免重复网络调用
    already = resolve(uid) if uid else None
    row = upsert(uid=uid, name=name, homepage=url)
    if not row:
        return None

    # 拉作品（网络调用，包异常）
    try:
        works = downloader.get_user_works(url)
    except Exception as e:
        logger.error("获取作者 %s 作品列表失败: %s", name, e)
        works = []

    # source_set 去重 + 构建 entries（work_type 推断下沉到此）
    in_library = WorkManager.source_set()
    entries = []
    skipped = 0
    for w in works:
        w_type = "novel" if "/novel/" in w else "illust"
        in_db = 1 if w in in_library else 0
        if in_db:
            skipped += 1
        entries.append({"url": w, "author_name": name,
                        "work_type": w_type, "is_in_db": in_db})

    added = append_to_download_json(entries)

    return {
        "uid": uid, "name": name, "local_id": row.get("id", ""),
        "already_followed": bool(already), "row": row,
        "total": len(works), "skipped": skipped, "queued": added,
    }


def follow_from_pixiv(cookie: str) -> dict:
    """导入 Pixiv 账号全部关注作者。

    Returns:
        {"new": int, "skipped": int, "authors": [{"uid", "name", "url"}],
         "error": str | None}
    """
    result = {"new": 0, "skipped": 0, "authors": [], "error": None}

    try:
        r = requests.get("https://www.pixiv.net/ajax/user/self", headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
            "Referer": "https://www.pixiv.net/",
        }, timeout=15)
        if not r.ok:
            result["error"] = f"获取账号信息失败: HTTP {r.status_code}"
            return result
        self_uid = r.json().get("userData", {}).get("id", "")
        if not self_uid:
            result["error"] = "无法获取 Pixiv UID，Cookie 可能已过期"
            return result
    except Exception as e:
        result["error"] = f"请求异常: {e}"
        return result

    followed = []
    offset = 0
    limit = 100
    while True:
        try:
            r = requests.get(
                f"https://www.pixiv.net/ajax/user/{self_uid}/following",
                params={"offset": offset, "limit": limit, "rest": "show", "tag": "", "lang": "zh"},
                headers={"User-Agent": "Mozilla/5.0", "Cookie": cookie, "Referer": "https://www.pixiv.net/"},
                timeout=20,
            )
            if not r.ok:
                break
            data = r.json()
            users = data.get("body", {}).get("users", [])
            if not users:
                break
            for u in users:
                followed.append({
                    "uid": str(u.get("userId", "")),
                    "name": u.get("userName", ""),
                    "url": f"https://www.pixiv.net/users/{u.get('userId', '')}",
                })
            offset += limit
            if len(users) < limit:
                break
        except Exception:
            break

    if not followed:
        result["error"] = "未获取到关注列表"
        return result

    for u in followed:
        already = resolve(u["uid"])
        if already:
            result["skipped"] += 1
        else:
            row = upsert(uid=u["uid"], name=u["name"], homepage=u["url"])
            if row:
                result["new"] += 1
                result["authors"].append(u)

    return result


def unfollow_targets(targets: str) -> dict:
    """取消关注，逗号分隔多个目标。

    Returns:
        {"unfollowed": int, "names": [str]}
    """
    names = []
    for tid in targets.split(","):
        tid = tid.strip()
        if not tid:
            continue
        row = resolve(tid)
        if not row:
            continue
        uid = row.get("pixiv_uid", "")
        if unfollow(uid):
            names.append(row.get("name", uid))
    return {"unfollowed": len(names), "names": names}


# ── 同步辅助 ──────────────────────────────────────────────


def resolve_sync_candidates(target: str | None, favorite_only: bool = False) -> list[dict]:
    """解析同步目标，返回候选作者列表。"""
    migrate_follows_csv()
    if target:
        row = resolve(target)
        return [row] if row else []
    rows = list_all()
    candidates = [r for r in rows
                  if r.get("follow_status", "") in ("active", "paused", "dead")
                  and (r.get("pixiv_uid") or "").strip()
                  and (not favorite_only or r.get("favorite"))]
    candidates.sort(key=lambda r: (not r.get("favorite", False), r.get("id", "")))
    return candidates


def backfill_homepages(candidates: list[dict]) -> None:
    """为有 UID 但无主页的作者补全默认 URL。"""
    for row in candidates:
        uid = (row.get("pixiv_uid") or "").strip()
        homepage = (row.get("homepage") or "").strip()
        if uid and not homepage:
            homepage = f"https://www.pixiv.net/users/{uid}"
            update(uid, homepage=homepage)
            row["homepage"] = homepage


def should_recheck_dead(last_checked: str, now_ts: float) -> bool:
    """判断注销作者是否应重新检查（>7 天）。"""
    if not last_checked:
        return True
    try:
        dt = datetime.strptime(last_checked[:10], "%Y-%m-%d")
        return now_ts - dt.timestamp() > 7 * 24 * 3600
    except ValueError:
        return True


def build_work_index(sync_targets: list[dict]) -> tuple[dict[str, set[str]], dict[str, str]]:
    """读取全部作品，构建 {local_id: {work_ids}} 和 {source_url: row_id} 索引。"""
    all_rows = WorkManager.read()
    work_index: dict[str, set[str]] = {}
    source_to_id: dict[str, str] = {}
    for r in all_rows:
        wid = extract_pixiv_id(r.get("来源", ""))
        if not wid:
            continue
        rid = r.get("ID", "")
        for row in sync_targets:
            lid = row.get("id", "")
            if lid and author_id_matches(rid, lid):
                work_index.setdefault(lid, set()).add(wid)
        source_to_id[r.get("来源", "")] = rid
    return work_index, source_to_id


_sync_downloader_cache: dict[str, "BaseDownloader"] = {}


def get_sync_downloader(url: str | None = None) -> "BaseDownloader" | None:
    """获取同步用的下载器实例（按 name 缓存单例）。

    优先按 url resolve；无 url 时取第一个已注册下载器。
    缓存复用其 client/config/existing_sources 快照，避免重复实例化开销。

    Returns:
        BaseDownloader 实例 or None（无已注册下载器）。
    """
    from src.downloader import registry
    cls = registry.resolve(url) if url else None
    if not cls:
        sites = registry.list_sites()
        if not sites:
            return None
        cls = registry._entries.get(sites[0])
    if not cls:
        return None
    key = cls.name
    if key not in _sync_downloader_cache:
        _sync_downloader_cache[key] = cls()
    return _sync_downloader_cache[key]


def get_sync_max_workers(downloader=None) -> int:
    """获取同步线程数。

    优先用 downloader.max_workers（如 PixivDownloader 的 property）；
    基类无该属性则兜底 4。
    """
    if downloader is None:
        downloader = get_sync_downloader()
    return getattr(downloader, "max_workers", 4)


def sync_one_author(row: dict, downloader=None, dry_run: bool = False,
                    work_index: dict[str, set[str]] | None = None,
                    source_to_id: dict[str, str] | None = None,
                    stop_event=None,
                    download_lock=None) -> dict:
    """单个作者的同步逻辑：对比远程与本地作品差异，标记删除，入队新作。

    Returns:
        {"new": int, "deleted": int, "unchanged": int, "downloaded": int,
         "new_urls": [...], "new_ids": [...]}
    """
    uid = row.get("pixiv_uid", "")
    name = row.get("name", "")
    homepage = row.get("homepage", "")
    local_id = row.get("id", "")
    result = {"new": 0, "deleted": 0, "unchanged": 0, "downloaded": 0}

    if not homepage or (stop_event and stop_event.is_set()):
        return result

    if not downloader:
        from src.downloader import registry
        cls = registry.resolve(homepage)
        if not cls:
            return result
        downloader = cls()

    try:
        works = downloader.get_user_works(uid if uid else homepage)
    except Exception as e:
        logger.error("获取作品列表失败: %s", e)
        return result

    if not works:
        if not check_user_exists(uid, None):
            update(uid, follow_status="dead",
                   last_checked=time.strftime("%Y-%m-%d %H:%M:%S"))
            return result
        logger.warning("%s (%s) App API 返回空，但 Web API 确认账号存在，恢复为活跃状态",
                       name, uid)
        upsert(uid=uid, name=name, homepage=homepage, latest_work_id="")
        update(uid, follow_status="active",
               last_checked=time.strftime("%Y-%m-%d %H:%M:%S"))
        return result

    work_ids = {extract_pixiv_id(u) for u in works}

    if work_index is not None:
        all_wids = set().union(*work_index.values()) if work_index else set()
        local_ids = work_index.get(local_id, set()) | (all_wids & work_ids)
    else:
        local_ids = set()
        for r in WorkManager.read():
            src = r.get("来源", "")
            wid = extract_pixiv_id(src)
            if not wid:
                continue
            if author_id_matches(r.get("ID", ""), local_id) or wid in work_ids:
                local_ids.add(wid)

    new_works = work_ids - local_ids
    deleted_works = local_ids - work_ids

    upsert(uid=uid, name=name, homepage=homepage,
           latest_work_id=max(work_ids, key=int) if work_ids else "")
    update(uid, last_checked=time.strftime("%Y-%m-%d %H:%M:%S"))

    if deleted_works and not dry_run:
        if source_to_id is not None:
            urls_to_mark = {s for s, rid in source_to_id.items()
                            if author_id_matches(rid, local_id)
                            and extract_pixiv_id(s) in deleted_works}
        else:
            rows = WorkManager.read()
            urls_to_mark = set()
            for r in rows:
                if not author_id_matches(r.get("ID", ""), local_id):
                    continue
                src = r.get("来源", "")
                if extract_pixiv_id(src) in deleted_works:
                    urls_to_mark.add(src)
        if urls_to_mark:
            WorkManager.mark_deleted(urls_to_mark)

    if new_works:
        new_urls = [u for u in works if extract_pixiv_id(u) in new_works]
        result["new_urls"] = new_urls
        result["new_ids"] = [extract_pixiv_id(u) for u in new_urls]
        if not dry_run:
            entries = [{"url": u, "author_name": name, "work_type": "novel" if "/novel/" in u else "illust"}
                        for u in new_urls]
            if entries:
                if download_lock:
                    with download_lock:
                        result["downloaded"] = append_to_download_json(entries)
                else:
                    result["downloaded"] = append_to_download_json(entries)

    result["new"] = len(new_works)
    result["deleted"] = len(deleted_works)
    result["unchanged"] = len(local_ids & work_ids)
    return result


# ── Pixiv API 辅助 ────────────────────────────────────────


def check_user_exists(uid: str, cookie: str | None) -> bool:
    """通过 Pixiv Web API 检查用户是否仍然存在。"""
    if not cookie:
        return True
    try:
        r = requests.get(f"https://www.pixiv.net/ajax/user/{uid}", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": cookie,
            "Referer": "https://www.pixiv.net/",
        }, timeout=10)
        if r.ok:
            data = r.json()
            if data.get("error"):
                return False
            return bool(data.get("body"))
    except Exception:
        pass
    return True


def fetch_work_details(urls: list[str], cookie: str) -> list[tuple[str, str, str]]:
    """获取作品标题和类型。返回 [(work_id, title, type_tag)]。"""
    results = []
    for url in urls[:10]:
        wid = extract_pixiv_id(url)
        try:
            if "/novel/" in url:
                api_url = f"https://www.pixiv.net/ajax/novel/{wid}"
            else:
                api_url = f"https://www.pixiv.net/ajax/illust/{wid}"
            r = requests.get(api_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Cookie": cookie,
                "Referer": "https://www.pixiv.net/",
            }, timeout=10)
            if r.ok:
                body = r.json().get("body", {})
                title = body.get("title") or body.get("illustTitle") or ""
                if "/novel/" in url:
                    type_tag = _TYPE_MAP["novel"]
                else:
                    itype = str(body.get("illustType", ""))
                    type_tag = _TYPE_MAP.get(itype, "[dim][?][/dim]")
                results.append((wid, title or url, type_tag))
            else:
                results.append((wid, url, _TYPE_MAP["0"]))
        except Exception:
            results.append((wid, url, _TYPE_MAP["0"]))
    return results


# ── 元数据更新 ─────────────────────────────────────────────


def compute_update_flags(args) -> dict:
    """根据 argparse 参数计算需要更新的字段标志。

    Returns:
        {"update_tags", "update_likes", "update_desc", "update_title",
         "update_author"}
    """
    any_specific = any([args.tags, args.likes, args.description, args.title, args.update_author])
    return {
        "update_tags": args.update_all or (not any_specific) or args.tags or args.likes or args.description,
        "update_likes": args.update_all or (not any_specific) or args.likes,
        "update_desc": args.update_all or (not any_specific) or args.description,
        "update_title": args.title,
        "update_author": args.update_author or args.update_all,
    }


def update_single_work_metadata(work: dict, downloader, flags: dict,
                                dry_run: bool = False) -> dict | None:
    """获取单个作品最新元数据，计算差异并应用更新。

    Args:
        work: 作品行 dict
        downloader: 下载器实例（需提供 get_info 方法）
        flags: compute_update_flags() 返回值
        dry_run: 仅预览不实际写入

    Returns:
        {"book_id", "title", "changes": [str]} or None if no changes.
    """
    bid = work.get("ID", "")
    title = work.get("标题", "")
    src = work.get("来源", "")
    old_author = (work.get("作者", "") or "").strip()
    old_series = (work.get("系列", "") or "").strip()

    try:
        info = downloader.get_info(src)
        if not info:
            return None
    except Exception:
        return None

    field_updates = {}
    new_author = ""
    new_series = ""
    changes_desc = []

    if flags.get("update_tags"):
        new_tags = info.get("tags") or []
        new_tag_set = set(new_tags) if isinstance(new_tags, list) else set(str(new_tags).split(","))
        old_tag_set = set(t.strip() for t in (work.get("标签", "") or "").split(",") if t.strip())
        added = new_tag_set - old_tag_set
        if added:
            merged = sorted(old_tag_set | new_tag_set)
            field_updates["标签"] = ",".join(merged)
            changes_desc.append(f"补足标签: +{', '.join(sorted(added))}")

    if flags.get("update_likes"):
        new_likes = str(info.get("like_count", 0))
        old_likes = str(work.get("点赞", "0") or "0")
        if new_likes != old_likes:
            field_updates["点赞"] = new_likes
            changes_desc.append(f"点赞 {old_likes} → {new_likes}")

    if flags.get("update_desc"):
        new_desc = (info.get("description") or "").strip()
        old_desc = (work.get("简介", "") or "").strip()
        if new_desc != old_desc:
            field_updates["简介"] = new_desc
            changes_desc.append("简介已更新")

    if flags.get("update_title"):
        new_title = (info.get("title") or "").strip()
        if new_title and new_title != title:
            field_updates["标题"] = new_title
            changes_desc.append(f"标题 → {new_title}")

    if flags.get("update_author"):
        na = (info.get("author") or "").strip()
        if na and na != old_author:
            new_author = na
            changes_desc.append(f"作者 {old_author} → {na}")

    new_series_name = (info.get("series") or "").strip()
    if new_series_name and new_series_name != old_series:
        new_series = new_series_name
        changes_desc.append(f"系列 {old_series} → {new_series_name}")

    if not field_updates and not new_author and not new_series:
        return None

    if not dry_run:
        if new_author or new_series or (flags.get("update_title") and "标题" in field_updates):
            WorkManager.update_entry_full(bid, field_updates,
                                          new_author=new_author,
                                          new_series=new_series)
        else:
            WorkManager.update_entry(bid, field_updates)

    return {"book_id": bid, "title": title, "changes": changes_desc}


# ── 重置 / 文件标记 ────────────────────────────────────────


def reset_dead_authors(target: str | None = None) -> dict:
    """将注销状态的作者重置为活跃。

    Returns:
        {"reset": int, "names": [str], "not_found": bool}
    """
    rows = list_all()
    dead_rows = [r for r in rows if r.get("follow_status", "") == "dead"]

    if target:
        target = target.strip()
        matched = [r for r in dead_rows
                   if r.get("pixiv_uid") == target
                   or r.get("id") == target
                   or r.get("name") == target]
        if not matched:
            return {"reset": 0, "names": [], "not_found": True}
        names = []
        for r in matched:
            uid = r.get("pixiv_uid", "")
            name = r.get("name", "")
            update(uid, follow_status="active", last_checked="")
            names.append(f"{name}" + (f" ({uid})" if uid else ""))
        return {"reset": len(names), "names": names, "not_found": False}

    names = []
    for r in dead_rows:
        uid = r.get("pixiv_uid", "")
        name = r.get("name", "")
        update(uid, follow_status="active", last_checked="")
        names.append(f"{name}" + (f" ({uid})" if uid else ""))
    return {"reset": len(names), "names": names, "not_found": False}


def has_new_favorites() -> bool:
    """检查 .new_favorites 哨兵文件是否有内容。"""
    nf = get_project_root() / ".new_favorites"
    return nf.exists() and nf.read_text(encoding="utf-8").strip() != ""


def save_updated_ids(sync_targets: list[dict], results: dict) -> None:
    """将同步变更的作者 ID 写入 .updated_authors 文件。"""
    changed_ids = []
    for row in sync_targets:
        uid = str(row.get("pixiv_uid", ""))
        r = results.get(uid, {})
        if r.get("new") or r.get("deleted"):
            lid = str(row.get("id", ""))
            if lid:
                changed_ids.append(lid)
    new_fav_file = get_project_root() / ".new_favorites"
    if new_fav_file.exists():
        new_ids = new_fav_file.read_text(encoding="utf-8").strip()
        if new_ids:
            for nid in new_ids.split(","):
                nid = nid.strip()
                if nid and nid not in changed_ids:
                    changed_ids.append(nid)
        new_fav_file.unlink()
    if changed_ids:
        ids_file = get_project_root() / ".updated_authors"
        ids_file.write_text(",".join(changed_ids), encoding="utf-8")


# ── 通用辅助 ──────────────────────────────────────────────


def author_id_matches(rid: str, local_id: str) -> bool:
    """检查作品 ID 中是否嵌入了指定的作者 local ID。"""
    return len(rid) >= 1 + len(local_id) and rid[1:1 + len(local_id)] == local_id


# ── URL 批量入队 ──────────────────────────────────────────


def queue_urls(urls: list[str]) -> dict:
    """批量将作品 URL 加入下载队列。

    自动识别 Pixiv 作品/小说 URL，提取 work_id，判断类型。
    不支持的 URL 会跳过。

    Returns:
        {"queued": int, "skipped": int, "invalid": [str]}
    """
    entries = []
    invalid = []

    for raw in urls:
        url = raw.strip()
        if not url:
            continue

        # Pixiv 作品/小说
        if "pixiv.net" in url:
            work_type = "novel" if "/novel/" in url else "illust"
            entries.append({"url": url, "work_type": work_type})
        else:
            invalid.append(url)

    queued = 0
    if entries:
        queued = append_to_download_json(entries)

    skipped = len(entries) - queued
    return {"queued": queued, "skipped": skipped, "invalid": invalid}
