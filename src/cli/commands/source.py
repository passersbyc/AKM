"""source 命令 — Pixiv 内容来源订阅管理：列出、关注、取消、同步、连通性测试。"""
import argparse
import signal
import subprocess
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from src.cli.core import BaseCommand
from src.core.logging import get_logger
from src.operations import source_op

logger = get_logger("akm.source")


class SourceCommand(BaseCommand):
    _download_lock = threading.Lock()

    def __init__(self) -> None:
        super().__init__()
        self._stop_event = threading.Event()
        try:
            signal.signal(signal.SIGINT, self._handle_sigint)
        except (ValueError, OSError):
            pass

    def _handle_sigint(self, signum, frame):
        if not self._stop_event.is_set():
            self._print("\n[yellow]🛑 收到停止信号[/yellow]")
        self._stop_event.set()

    def _max_workers(self) -> int:
        try:
            from src.cli.downplugin.pixiv.config import PixivConfig
            return PixivConfig.from_file().max_workers
        except Exception:
            return 4

    def _cookie(self) -> str:
        return self.config.get("pixiv", {}).get("cookie", "")

    @property
    def name(self) -> str:
        return "source"

    @property
    def description(self) -> str:
        return "Pixiv 内容来源管理：列出、关注、取消、同步、连通性测试"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        subs = parser.add_subparsers(dest="subcommand", help="子命令")

        p_list = subs.add_parser("list", help="列出所有已关注源")

        p_follow = subs.add_parser("follow", help="关注 Pixiv 作者")
        p_follow.add_argument("url", type=str, nargs="?", default=None,
                              help="Pixiv 作者主页 URL（--pixiv 时可选）")
        p_follow.add_argument("--pixiv", action="store_true",
                              help="导入当前 Pixiv 账号的全部关注作者")

        p_unfollow = subs.add_parser("unfollow", help="取消关注")
        p_unfollow.add_argument("id", type=str,
                                help="Pixiv UID / 本地ID / 名称，逗号分隔可批量")

        p_sync = subs.add_parser("sync", help="同步作者新作到下载队列")
        p_sync.add_argument("id", type=str, nargs="?", default=None,
                            help="Pixiv UID / 本地ID / 名称（不指定则同步全部活跃作者）")
        p_sync.add_argument("--all", action="store_true", help="同步所有活跃作者")
        p_sync.add_argument("--dry-run", action="store_true", help="仅对比不修改")
        p_sync.add_argument("--favorite", action="store_true", help="仅同步收藏作者")

        p_update = subs.add_parser("update", help="更新已有作品元数据（标签/简介/点赞/作者）")
        p_update.add_argument("author", type=str, nargs="?", default=None,
                              help="作者名/ID 或作品ID（不指定则更新全部）")
        p_update.add_argument("--dry-run", action="store_true", help="仅预览变更")
        p_update.add_argument("--tags", action="store_true", help="仅更新标签")
        p_update.add_argument("--likes", action="store_true", help="仅更新点赞数")
        p_update.add_argument("--description", action="store_true", help="仅更新简介")
        p_update.add_argument("--title", action="store_true", help="仅更新标题")
        p_update.add_argument("--author-name", action="store_true", dest="update_author",
                              help="更新作者名（Pixiv 改名时同步）")
        p_update.add_argument("--all", dest="update_all", action="store_true",
                              help="更新全部元数据（含作者名）")

        p_ping = subs.add_parser("ping", help="测试 Pixiv 连通性")
        p_ping.add_argument("--mode", "-m", choices=["http", "icmp"], default="http",
                            help="测试模式 (默认: http)")
        p_ping.add_argument("--timeout", "-t", type=int, default=10,
                            help="超时时间（秒）(默认: 10)")

        p_reset = subs.add_parser("reset", help="将注销/停更的作者状态重置为正常")
        p_reset.add_argument("target", type=str, nargs="?", default=None,
                             help="Pixiv UID / 本地ID / 名称（不指定则重置全部注销作者）")

    def execute(self, args: argparse.Namespace) -> int:
        if args.subcommand == "list":
            return self._cmd_list()
        elif args.subcommand == "follow":
            return self._cmd_follow(args)
        elif args.subcommand == "unfollow":
            return self._cmd_unfollow(args.id)
        elif args.subcommand == "sync":
            fav = getattr(args, "favorite", False)
            if args.all:
                return self._cmd_sync(None, getattr(args, "dry_run", False), favorite_only=fav)
            return self._cmd_sync(args.id, getattr(args, "dry_run", False), favorite_only=fav)
        elif args.subcommand == "update":
            return self._cmd_update(args)
        elif args.subcommand == "ping":
            return self._cmd_ping(args)
        elif args.subcommand == "reset":
            return self._cmd_reset(args)
        else:
            self._print_info("子命令: list / follow / unfollow / sync / update / ping / reset")
            return 1

    # ── list ──────────────────────────────────────────────

    def _cmd_list(self) -> int:
        result = source_op.list_sources_data()
        if not result["sources"]:
            self._print_info("还没有关注任何来源，使用 source follow <url> 添加")
            return self._respond(True, data={"sources": []})

        from rich.table import Table

        table = Table(show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("名称", style="bold")
        table.add_column("UID", style="cyan")
        table.add_column("ID", style="magenta", justify="center")
        table.add_column("作品", justify="right")
        table.add_column("状态", justify="center")
        table.add_column("上次检查", style="dim")

        for s in result["sources"]:
            icon = "\u25cf" if s["status"] == "active" else "\u00d7"
            color = "green" if s["status"] == "active" else "dim"
            status_display = f"[{color}]{icon}[/{color}]"
            table.add_row(s["name"], s["uid"], s["local_id"],
                          str(s["works_count"]), status_display, s["last_checked"])

        self._print(table)
        self._print(f"[dim]共计 {result['total']} 个来源[/dim]")
        return self._respond(True, data={"sources": result["sources"]})

    # ── follow ────────────────────────────────────────────

    def _cmd_follow(self, args: argparse.Namespace) -> int:
        if args.pixiv:
            return self._cmd_follow_pixiv()

        url = args.url
        if not url:
            self._print_info("请提供 Pixiv 作者主页 URL，或使用 --pixiv 导入全部关注")
            return 1

        result = source_op.follow_author_by_url(url)
        if not result:
            self._print_info("不支持的 URL 或获取作者信息失败，请检查 URL 或 Cookie")
            return 1

        tag = "已关注" if result["already_followed"] else "已关注作者"
        self._print_info(f"{tag}: {result['name']} (UID: {result['uid']})")
        lid = result["local_id"]
        if lid:
            self._print_info(f"  本地ID: {lid}")
        self._print_info(f"  主页:   {url}")
        row = result["row"]
        status = row.get("follow_status", "")
        self._print_info(f"  状态:   {status}")
        note = row.get("note", "")
        if note:
            self._print_info(f"  备注:   {note}")
        data = {"uid": result["uid"], "name": result["name"], "local_id": lid}
        if result["already_followed"]:
            data["already_followed"] = True
            return self._respond(True, data=data, exit_code=2)
        return self._respond(True, data=data)

    def _cmd_follow_pixiv(self) -> int:
        cookie = self._cookie()
        if not cookie:
            self._print_info("未配置 Cookie，请先运行 akm auth cookie")
            return 1

        self._print("[bold]正在获取 Pixiv 关注列表...[/bold]")
        result = source_op.follow_from_pixiv(cookie)

        if result["error"]:
            self._print_info(result["error"])
            return 1

        for u in result["authors"]:
            self._print(f"  + {u['name']} ({u['uid']})")

        self._print()
        if result["new"]:
            self._print(f"[green]新增 {result['new']} 位作者[/green]")
        if result["skipped"]:
            self._print(f"[dim]跳过 {result['skipped']} 位（已关注）[/dim]")
        return 0

    # ── unfollow ──────────────────────────────────────────

    def _cmd_unfollow(self, targets: str) -> int:
        result = source_op.unfollow_targets(targets)
        if result["unfollowed"] == 0:
            self._print_info(f"未找到匹配的来源: {targets}")
            return 1
        for name in result["names"]:
            self._print_info(f"已取消关注: {name}")
        return self._respond(True, data={"unfollowed": result["unfollowed"]})

    # ── sync ──────────────────────────────────────────────

    def _cmd_sync(self, target: str | None, dry_run: bool, favorite_only: bool = False) -> int:
        from src.cli.downplugin.pixiv.downloader import PixivDownloader

        candidates = source_op.resolve_sync_candidates(target, favorite_only)
        if not target and not candidates:
            self._print_info("没有来源可同步")
            return 0
        if target and not candidates:
            self._print_info(f"未找到来源: {target}")
            return 1

        source_op.backfill_homepages(candidates)

        active = [r for r in candidates if r.get("follow_status", "") == "active"]
        paused = [r for r in candidates if r.get("follow_status", "") == "paused"]
        dead = [r for r in candidates if r.get("follow_status", "") == "dead"]

        now_ts = time.time()
        recheck_dead = [
            r for r in dead
            if source_op.should_recheck_dead(r.get("last_checked", ""), now_ts)
        ]

        self._print(f"[bold]请稍等，正在检查更新...[/bold]")
        parts = []
        if active:
            parts.append(f"{len(active)} 名活跃")
        if recheck_dead:
            parts.append(f"{len(recheck_dead)} 名重试")
        self._print(f"共 {' + '.join(parts)} 作者需更新" if parts else "无作者需更新")
        max_workers = self._max_workers()
        self._print(f"运行模式: 并行，{max_workers} 线程。[dim](Ctrl+C 退出)[/dim]")
        self._print()

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
        total = len(sync_targets)

        from tqdm import tqdm

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for row in sync_targets:
                uid_key = row.get("pixiv_uid", "")
                futures[pool.submit(
                    source_op.sync_one_author, row, downloader, dry_run,
                    work_index, source_to_id, self._stop_event,
                    self._download_lock
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
            self._print("[dim]同步已中断[/dim]")

        changed_count = 0
        unchanged: list[str] = []

        for row in sync_targets:
            name = str(row.get("name", ""))
            uid = str(row.get("pixiv_uid", ""))
            r = results.get(uid, {})
            if not r:
                unchanged.append(name)
                continue
            added = r.get("downloaded", 0)
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
                if added:
                    line += f"  [dim]→ 已入队 {added} 个[/dim]"
                if not changed_count:
                    self._print("")
                self._print(line)
                if r.get("new_urls"):
                    works = source_op.fetch_work_details(r["new_urls"][:10], self._cookie())
                    if works:
                        total_new = len(r["new_urls"])
                        for i, (tid, t, type_tag) in enumerate(works):
                            is_last = (i == len(works) - 1 and total_new <= 10)
                            prefix = "   └──" if is_last else "   ├──"
                            self._print(f"{prefix} [dim]{tid}[/dim]  {type_tag} {t}")
                        if total_new > 10:
                            self._print(f"   └── [dim]... 等 {total_new - 10} 部[/dim]")
                changed_count += 1
            else:
                unchanged.append(name)

        if unchanged:
            names = ", ".join(unchanged)
            self._print(f"\n[dim]无更新 ({len(unchanged)}): {names}[/dim]")

        if paused:
            self._print("")
            for p in paused:
                name = p.get("name", "")
                uid = (p.get("pixiv_uid") or "").strip()
                self._print(f"[yellow]停止追更: {name}" + (f" ({uid})" if uid else "") + "[/yellow]")

        if dead:
            self._print("")
            for d in dead:
                name = d.get("name", "")
                uid = (d.get("pixiv_uid") or "").strip()
                self._print(f"[dim]已停更: {name}" + (f" ({uid})" if uid else "") + "[/dim]")

        if changed_count > 0 or source_op.has_new_favorites():
            source_op.save_updated_ids(sync_targets, results)
            return 2
        return 0

    # ── update ────────────────────────────────────────────

    def _cmd_update(self, args: argparse.Namespace) -> int:
        from src.cli.downplugin.pixiv.downloader import PixivDownloader
        from src.core.author_manager import resolve as author_resolve
        from src.core.work_manager import WorkManager

        works = WorkManager.read()
        if not works:
            self._print_info("库里没有作品")
            return 0

        if args.author:
            author = author_resolve(args.author)
            if author:
                works = [w for w in works if w.get("作者", "") == author.get("name", "")]
            else:
                book = WorkManager.get_by_id(args.author)
                if book:
                    works = [book]
                else:
                    self._print_info(f"未找到作者或作品: {args.author}")
                    return 1
            if not works:
                self._print_info(f"没有匹配的作品")
                return 0

        pixiv_works = [w for w in works if "pixiv.net" in (w.get("来源", "") or "")]
        if not pixiv_works:
            self._print_info("没有 Pixiv 来源的作品")
            return 0

        flags = source_op.compute_update_flags(args)
        what = self._describe_update_scope(flags, args)

        d_label = f"[bold]source update[/bold] — {what}" + (" [dim][dry-run][/dim]" if getattr(args, "dry_run", False) else "")
        self._print(d_label)
        self._print(f"共 {len(pixiv_works)} 部作品\n")

        downloader = PixivDownloader()
        print_lock = threading.Lock()
        changed = 0
        max_workers = self._max_workers()
        dry_run = getattr(args, "dry_run", False)

        def _update_one(w):
            nonlocal changed
            if self._stop_event.is_set():
                return
            result = source_op.update_single_work_metadata(w, downloader, flags, dry_run)
            if not result:
                return
            with print_lock:
                self._print(f"  [dim]{result['book_id']}[/dim]  {result['title']}")
                self._print(f"    {', '.join(result['changes'])}")
                changed += 1

        from tqdm import tqdm
        total = len(pixiv_works)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_update_one, w): w for w in pixiv_works}
            pbar = tqdm(total=total, desc="更新元数据", unit="个", ncols=80)
            try:
                for future in as_completed(futures):
                    if self._stop_event.is_set():
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    future.result()
                    pbar.update(1)
            except KeyboardInterrupt:
                self._stop_event.set()
                pool.shutdown(wait=False, cancel_futures=True)
            finally:
                pbar.close()

        if self._stop_event.is_set():
            self._print("[dim]更新已中断[/dim]")

        if changed == 0:
            self._print("[dim]所有作品元数据已是最新[/dim]")
        else:
            prefix = "[dim][dry-run] 预览: " if dry_run else ""
            self._print(f"\n{prefix}共更新 {changed} 部作品")

        return 0

    @staticmethod
    def _describe_update_scope(flags: dict, args) -> str:
        if getattr(args, "update_all", False):
            return "全部元数据（含作者名）"
        parts = []
        if flags.get("update_tags"):
            parts.append("标签")
        if flags.get("update_likes"):
            parts.append("点赞")
        if flags.get("update_desc"):
            parts.append("简介")
        if flags.get("update_title"):
            parts.append("标题")
        if flags.get("update_author"):
            parts.append("作者名")
        return "+".join(parts) if parts else "标签+简介+点赞"

    # ── ping ──────────────────────────────────────────────

    def _cmd_ping(self, args: argparse.Namespace) -> int:
        pixiv_url = self.config.get("pixiv", {}).get("base_url", "https://www.pixiv.net")
        pixiv_domain = pixiv_url.replace("https://", "").replace("http://", "").split("/")[0]

        logger.info(f"🚀 开始网络连通性测试 (模式: {args.mode})...")
        if args.mode == "http":
            ok = self._http_ping("Pixiv", pixiv_url, args.timeout)
        else:
            ok = self._icmp_ping("Pixiv", pixiv_domain)

        if ok:
            logger.info("✅ 连通性测试通过！")
            return 0
        logger.warning("⚠️ 连通性问题，请检查网络或代理。")
        return 1

    def _http_ping(self, name: str, url: str, timeout: int) -> bool:
        logger.info(f"🌐 正在测试 {name} ({url})...")
        try:
            start = time.time()
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            proxies = self._get_proxies()
            response = requests.get(url, headers=headers, timeout=timeout, proxies=proxies, stream=True)
            response.close()
            elapsed = (time.time() - start) * 1000
            if response.status_code < 500:
                logger.info(f"✅ {name} 连通成功！延迟: {elapsed:.2f}ms, 状态码: {response.status_code}")
                return True
            logger.warning(f"❌ {name} 连通异常。状态码: {response.status_code}")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"❌ {name} 连接超时 (>{timeout}s)")
            return False
        except requests.exceptions.ProxyError:
            logger.error(f"❌ {name} 代理连接失败，请检查代理配置")
            return False
        except requests.exceptions.SSLError:
            logger.error(f"❌ {name} SSL 证书验证失败")
            return False
        except Exception as e:
            logger.error(f"❌ {name} 连通失败: {type(e).__name__} - {e}")
            return False

    def _icmp_ping(self, name: str, host: str) -> bool:
        import platform
        logger.info(f"📡 正在 ping {name} ({host})...")
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        try:
            result = subprocess.run(['ping', param, '4', host],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                logger.info(f"✅ {name} ping 成功！")
                for line in result.stdout.splitlines()[-3:]:
                    if line.strip():
                        logger.info(f"  {line.strip()}")
                return True
            logger.warning(f"❌ {name} ping 失败。")
            return False
        except Exception as e:
            logger.error(f"❌ {name} 执行 ping 命令出错: {e}")
            return False

    # ── reset ─────────────────────────────────────────────

    def _cmd_reset(self, args: argparse.Namespace) -> int:
        result = source_op.reset_dead_authors(args.target)
        if result["not_found"]:
            self._print(f"[yellow]未找到匹配的注销作者: {args.target}[/yellow]")
            return 1
        if result["reset"] == 0:
            self._print("[dim]没有需要重置的注销作者[/dim]")
            return 0
        for name in result["names"]:
            self._print(f"[green]已重置: {name}[/green]")
        self._print(f"\n共重置 [bold cyan]{result['reset']}[/bold cyan] 位作者")
        return 0

    def _get_proxies(self) -> Optional[dict]:
        proxy = self.config.get("project_settings", {}).get("proxy", "")
        if proxy:
            return {"http": proxy, "https": proxy}
        return None
