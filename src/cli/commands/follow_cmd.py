import argparse
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.cli.base import BaseCommand
from src.core.logging import logger
from src.operations import source_op


class FollowCommand(BaseCommand):
    verb = "follow"
    nouns: list[str] = []
    description = "关注 Pixiv 作者 / 同步作者新作到下载队列"

    def __init__(self) -> None:
        super().__init__()
        self._stop_event = threading.Event()
        self._download_lock = threading.Lock()
        try:
            signal.signal(signal.SIGINT, self._handle_sigint)
        except (ValueError, OSError):
            pass

    def _handle_sigint(self, signum, frame):
        if not self._stop_event.is_set():
            self.output.info("\n[yellow]🛑 收到停止信号[/yellow]")
        self._stop_event.set()

    def _cookie(self) -> str:
        return self.config.get("pixiv", {}).get("cookie", "")

    def _max_workers(self) -> int:
        try:
            from src.cli.downplugin.pixiv.config import PixivConfig
            return PixivConfig.from_file().max_workers
        except Exception:
            return 4

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("url", type=str, nargs="?", default=None,
                            help="Pixiv 作者主页 URL（提供时为关注；省略时为同步）")
        parser.add_argument("--pixiv", action="store_true",
                            help="导入当前 Pixiv 账号的全部关注作者")
        parser.add_argument("--dry-run", action="store_true", help="仅对比不修改")
        parser.add_argument("--favorite", action="store_true", help="仅同步收藏作者")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        # --pixiv: 批量导入关注列表
        if args.pixiv:
            return self._follow_pixiv()

        # 提供 URL: 关注单个作者并排队全部作品
        if args.url:
            return self._follow_url(args.url)

        # 无 URL: 同步新作
        return self._sync(args)

    # ── 关注 ──────────────────────────────────────────────

    def _follow_url(self, url: str) -> int:
        from src.cli.downplugin import registry
        from src.core.download import append_or_update
        from src.operations import source_set

        cls = registry.resolve(url)
        if not cls:
            self.output.info(f"不支持的链接: {url}")
            return 1
        downloader = cls()

        info = downloader.get_author_info(url)
        if not info:
            self.output.info("无法获取作者信息，请检查 URL 或 Cookie")
            return 1
        name, _ = info
        uid = downloader.extract_uid(url)

        self.output.info(f"作者: {name}" + (f" (UID: {uid})" if uid else ""))

        works = downloader.get_user_works(url)
        if not works:
            self.output.info("未获取到任何作品，作者可能已清空或账号异常")
            result = source_op.follow_author_by_url(url)
            if result:
                self.output.info(f"已关注: {name}")
            return 1

        result = source_op.follow_author_by_url(url)
        if result:
            lid = result["local_id"]
            tag = "已关注" if result["already_followed"] else "已关注"
            self.output.info(f"{tag}: {name} (本地ID: {lid})")

        in_library = source_set()
        entries = []
        skipped = 0
        for w in works:
            w_type = "novel" if "/novel/" in w else "illust"
            in_db = 1 if w in in_library else 0
            if in_db:
                skipped += 1
            entries.append({"url": w, "author_name": name, "work_type": w_type, "is_in_db": in_db})
        added = append_or_update(entries)

        self.output.info(f"作品总数: {len(works)} | 已入库跳过: {skipped} | 新加入队列: {added}")
        return self.output.result(True, data={
            "author": name, "uid": uid, "total": len(works),
            "skipped": skipped, "queued": added,
        })

    def _follow_pixiv(self) -> int:
        cookie = self._cookie()
        if not cookie:
            self.output.info("未配置 Cookie，请先配置 Pixiv Cookie")
            return 1
        self.output.info("[bold]正在获取 Pixiv 关注列表...[/bold]")
        result = source_op.follow_from_pixiv(cookie)
        if result["error"]:
            self.output.info(result["error"])
            return 1
        for u in result["authors"]:
            self.output.info(f"  + {u['name']} ({u['uid']})")
        self.output.info("")
        if result["new"]:
            self.output.info(f"[green]新增 {result['new']} 位作者[/green]")
        if result["skipped"]:
            self.output.info(f"[dim]跳过 {result['skipped']} 位（已关注）[/dim]")
        return 0

    # ── 同步 ──────────────────────────────────────────────

    def _sync(self, args: argparse.Namespace) -> int:
        from src.cli.downplugin.pixiv.downloader import PixivDownloader

        candidates = source_op.resolve_sync_candidates(None, getattr(args, "favorite", False))
        if not candidates:
            self.output.info("没有来源可同步")
            return 0

        source_op.backfill_homepages(candidates)

        active = [r for r in candidates if r.get("follow_status", "") == "active"]
        paused = [r for r in candidates if r.get("follow_status", "") == "paused"]
        dead = [r for r in candidates if r.get("follow_status", "") == "dead"]

        now_ts = time.time()
        recheck_dead = [
            r for r in dead
            if source_op.should_recheck_dead(r.get("last_checked", ""), now_ts)
        ]

        self.output.info("[bold]请稍等，正在检查更新...[/bold]")
        parts = []
        if active:
            parts.append(f"{len(active)} 名活跃")
        if recheck_dead:
            parts.append(f"{len(recheck_dead)} 名重试")
        self.output.info(f"共 {' + '.join(parts)} 作者需更新" if parts else "无作者需更新")
        max_workers = self._max_workers()
        self.output.info(f"运行模式: 并行，{max_workers} 线程。[dim](Ctrl+C 退出)[/dim]")
        self.output.info("")

        sync_targets = active + recheck_dead
        if not sync_targets:
            return 0

        def _dwidth(s: str) -> int:
            w = 0
            for ch in s:
                cp = ord(ch)
                if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F
                        or 0xFF00 <= cp <= 0xFFEF or 0x2E80 <= cp <= 0x2FDF
                        or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF):
                    w += 2
                else:
                    w += 1
            return w

        def _rpad(s: str, w: int) -> str:
            return s + " " * max(0, w - _dwidth(s))

        name_width = max((_dwidth(str(r.get("name", ""))) for r in sync_targets), default=0)

        downloader = PixivDownloader()
        work_index, source_to_id = source_op.build_work_index(sync_targets)

        results: dict[str, dict] = {}
        from tqdm import tqdm
        total = len(sync_targets)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for row in sync_targets:
                uid_key = row.get("pixiv_uid", "")
                futures[pool.submit(
                    source_op.sync_one_author, row, downloader, getattr(args, "dry_run", False),
                    work_index, source_to_id, self._stop_event, self._download_lock,
                )] = uid_key

            pbar = tqdm(total=total, desc="同步检查", unit="人", ncols=80)
            try:
                for future in as_completed(futures):
                    if self._stop_event.is_set():
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    uid_key = futures[future]
                    try:
                        results[uid_key] = future.result()
                    except Exception as e:
                        logger.error("同步 %s 异常: %s", uid_key, e)
                    pbar.update(1)
            except KeyboardInterrupt:
                self._stop_event.set()
                pool.shutdown(wait=False, cancel_futures=True)
            finally:
                pbar.close()

        if self._stop_event.is_set():
            self.output.info("[dim]同步已中断[/dim]")

        changed_count = 0
        unchanged: list[str] = []

        for row in sync_targets:
            name = str(row.get("name", ""))
            uid = str(row.get("pixiv_uid", ""))
            r = results.get(uid, {})
            if not r:
                unchanged.append(name)
                continue
            is_fav = row.get("favorite", False)
            if r.get("new") or r.get("deleted"):
                parts = []
                if r.get("new"):
                    parts.append(f"[green]+{r['new']}[/green]")
                if r.get("deleted"):
                    parts.append(f"[red]-{r['deleted']}[/red]")
                n = _rpad(name, name_width)
                fav_icon = " [red]♥[/red]" if is_fav else ""
                line = f"  {n}{fav_icon} ({uid})  {', '.join(parts)}"
                added = r.get("downloaded", 0)
                if added:
                    line += f"  [dim]→ 已入队 {added} 个[/dim]"
                if not changed_count:
                    self.output.info("")
                self.output.info(line)
                if r.get("new_urls"):
                    works = source_op.fetch_work_details(r["new_urls"][:10], self._cookie())
                    if works:
                        total_new = len(r["new_urls"])
                        for i, (tid, t, type_tag) in enumerate(works):
                            is_last = (i == len(works) - 1 and total_new <= 10)
                            prefix = "   └──" if is_last else "   ├──"
                            self.output.info(f"{prefix} [dim]{tid}[/dim]  {type_tag} {t}")
                        if total_new > 10:
                            self.output.info(f"   └── [dim]... 等 {total_new - 10} 部[/dim]")
                changed_count += 1
            else:
                unchanged.append(name)

        if unchanged:
            self.output.info(f"\n[dim]无更新 ({len(unchanged)}): {', '.join(unchanged)}[/dim]")

        if paused:
            self.output.info("")
            for p in paused:
                name = p.get("name", "")
                uid = (p.get("pixiv_uid") or "").strip()
                self.output.info(f"[yellow]停止追更: {name}" + (f" ({uid})" if uid else "") + "[/yellow]")

        if dead:
            self.output.info("")
            for d in dead:
                name = d.get("name", "")
                uid = (d.get("pixiv_uid") or "").strip()
                self.output.info(f"[dim]已停更: {name}" + (f" ({uid})" if uid else "") + "[/dim]")

        if changed_count > 0 or source_op.has_new_favorites():
            source_op.save_updated_ids(sync_targets, results)
            return 2
        return 0
