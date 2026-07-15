"""
src/cli/commands/rank.py
排行榜命令：根据点赞量对作者、系列或作品进行排行
"""

import argparse
import json
from typing import Dict, List, Tuple
from pathlib import Path
from src.cli.core import BaseCommand
from src.cli.downplugin.pixiv import PixivDownloader
from src.cli.downplugin.pixiv.extractors import extract_pixiv_id
from src.core.logging import logger
from src.core.config import get_project_root
from src.operations import get_pixiv_entries
import requests
import time
import re
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

console = Console()

class RankCommand(BaseCommand):
    """
    排行榜命令实现类，支持按作者、系列或作品进行点赞量排行
    """
    
    def __init__(self) -> None:
        super().__init__()
        self.pixiv_downloader = PixivDownloader()
        # 创建一个额外的CSV文件用于存储点赞量数据
        self.likes_data_path = get_project_root() / "pixiv_likes_data.json"
        # 黑名单文件用于存储无效的作品ID
        self.blacklist_path = get_project_root() / "pixiv_blacklist.json"
        
    @property
    def name(self) -> str:
        """
        命令名称：rank
        """
        return "rank"

    @property
    def description(self) -> str:
        """
        命令描述：根据点赞量对Pixiv作品进行排行
        """
        return "根据点赞量对Pixiv作品进行排行（仅支持Pixiv作品）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        """
        配置 rank 命令的参数。
        
        参数：
        - -a, --author: 获取作者下所有作品的点赞量并排行
        - -s, --series: 获取系列作品下所有作品的点赞量平均值并排行
        - -w, --work: 获取所有单个作品的点赞量并排行
        - -l, --like: 获取/更新所有作品点赞量并持久化
        """
        parser.add_argument(
            "-a", "--author",
            action="store_true",
            help="获取作者点赞量排行"
        )
        parser.add_argument(
            "-s", "--series",
            action="store_true",
            help="获取系列点赞量排行"
        )
        parser.add_argument(
            "-w", "--work",
            action="store_true",
            help="获取作品点赞量排行"
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-li", "--like-incremental",
            action="store_true",
            help="增量更新：仅获取/更新未记录的作品点赞量并持久化"
        )
        group.add_argument(
            "-lc", "--like-comprehensive",
            action="store_true",
            help="全面更新：获取/更新所有作品点赞量并持久化（覆盖已有数据）"
        )
        # 保持原有的 -l 参数作为增量更新的别名，以维持向后兼容性
        group.add_argument(
            "-l", "--like",
            action="store_true",
            help="获取/更新所有作品点赞量并持久化（默认为增量更新）"
        )
        parser.add_argument(
            "-n", "--number",
            type=int,
            default=20,
            help="指定显示的排名数量，默认为 20"
        )
        parser.add_argument(
            "-t", "--type",
            type=str,
            choices=['illust', 'novel'],
            help="根据作品类型过滤，可选值为 'illust' (插画/漫画) 或 'novel' (小说)"
        )

    def execute(self, args: argparse.Namespace) -> int:
        """
        执行排行榜逻辑。
        """
        # 检查是否至少提供了一个参数
        if not any([args.author, args.series, args.work, args.like, args.like_incremental, args.like_comprehensive]):
            logger.error("❌ 请至少指定一个参数：-a (作者排行), -s (系列排行), -w (作品排行), -li (增量更新), -lc (全面更新), -l (更新点赞量)")
            return 1

        # 只处理Pixiv来源的作品
        pixiv_entries = self._get_pixiv_entries()
        if not pixiv_entries:
            logger.warning("⚠️  没有找到Pixiv来源的作品")
            return 0

        # 如果指定了更新点赞量参数，则更新点赞量数据
        if args.like or args.like_incremental:  # 默认行为或显式增量更新
            logger.info("🔄 正在进行增量更新（仅更新未记录的作品点赞量）...")
            self._update_likes_data(pixiv_entries, incremental=True)
            logger.info("✅ 增量更新完成")
        elif args.like_comprehensive:
            logger.info("🔄 正在进行全面更新（更新所有作品点赞量）...")
            self._update_likes_data(pixiv_entries, incremental=False)
            logger.info("✅ 全面更新完成")

        # 加载点赞量数据
        likes_data = self._load_likes_data()

        # 根据参数执行相应的排行功能
        limit = args.number
        work_type = args.type
        
        if args.author:
            if work_type:
                logger.info(f"📊 正在生成作者点赞量排行 (类型: {work_type})...")
            else:
                logger.info("📊 正在生成作者点赞量排行...")
            self._rank_by_author(pixiv_entries, likes_data, limit, work_type)

        if args.series:
            if work_type:
                logger.info(f"📊 正在生成系列点赞量排行 (类型: {work_type})...")
            else:
                logger.info("📊 正在生成系列点赞量排行...")
            self._rank_by_series(pixiv_entries, likes_data, limit, work_type)

        if args.work:
            if work_type:
                logger.info(f"📊 正在生成作品点赞量排行 (类型: {work_type})...")
            else:
                logger.info("📊 正在生成作品点赞量排行...")
            self._rank_by_work(pixiv_entries, likes_data, limit, work_type)

        return 0

    @staticmethod
    def extract_work_id(entry: dict) -> str:
        source_url = entry.get('来源', '')
        if source_url and "pixiv.net" in source_url:
            pid = extract_pixiv_id(source_url)
            if pid:
                return pid

        file_path = entry.get('文件路径', '')
        if file_path:
            filename = Path(file_path).name
            id_match = re.search(r'(?:_|^|\.)(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip|epub)$', filename, re.IGNORECASE)
            if not id_match:
                id_match = re.search(r'(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip|epub)$', filename, re.IGNORECASE)
            if id_match:
                return id_match.group(1)
        return ""

    def _extract_work_id_from_url(self, url: str) -> str:
        """
        向下兼容的方法，从Pixiv URL中提取作品ID
        """
        return self.extract_work_id({'来源': url})

    def _get_pixiv_entries(self) -> List[Dict]:
        try:
            return get_pixiv_entries()
        except Exception as e:
            logger.error(f"❌ 读取作品数据时出错: {e}")
        return []

    def _load_likes_data(self) -> Dict:
        """
        从JSON文件加载点赞量数据
        """
        if self.likes_data_path.exists():
            try:
                with open(self.likes_data_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ 加载点赞量数据失败: {e}")
                return {}
        return {}

    def _save_likes_data(self, likes_data: Dict) -> None:
        """
        将点赞量数据保存到JSON文件
        """
        try:
            with open(self.likes_data_path, 'w', encoding='utf-8') as f:
                json.dump(likes_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 保存点赞量数据失败: {e}")

    def _load_blacklist(self) -> set:
        """
        从JSON文件加载黑名单
        """
        if self.blacklist_path.exists():
            try:
                with open(self.blacklist_path, 'r', encoding='utf-8') as f:
                    blacklist_data = json.load(f)
                    return set(blacklist_data)
            except Exception as e:
                logger.error(f"❌ 加载黑名单失败: {e}")
                return set()
        return set()

    def _save_blacklist(self, blacklist: set) -> None:
        """
        将黑名单保存到JSON文件
        """
        try:
            with open(self.blacklist_path, 'w', encoding='utf-8') as f:
                json.dump(list(blacklist), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 保存黑名单失败: {e}")

    def _update_likes_data(self, entries: List[Dict], incremental: bool = True) -> None:
        """
        更新点赞量数据（多线程加速版，带进度预估）
        
        参数:
        - entries: 作品条目列表
        - incremental: 是否为增量更新模式(True)或全面更新模式(False)
        """
        import concurrent.futures
        import threading
        
        likes_data = self._load_likes_data()
        # 加载黑名单
        blacklist = self._load_blacklist()
        
        # 1. 收集所有需要更新的任务
        tasks = []
        for entry in entries:
            source_url = entry.get('来源', '')
            work_id = self.extract_work_id(entry)
            
            if work_id and work_id not in blacklist:
                # 根据更新模式决定是否添加到任务列表
                if incremental:
                    # 增量更新：只处理未记录的作品
                    if work_id not in likes_data:
                        tasks.append((work_id, source_url))
                else:
                    # 全面更新：处理所有作品（除了黑名单中的）
                    tasks.append((work_id, source_url))
                
        total_tasks = len(tasks)
        if total_tasks == 0:
            logger.info("✅ 所有作品点赞量已是最新，无需更新。")
            return
            
        logger.info("🔄 共有 %d 个作品需要获取点赞量，启动多线程加速...", total_tasks)
        
        updated_count = 0
        failed_count = 0
        data_lock = threading.Lock()
        
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            task_id = progress.add_task("[cyan]更新点赞量...", total=total_tasks)
            
            def process_task(task):
                nonlocal updated_count, failed_count
                work_id, source_url = task
                try:
                    # 优先使用来源 URL，如果没有则退回到构造的插画 URL
                    work_url = source_url if source_url and 'pixiv' in source_url else f"https://www.pixiv.net/artworks/{work_id}"
                    info = self.pixiv_downloader.get_info(work_url)
                    
                    with data_lock:
                        if info:
                            like_count = info.get('like_count', 0)
                            title = info.get('title', '')
                            likes_data[work_id] = {
                                'like_count': like_count,
                                'title': title,
                                'author': info.get('author', ''),
                                'updated_at': time.time()
                            }
                            updated_count += 1
                            display_title = title[:20] + "..." if len(title) > 20 else title
                            progress.update(task_id, advance=1, description=f"[cyan]📝 《{display_title}》: {like_count}赞")
                        else:
                            failed_count += 1
                            # 检查错误是否与404相关（作品不存在），如果是则加入黑名单
                            # 401等权限错误不应加入黑名单，因为可能是临时的权限问题
                            error_msg = str(self.pixiv_downloader.get_last_error()) if hasattr(self.pixiv_downloader, 'get_last_error') else ""
                            if ("404" in error_msg or "找不到这个页面" in error_msg or "Not Found" in error_msg) and "401" not in error_msg:
                                # 将作品ID加入黑名单
                                blacklist.add(work_id)
                                logger.info("📝 作品 %s 已加入黑名单（404错误）", work_id)
                            elif "401" in error_msg:
                                logger.warning("⚠️  作品 %s 遇到权限错误（401），请检查Cookie配置", work_id)
                            
                            # 显示作品ID和原始网址，便于排查问题
                            original_url = source_url if source_url and 'pixiv' in source_url else f"https://www.pixiv.net/artworks/{work_id}"
                            progress.update(task_id, advance=1, description=f"[red]⚠️ 无法获取 {work_id} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   0% {original_url}")
                except Exception as e:
                    with data_lock:
                        failed_count += 1
                        # 检查错误是否与404相关（作品不存在），如果是则加入黑名单
                    # 401等权限错误不应加入黑名单，因为可能是临时的权限问题
                    error_msg = str(e)
                    if ("404" in error_msg or "找不到这个页面" in error_msg or "Not Found" in error_msg) and "401" not in error_msg:
                        # 将作品ID加入黑名单
                        blacklist.add(work_id)
                        logger.info("📝 作品 %s 已加入黑名单（404错误）", work_id)
                    elif "401" in error_msg:
                        logger.warning("⚠️  作品 %s 遇到权限错误（401），请检查Cookie配置", work_id)
                    
                    # 显示作品ID和原始网址，便于排查问题
                    original_url = source_url if source_url and 'pixiv' in source_url else f"https://www.pixiv.net/artworks/{work_id}"
                    progress.update(task_id, advance=1, description=f"[red]❌ 获取 {work_id} 失败 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   0% {original_url}")
    
            try:
                # 使用配置中的并发数，如果没有则默认为4
                max_workers = getattr(self.pixiv_downloader, 'max_workers', 4)
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(process_task, task) for task in tasks]
                    for future in concurrent.futures.as_completed(futures):
                        future.result() # 获取异常，并允许被 KeyboardInterrupt 打断
            except KeyboardInterrupt:
                logger.warning("\n⚠️  用户中断了更新操作，正在保存已获取的数据...")
                # 尝试取消尚未开始的任务
                for future in futures:
                    future.cancel()
            finally:
                self._save_likes_data(likes_data)
                # 保存更新后的黑名单
                self._save_blacklist(blacklist)
                logger.info("✅ 共成功更新了 %d 个作品的点赞量数据，失败 %d 个", updated_count, failed_count)
                logger.info("📝 黑名单已更新，共包含 %d 个无效作品ID", len(blacklist))

    def _rank_by_author(self, entries: List[Dict], likes_data: Dict, limit: int = 20, work_type: str = None) -> List[Tuple[str, Dict]]:
        """
        按作者进行点赞量排行
        """
        author_likes = {}
        
        for entry in entries:
            author = entry.get('作者', '未知作者')
            
            # 优先从来源URL中提取作品ID
            source_url = entry.get('来源', '')
            work_id = self._extract_work_id_from_url(source_url)
            
            if not work_id:
                # 如果从URL中无法提取ID，则尝试从文件路径中提取
                file_path = entry.get('文件路径', '')
                if file_path:
                    # 从文件路径中提取作品ID
                    file_obj = Path(file_path)
                    filename = file_obj.name
                    id_match = re.search(r'(?:_|^|\.)(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip)$', filename, re.IGNORECASE)
                    if not id_match:
                        id_match = re.search(r'(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip)$', filename, re.IGNORECASE)
                    
                    if id_match:
                        work_id = id_match.group(1)
            
            if work_id:
                # 如果指定了类型过滤，检查作品类型
                if work_type:
                    # 根据 URL 结构判断类型
                    is_novel = 'novel' in source_url
                    if (work_type == 'novel' and not is_novel) or (work_type == 'illust' and is_novel):
                        continue
                        
                like_count = likes_data.get(work_id, {}).get('like_count', 0)
                
                if author not in author_likes:
                    author_likes[author] = {'total_likes': 0, 'work_count': 0, 'works': []}
                
                author_likes[author]['total_likes'] += like_count
                author_likes[author]['work_count'] += 1
                author_likes[author]['works'].append({
                    'title': likes_data.get(work_id, {}).get('title', f'作品_{work_id}'),
                    'like_count': like_count
                })
        
        # 按总点赞量排序
        sorted_authors = sorted(author_likes.items(), key=lambda x: x[1]['total_likes'], reverse=True)
        
        # 使用 rich 渲染表格
        table = Table(title="🏆 作者点赞量排行", show_header=True, header_style="bold magenta")
        table.add_column("排名", justify="center", style="cyan", no_wrap=True)
        table.add_column("作者", style="green")
        table.add_column("总点赞量", justify="right", style="yellow")
        table.add_column("作品数", justify="right", style="blue")
        table.add_column("平均点赞量", justify="right", style="red")
        
        for idx, (author, data) in enumerate(sorted_authors, 1):
            avg_likes = data['total_likes'] / data['work_count'] if data['work_count'] > 0 else 0
            
            # 显示该作者最受欢迎的几个作品，作为作者名的一部分
            top_works = sorted(data['works'], key=lambda x: x['like_count'], reverse=True)[:3]
            works_str = "\n".join([f"  └─ {w['title'][:30]}... ({w['like_count']}赞)" if len(w['title']) > 30 else f"  └─ {w['title']} ({w['like_count']}赞)" for w in top_works])
            author_display = f"[bold]{author}[/bold]\n[dim]{works_str}[/dim]"
            
            table.add_row(
                str(idx),
                author_display,
                str(data['total_likes']),
                str(data['work_count']),
                f"{avg_likes:.1f}"
            )
            
            if idx >= limit:
                break
        
        console.print(table)
        return sorted_authors[:limit]

    def _rank_by_series(self, entries: List[Dict], likes_data: Dict, limit: int = 20, work_type: str = None) -> List[Tuple[str, Dict]]:
        """
        按系列进行点赞量平均值排行
        """
        series_likes = {}
        
        for entry in entries:
            series = entry.get('系列', '无系列')
            if not series or series.lower() in ['none', 'null', '无', '']:
                series = '无系列'
                
            # 优先从来源URL中提取作品ID
            source_url = entry.get('来源', '')
            work_id = self._extract_work_id_from_url(source_url)
            
            if not work_id:
                # 如果从URL中无法提取ID，则尝试从文件路径中提取
                file_path = entry.get('文件路径', '')
                if file_path:
                    # 从文件路径中提取作品ID
                    file_obj = Path(file_path)
                    filename = file_obj.name
                    id_match = re.search(r'(?:_|^|\.)(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip)$', filename, re.IGNORECASE)
                    if not id_match:
                        id_match = re.search(r'(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip)$', filename, re.IGNORECASE)
                    
                    if id_match:
                        work_id = id_match.group(1)
            
            if work_id:
                # 如果指定了类型过滤，检查作品类型
                if work_type:
                    is_novel = 'novel' in source_url
                    if (work_type == 'novel' and not is_novel) or (work_type == 'illust' and is_novel):
                        continue
                        
                like_count = likes_data.get(work_id, {}).get('like_count', 0)
                
                if series not in series_likes:
                    series_likes[series] = {'total_likes': 0, 'work_count': 0, 'works': []}
                
                series_likes[series]['total_likes'] += like_count
                series_likes[series]['work_count'] += 1
                series_likes[series]['works'].append({
                    'title': likes_data.get(work_id, {}).get('title', f'作品_{work_id}'),
                    'like_count': like_count
                })
        
        # 计算平均点赞量并排序
        series_avg_likes = {}
        for series, data in series_likes.items():
            if data['work_count'] > 0:
                series_avg_likes[series] = {
                    'avg_likes': data['total_likes'] / data['work_count'],
                    'total_likes': data['total_likes'],
                    'work_count': data['work_count'],
                    'works': data['works']
                }
        
        sorted_series = sorted(series_avg_likes.items(), key=lambda x: x[1]['avg_likes'], reverse=True)
        
        table = Table(title="🏆 系列平均点赞量排行", show_header=True, header_style="bold magenta")
        table.add_column("排名", justify="center", style="cyan", no_wrap=True)
        table.add_column("系列", style="green")
        table.add_column("平均点赞量", justify="right", style="red")
        table.add_column("总点赞量", justify="right", style="yellow")
        table.add_column("作品数", justify="right", style="blue")
        
        for idx, (series, data) in enumerate(sorted_series, 1):
            avg_likes = data.get('avg_likes', 0)
            
            top_works = sorted(data['works'], key=lambda x: x['like_count'], reverse=True)[:3]
            works_str = "\n".join([f"  └─ {w['title'][:30]}... ({w['like_count']}赞)" if len(w['title']) > 30 else f"  └─ {w['title']} ({w['like_count']}赞)" for w in top_works])
            series_display = f"[bold]{series}[/bold]\n[dim]{works_str}[/dim]"
                
            table.add_row(
                str(idx),
                series_display,
                f"{avg_likes:.1f}",
                str(data['total_likes']),
                str(data['work_count'])
            )
            
            if idx >= limit:
                break
        
        console.print(table)
        return sorted_series[:limit]

    def _rank_by_work(self, entries: List[Dict], likes_data: Dict, limit: int = 20, work_type: str = None) -> List[Dict]:
        """
        按单个作品进行点赞量排行
        """
        works = []
        
        for entry in entries:
            # 优先从来源URL中提取作品ID
            source_url = entry.get('来源', '')
            work_id = self._extract_work_id_from_url(source_url)
            
            if not work_id:
                # 如果从URL中无法提取ID，则尝试从文件路径中提取
                file_path = entry.get('文件路径', '')
                if file_path:
                    # 从文件路径中提取作品ID
                    file_obj = Path(file_path)
                    filename = file_obj.name
                    id_match = re.search(r'(?:_|^|\.)(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip)$', filename, re.IGNORECASE)
                    if not id_match:
                        id_match = re.search(r'(\d{6,})\.(?:jpg|jpeg|png|gif|webp|pdf|zip)$', filename, re.IGNORECASE)
                    
                    if id_match:
                        work_id = id_match.group(1)
            
            if work_id:
                # 如果指定了类型过滤，检查作品类型
                if work_type:
                    is_novel = 'novel' in source_url
                    if (work_type == 'novel' and not is_novel) or (work_type == 'illust' and is_novel):
                        continue
                        
                like_count = likes_data.get(work_id, {}).get('like_count', 0)
                
                works.append({
                    'id': work_id,
                    'title': likes_data.get(work_id, {}).get('title', f'作品_{work_id}'),
                    'author': likes_data.get(work_id, {}).get('author', entry.get('作者', '未知作者')),
                    'like_count': like_count
                })
        
        # 按点赞量排序
        sorted_works = sorted(works, key=lambda x: x['like_count'], reverse=True)
        
        table = Table(title="🏆 作品点赞量排行", show_header=True, header_style="bold magenta")
        table.add_column("排名", justify="center", style="cyan", no_wrap=True)
        table.add_column("作品ID", style="blue")
        table.add_column("标题", style="green")
        table.add_column("作者", style="yellow")
        table.add_column("点赞量", justify="right", style="red")
        
        for idx, work in enumerate(sorted_works, 1):
            table.add_row(
                str(idx),
                work['id'],
                work['title'],
                work['author'],
                str(work['like_count'])
            )
            
            if idx >= limit:
                break
        
        console.print(table)
        return sorted_works[:limit]