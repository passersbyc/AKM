"""prompt_toolkit 自动补全 — verb→noun 两级 + 动态作品名/作者名/标签补全。"""
import argparse

from src.core.logging import logger


def build_completer(app):
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.styles import Style
        from prompt_toolkit.document import Document
    except ImportError:
        logger.warning("未安装 prompt_toolkit。自动补全已禁用。")
        return None

    class DynamicCompleter(Completer):
        def __init__(self, app):
            self.app = app
            self.verbs: list[str] = list(app._commands.keys()) + ["exit", "quit", "help"]
            self.verb_nouns: dict[str, list[str]] = {}
            self.verb_options: dict[str, list[str]] = {}
            self.noun_options: dict[tuple[str, str], list[str]] = {}
            self._init_options()

        def _init_options(self):
            for verb, command in self.app._commands.items():
                parser = self.app._verb_parsers.get(verb)
                if parser is None:
                    continue
                own_opts = []
                for action in parser._actions:
                    own_opts.extend(action.option_strings)
                self.verb_options[verb] = own_opts
                nouns = getattr(command, "nouns", []) or []
                if nouns:
                    self.verb_nouns[verb] = nouns
                    for noun in nouns:
                        sub_parser = self.app._noun_parsers.get((verb, noun))
                        sub_opts = []
                        if sub_parser is not None:
                            for action in sub_parser._actions:
                                sub_opts.extend(action.option_strings)
                        self.noun_options[(verb, noun)] = sub_opts

        def _query_works(self, prefix: str, limit: int = 15) -> list[tuple[str, str]]:
            """查询作品：标题包含 + 短ID前缀匹配，返回 [(insert_text, display), ...]。"""
            try:
                from src.core.database import get_db, short_id
                db = get_db()
                results: list[tuple[str, str]] = []
                seen: set[str] = set()

                def _add(work_id: str, title: str) -> None:
                    sid = short_id(work_id)
                    if sid not in seen:
                        seen.add(sid)
                        display = f"{sid}  {title}"
                        results.append((sid, display))

                # 短 ID 前缀匹配（如 n.1, c.3.0）
                if prefix and prefix[0] in "ncmfi0":
                    clean = prefix.replace(".", "")
                    if clean:
                        rows = db.execute(
                            "SELECT id, title FROM works WHERE id LIKE ? LIMIT ?",
                            (f"{clean}%", limit),
                        ).fetchall()
                        for r in rows:
                            _add(r["id"], r["title"])

                # 标题包含匹配
                if prefix:
                    rows = db.execute(
                        "SELECT id, title FROM works WHERE title LIKE ? LIMIT ?",
                        (f"%{prefix}%", limit),
                    ).fetchall()
                    for r in rows:
                        _add(r["id"], r["title"])

                # 无前缀时列出最近作品
                if not prefix:
                    rows = db.execute(
                        "SELECT id, title FROM works ORDER BY imported_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    for r in rows:
                        _add(r["id"], r["title"])

                return results[:limit]
            except Exception:
                return []

        def _query_authors(self, prefix: str, limit: int = 15) -> list[str]:
            try:
                from src.cli.matcher import list_author_names
                names = list_author_names(prefix, limit)
                return [n for _, n in names]
            except Exception:
                return []

        def _query_labels(self, prefix: str, limit: int = 15) -> list[str]:
            try:
                from src.core.database import get_db
                db = get_db()
                all_tags: set[str] = set()
                for r in db.execute("SELECT tags FROM works WHERE tags LIKE ? LIMIT 200",
                                    (f"%{prefix}%",)).fetchall():
                    for t in (r["tags"] or "").split(","):
                        t = t.strip()
                        if t and (not prefix or prefix in t):
                            all_tags.add(t)
                return sorted(all_tags)[:limit]
            except Exception:
                return []

        def get_completions(self, document: Document, complete_event):
            text = document.text_before_cursor.lstrip()
            words = text.split()
            word_before = document.get_word_before_cursor(WORD=True)

            # 空输入：补全 verb
            if not words:
                for verb in self.verbs:
                    if verb.startswith(text):
                        yield Completion(verb, start_position=-len(text))
                return

            first = words[0]

            # 第一个词未输入完：补全 verb
            if len(words) == 1 and " " not in text:
                for verb in self.verbs:
                    if verb.startswith(text):
                        yield Completion(verb, start_position=-len(text))
                return

            # exit/help/quit 无后续补全
            if first in ("exit", "quit", "help"):
                return

            # 非已知 verb
            if first not in self.app._commands:
                return

            # 有 noun 的 verb：第二词补全 noun
            if first in self.verb_nouns and (
                len(words) == 1 or (len(words) == 2 and not text.endswith(" "))
            ):
                # 先补全 noun
                noun_matched = False
                for noun in self.verb_nouns[first]:
                    if noun.startswith(word_before):
                        yield Completion(noun, start_position=-len(word_before))
                        noun_matched = True
                # 选项仅在 -- 开头时补全
                if word_before.startswith("-"):
                    for opt in self.verb_options[first]:
                        if opt.startswith(word_before):
                            yield Completion(opt, start_position=-len(word_before))
                    return
                # noun 没匹配到时，继续补全作品名（适用于 open/edit/delete）
                if not noun_matched and first in ("open", "edit", "delete"):
                    for insert, display in self._query_works(word_before):
                        yield Completion(insert, start_position=-len(word_before),
                                         display=display)
                return

            # 第二词输入完且有 noun 匹配时，也补全作品名
            second = words[1] if len(words) >= 2 else ""

            # open url: 补全作品名 + 作者名
            if first == "open" and second == "url":
                if len(words) == 2 or (len(words) == 3 and not text.endswith(" ")):
                    for insert, display in self._query_works(word_before):
                        yield Completion(insert, start_position=-len(word_before),
                                         display=display)
                    for name in self._query_authors(word_before):
                        yield Completion(name, start_position=-len(word_before))
                return

            # search author / delete author: 补全作者名
            if first in ("search", "delete") and second == "author":
                if len(words) == 2 or (len(words) == 3 and not text.endswith(" ")):
                    for name in self._query_authors(word_before):
                        yield Completion(name, start_position=-len(word_before))
                return

            # search label: 补全标签名
            if first == "search" and second == "label":
                if len(words) == 2 or (len(words) == 3 and not text.endswith(" ")):
                    for label in self._query_labels(word_before):
                        yield Completion(label, start_position=-len(word_before))
                return

            # open / edit / delete: 第二词补全作品名（除非是 author/all）
            if first in ("open", "edit", "delete") and second not in ("author", "all"):
                if len(words) == 1 or (len(words) == 2 and not text.endswith(" ")):
                    for insert, display in self._query_works(word_before):
                        yield Completion(insert, start_position=-len(word_before),
                                         display=display)
                # -- 开头时也补全选项
                if word_before.startswith("-"):
                    for opt in self.verb_options[first]:
                        if opt.startswith(word_before):
                            yield Completion(opt, start_position=-len(word_before))
                return

            # search: 补全作品名
            if first == "search" and second not in ("author", "label"):
                if len(words) == 1 or (len(words) == 2 and not text.endswith(" ")):
                    for insert, display in self._query_works(word_before):
                        yield Completion(insert, start_position=-len(word_before),
                                         display=display)
                return

            # 补全选项（仅 -- 开头）
            if word_before.startswith("-"):
                key = (first, second)
                if key in self.noun_options:
                    for opt in self.noun_options[key]:
                        if opt.startswith(word_before):
                            yield Completion(opt, start_position=-len(word_before))
                    return
                for opt in self.verb_options[first]:
                    if opt.startswith(word_before):
                        yield Completion(opt, start_position=-len(word_before))

    completer = DynamicCompleter(app)
    style = Style.from_dict({"prompt": "#ansigreen bold"})
    return PromptSession(completer=completer, style=style)