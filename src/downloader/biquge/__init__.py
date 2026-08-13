"""笔趣阁下载器 — 下载小说并导入库中。"""
import re
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.downloader.base import BaseDownloader
from src.downloader.biquge.client import BiqugeClient
from src.core.logging import get_logger

logger = get_logger("akm.biquge")


class BiqugeDownloader(BaseDownloader):
    name = "biquge"
    url_patterns = [
        r"bqg\d+\.xyz",
        r"biquge|笔趣阁",
    ]

    def __init__(self):
        super().__init__()
        self._load_base_config()
        self.client = BiqugeClient(timeout=15)
        self._load_existing_sources()
        self._max_chapters = 0  # 0 = 全部

    def set_max_chapters(self, n: int):
        self._max_chapters = n

    # ── 抽象方法实现 ──

    def process_url(self, urls: Union[str, List[str]], mode: str = "both") -> Dict[str, int]:
        if isinstance(urls, str):
            urls = [urls]

        stats = {"success": 0, "failed": 0, "skipped": 0}
        for url in urls:
            book_id = self._extract_book_id(url)
            if not book_id:
                logger.error("无法解析书籍 ID: %s", url)
                stats["failed"] += 1
                self._apply_queue_result(url, "failed", "404")
                continue
            try:
                r = self._download_book(book_id, url)
                if r == "ok":
                    stats["success"] += 1
                    self._apply_queue_result(url, "success")
                elif r == "skip":
                    stats["skipped"] += 1
                    self._apply_queue_result(url, "skipped")
                else:
                    stats["failed"] += 1
                    self._apply_queue_result(url, "failed", r)
            except Exception as e:
                logger.error("下载失败: %s - %s", url, e)
                stats["failed"] += 1
                self._apply_queue_result(url, "failed", str(e))
        return stats

    def get_author_info(self, url: str) -> Optional[tuple[str, int]]:
        book_id = self._extract_book_id(url)
        if not book_id:
            return None
        try:
            info = self.client.get_book(book_id)
            return info.get("author", ""), 0
        except Exception:
            return None

    def extract_uid(self, url: str) -> str:
        return str(self._extract_book_id(url) or "")

    # ── 内部方法 ──

    def _extract_book_id(self, url: str) -> Optional[int]:
        m = re.search(r"/book/(\d+)", url)
        if m:
            return int(m.group(1))
        m = re.search(r"[?&]id=(\d+)", url)
        if m:
            return int(m.group(1))
        return None

    def _download_book(self, book_id: int, source_url: str) -> str:
        # 1. 元数据
        logger.info("获取书籍信息 #%d ...", book_id)
        book = self.client.get_book(book_id)
        title = book.get("title", f"book_{book_id}")
        author = book.get("author", "佚名")
        intro = book.get("intro", "")
        sortname = book.get("sortname", "")
        # dirid 键可能存在但为 None，需兜底回退到 book_id
        dir_id = book.get("dirid") or str(book_id)

        if self._is_source_in_manifest(source_url):
            logger.info("已经有了，跳过～: %s", title)
            return "skip"

        # 2. 章节列表
        logger.info("获取章节列表 ...")
        all_chapters = self.client.get_booklist(int(dir_id))
        total_books = len(all_chapters)
        chapters = all_chapters
        if self._max_chapters > 0 and self._max_chapters < total_books:
            chapters = all_chapters[:self._max_chapters]
        total = len(chapters)
        logger.info("共 %d 章 (实际下载 %d 章)", total_books, total)

        if not chapters:
            logger.error("章节列表为空")
            return "fail"

        # 3. 并发下载章节（可取消：取消时立即停止提交并等待当前批完成）
        logger.info("下载 %d 章 (并发 ×8) ...", total)
        chapter_contents = [""] * total
        chapter_counts = {"success": 0, "failed": 0, "skipped": 0}

        from src.core.progress import make_progress, advance
        progress, main_task, counts_task = make_progress(
            chapter_counts, "下载章节", total=total)
        progress.start()
        pool = ThreadPoolExecutor(max_workers=8)
        try:
            futures = {pool.submit(self._fetch_chapter, book_id, i + 1): i for i in range(total)}
            for f in as_completed(futures):
                self._check_stop()
                idx = futures[f]
                try:
                    chapter_contents[idx] = f.result()
                    chapter_counts["success"] += 1
                except Exception as e:
                    chapter_contents[idx] = f"[下载失败: {e}]"
                    chapter_counts["failed"] += 1
                advance(progress, main_task, counts_task)
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            progress.stop()
            pool.shutdown(wait=True, cancel_futures=True)

        # 4. 组装文本
        self._check_stop()
        parts = [title, "", f"作者：{author}", f"分类：{sortname}", "", intro, "", "—" * 40, ""]
        for name, content in zip(chapters, chapter_contents):
            parts.append(f"\n{name}\n")
            parts.append(str(content))
            parts.append("")

        full_text = "\n".join(parts)
        tmp = Path(tempfile.mktemp(suffix=".txt"))
        tmp.write_text(full_text, encoding="utf-8")
        logger.info("生成文件: %.1f KB", len(full_text) / 1024)

        # 5. 导入
        logger.info("导入库中 ...")
        tags = [sortname, "小说", "笔趣阁"] if sortname else ["小说", "笔趣阁"]

        result = self.import_download(
            file_path=tmp,
            work_url=source_url,
            metadata_info={
                "title": title,
                "author": author,
                "tags": tags,
                "description": intro,
                "source_status": "ok",
            },
        )

        if result[1] == "ok":
            logger.info("导入成功: %s (%d章)", title, total)
            return "ok"
        else:
            logger.error("导入失败: %s - %s", title, result[1])
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return "fail"

    def _fetch_chapter(self, book_id: int, chapter_id: int) -> str:
        self._check_stop()
        try:
            ch = self.client.get_chapter(book_id, chapter_id)
            return ch.get("txt", "")
        except Exception as e:
            logger.warning("第%d章失败: %s", chapter_id, e)
            return ""
