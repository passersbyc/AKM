"""交互模式横幅与首次欢迎界面（从旧 core.py 拆出）。"""
import math
from collections import Counter
from src.core.logging import logger


def _console():
    from rich.console import Console
    return Console(stderr=True)


def _render_recommendations(console, db, recent_open, recent_import, recent_download) -> None:
    """猜你喜欢 — TF-IDF + 余弦相似度 + MMR 多样性选择，推荐 8 条。"""
    try:
        from rich.table import Table
        from rich import box
        from src.core.database import short_id
    except ImportError:
        return

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

    # ── 计算全库 TF-IDF：稀有标签权重高，通用标签权重低 ──
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

    # 时间衰减权重：最近打开 ×3，下载 ×2，导入 ×1
    for row in recent_open:
        _feed(row, 3)
    for row in recent_download:
        _feed(row, 2)
    for row in recent_import:
        _feed(row, 1)

    has_interest = any(interest_tags) or any(interest_authors) or any(interest_series) or any(interest_types)

    # ── 兴趣向量归一化（用于余弦相似度） ──
    vec_norm = math.sqrt(
        sum(v * v for v in interest_tags.values())
        + sum(v * v for v in interest_authors.values())
        + sum(v * v for v in interest_series.values())
        + sum(v * v for v in interest_types.values())
    ) or 1.0

    def _build_item_vector(w) -> dict[str, float]:
        """构建作品特征向量（TF-IDF 标签 + 作者 + 系列 + 分类）。"""
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

    # 构建兴趣统一向量
    interest_vec: dict[str, float] = {}
    for tag, val in interest_tags.items():
        interest_vec[f"tag:{tag}"] = val
    for aid, val in interest_authors.items():
        interest_vec[f"author:{aid}"] = float(val)
    for sid, val in interest_series.items():
        interest_vec[f"series:{sid}"] = float(val)
    for ft, val in interest_types.items():
        interest_vec[f"type:{ft}"] = float(val)

    def _cosine_similarity(item_vec: dict[str, float]) -> float:
        """计算作品向量与兴趣向量的余弦相似度。"""
        if not interest_vec or not item_vec:
            return 0.0
        dot = sum(v * interest_vec.get(k, 0.0) for k, v in item_vec.items())
        item_norm = math.sqrt(sum(v * v for v in item_vec.values())) or 1.0
        if item_norm == 0 or vec_norm == 0:
            return 0.0
        return dot / (item_norm * vec_norm)

    def _score_work(w) -> tuple[float, list[str]]:
        """综合评分：余弦相似度为主 + 评分加成 + 新颖度。"""
        item_vec = _build_item_vector(w)
        cos_sim = _cosine_similarity(item_vec)
        reasons: list[str] = []

        # 理由生成（基于最高权重匹配）
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

        # 评分 = 余弦相似度 × 100 + 评分加成 + 收藏加成
        score = cos_sim * 100.0
        if w["favorite"]:
            score += 3.0
            if not reasons:
                reasons.append("收藏")
        score += (w["rating"] or 0) * 0.3
        # 新颖度：未在三栏出现的作品轻微加分
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

    # 统一候选列表：(score, kind, payload, reasons, author_id, series_id)
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
        # 已互动系列降权
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
        return

    # ── 冷启动 fallback：无兴趣画像时按评分/收藏排序 ──
    if not has_interest:
        def _cold_key(c):
            if c[1] == "series":
                name, count = c[2][:2]
                return (count, c[0])
            w = c[2]
            return (w["favorite"] or 0, c[0])
        all_candidates.sort(key=_cold_key, reverse=True)
        picked = all_candidates[:8]
    else:
        # ── MMR (Maximal Marginal Relevance) 多样性选择 ──
        # 避免推荐全是同一作者/系列，平衡相关性与多样性
        all_candidates.sort(key=lambda c: c[0], reverse=True)
        picked: list[tuple[float, str, object, list[str], str, str]] = []
        remaining = list(all_candidates)
        lambda_div = 0.4  # 多样性权重（0=纯相关性，1=纯多样性）

        while remaining and len(picked) < 8:
            best_idx = 0
            best_mmr = -1.0
            for i, cand in enumerate(remaining):
                rel = cand[0]
                # 计算与已选候选的最大相似度（同作者/同系列 = 高相似）
                max_sim = 0.0
                for p in picked:
                    sim = 0.0
                    if cand[4] and cand[4] == p[4]:  # 同作者
                        sim += 0.5
                    if cand[5] and cand[5] == p[5]:  # 同系列
                        sim += 0.5
                    max_sim = max(max_sim, sim)
                mmr = (1 - lambda_div) * rel - lambda_div * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i
            picked.append(remaining.pop(best_idx))

    # ── 渲染 ──
    console.print()
    rec_table = Table(title="[bold bright_magenta]猜你喜欢[/bold bright_magenta]",
                      show_header=False, box=box.SIMPLE_HEAVY, padding=(0, 1),
                      expand=True)
    rec_table.add_column("id", width=11, no_wrap=True)
    rec_table.add_column("title", ratio=1, no_wrap=True, overflow="ellipsis")
    rec_table.add_column("count", width=6, no_wrap=True)
    rec_table.add_column("reason", width=24, no_wrap=True)
    for score, kind, payload, reasons, _, _ in picked:
        reason_str = ""
        if reasons:
            reason_str = "[" + ", ".join(reasons[:2]) + "]"
        if kind == "work":
            w = payload
            sid = short_id(w["id"])
            title = (w["title"] or "")[:20]
            rec_table.add_row(
                f"[cyan]{sid}[/cyan]",
                title,
                "",
                f"[dim]{reason_str}[/dim]" if reason_str else "",
            )
        else:
            name, count, first_id = payload
            name_trunc = (name or "")[:20]
            first_sid = short_id(first_id)
            rec_table.add_row(
                f"[magenta]\u25a3[/magenta] [cyan]{first_sid}[/cyan]",
                f"[bold magenta]{name_trunc}[/bold magenta]",
                f"[dim]{count}本[/dim]",
                f"[dim]{reason_str}[/dim]" if reason_str else "",
            )
    console.print(rec_table)


def show_interactive_banner(prog_name: str) -> None:
    try:
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich.rule import Rule
        from rich import box
        from art import text2art
        from src.core.database import get_db

        console = _console()
        db = get_db()
        total_works = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        total_authors = db.execute("SELECT COUNT(DISTINCT author_id) FROM works").fetchone()[0]
        total_series = db.execute("SELECT COUNT(DISTINCT series_id) FROM works WHERE series_id != ''").fetchone()[0]
        total_fav = db.execute("SELECT COUNT(*) FROM works WHERE favorite = 1").fetchone()[0]

        console.print()
        console.print(Rule(style="bright_cyan"))

        logo = text2art("AKM", font="merlin1")
        logo_text = Text()
        for line in logo.rstrip("\n").split("\n"):
            logo_text.append(line + "\n", style="bold cyan")
        console.print()
        console.print(Align.center(logo_text))

        subtitle = Panel(
            Align.center(Text("作品管理系统  ·  v0.2.0", style="bold bright_white")),
            box=box.HEAVY,
            border_style="bright_cyan",
            padding=(0, 6),
        )
        console.print(Align.center(subtitle))

        console.print()
        stats_line = Text()
        stats_line.append("  作品 ", style="dim")
        stats_line.append(str(total_works), style="bold yellow")
        stats_line.append("    作者 ", style="dim")
        stats_line.append(str(total_authors), style="bold yellow")
        stats_line.append("    系列 ", style="dim")
        stats_line.append(str(total_series), style="bold yellow")
        stats_line.append("    收藏 ", style="dim")
        stats_line.append(str(total_fav), style="bold yellow")
        console.print(Align.center(stats_line))

        # ── 最近活动三栏 ──
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

        if recent_open or recent_import or recent_download:
            console.print()
            activity = Table(show_header=True, header_style="bold bright_cyan",
                             box=box.SIMPLE_HEAVY, padding=(0, 1), expand=True)
            activity.add_column("最近打开", style="green", ratio=1)
            activity.add_column("最近导入", style="yellow", ratio=1)
            activity.add_column("最近下载", style="blue", ratio=1)

            def _fmt_open(row):
                if not row:
                    return "[dim]无[/dim]"
                from src.core.database import short_id
                sid = short_id(row["work_id"])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            def _fmt_import(row):
                if not row:
                    return "[dim]无[/dim]"
                from src.core.database import short_id
                sid = short_id(row["id"])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            def _fmt_download(row):
                if not row:
                    return "[dim]无[/dim]"
                from src.core.database import short_id
                sid = short_id(row["id"])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            for i in range(5):
                o = recent_open[i] if i < len(recent_open) else None
                im = recent_import[i] if i < len(recent_import) else None
                dl = recent_download[i] if i < len(recent_download) else None
                activity.add_row(_fmt_open(o), _fmt_import(im), _fmt_download(dl))
            console.print(activity)

            # ── 猜你喜欢（推荐） ──
            _render_recommendations(console, db, recent_open, recent_import, recent_download)

        console.print()
        shortcuts = Table(show_header=False, box=box.SIMPLE, padding=(0, 3))
        shortcuts.add_column(width=24)
        shortcuts.add_column(width=24)
        shortcuts.add_column(width=24)
        shortcuts.add_row(
            "[bold cyan]list[/]  [dim]查看作品[/]",
            "[bold cyan]search[/]  [dim]搜索[/]",
            "[bold cyan]stats[/]  [dim]仪表盘[/]",
        )
        shortcuts.add_row(
            "[bold cyan]import[/]  [dim]导入[/]",
            "[bold cyan]open[/]  [dim]打开[/]",
            "[bold cyan]follow[/]  [dim]关注/同步[/]",
        )
        console.print(Align.center(shortcuts))

        console.print()
        tip = Panel(
            Align.center(
                Text("输入 ", style="dim")
                + Text("help", style="bold bright_white")
                + Text(" 查看命令  |  ", style="dim")
                + Text("输入 ", style="dim")
                + Text("exit", style="bold bright_white")
                + Text(" 退出", style="dim")
            ),
            box=box.SIMPLE,
            border_style="bright_black",
            padding=(0, 4),
        )
        console.print(Align.center(tip))
        console.print(Rule(style="bright_cyan"))
        console.print()
    except Exception:
        print(f"\n欢迎使用 {prog_name} 交互模式。\n输入 'help' 或 '?' 查看命令。输入 'exit' 退出。\n")


def show_welcome(prog_name: str) -> None:
    try:
        from src.core.database import get_db
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        if total > 0:
            return
    except Exception:
        pass

    try:
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich.columns import Columns
        from rich.align import Align
        from rich.rule import Rule
        from rich import box
        from art import text2art

        console = _console()
        logo = text2art("AKM", font="alpha")
        lines = [l for l in logo.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        logo_text = Text()
        for i, line in enumerate(lines):
            logo_text.append(line + ("\n" if i < len(lines) - 1 else ""), style="bold cyan")
        console.print(Align.center(logo_text))

        subtitle = Panel(
            Align.center(Text("作 品 管 理 系 统  ·  v0.2.0", style="bold")),
            box=box.HEAVY,
            border_style="bright_cyan",
            padding=(0, 4),
        )
        console.print(Align.center(subtitle))
        console.print()

        features = [
            Panel(
                Text("作品管理\n", style="bold yellow")
                + Text("导入 / 搜索 / 编辑\n分类 / 标签 / 评分", style="dim"),
                box=box.ROUNDED, border_style="yellow", padding=(1, 2),
            ),
            Panel(
                Text("多格式支持\n", style="bold magenta")
                + Text("txt · epub · pdf\n漫画 · 音乐 · 电影", style="dim"),
                box=box.ROUNDED, border_style="magenta", padding=(1, 2),
            ),
            Panel(
                Text("在线订阅\n", style="bold blue")
                + Text("follow / pull\nPixiv 作者追踪", style="dim"),
                box=box.ROUNDED, border_style="blue", padding=(1, 2),
            ),
            Panel(
                Text("智能检索\n", style="bold green")
                + Text("正则搜索 · 多字段\n收藏 · 作者 · 系列", style="dim"),
                box=box.ROUNDED, border_style="green", padding=(1, 2),
            ),
        ]
        console.print(Columns(features, equal=True, padding=(0, 1)))

        console.print()
        console.print(Rule("快速上手", style="bold bright_cyan"))
        cmd_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2),
                          expand=True, leading=1)
        cmd_table.add_column("cmd", style="bold cyan", width=35)
        cmd_table.add_column("desc", style="white")
        for cmd, desc in [
            ("akm ls", "查看库中所有作品"),
            ("akm search <关键词>", "搜索作品"),
            ("akm open <作品ID>", "在应用中打开作品"),
            ("akm stats", "库统计概览"),
            ("akm import <文件路径>", "导入新文件到库中"),
            ("akm follow <Pixiv URL>", "关注 Pixiv 作者"),
        ]:
            cmd_table.add_row(f"  $ {cmd}", desc)
        console.print(Panel(cmd_table, box=box.ROUNDED, border_style="bright_black"))
        console.print()

        footer = Text()
        footer.append("输入 ", style="dim")
        footer.append("akm --help", style="bold bright_white")
        footer.append(" 查看完整命令  |  输入 ", style="dim")
        footer.append("akm", style="bold bright_white")
        footer.append(" 进入交互模式", style="dim")
        console.print(Align.center(footer))
        console.print()
    except Exception:
        print(f"\n欢迎使用 {prog_name}！输入 --help 查看帮助。\n")
