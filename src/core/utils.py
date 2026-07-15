import html
import json
import re

from src.core.config import get_project_root, load_config



def description_to_text(text: str) -> str:
    if not text:
        return ""
    s = html.unescape(text)
    s = s.replace('\\n', '\n').replace('\\r', '\n')
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</p\s*>', '\n', s)
    s = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', s)
    s = re.sub(r'(?s)<[^>]+>', '', s)
    s = re.sub(r'\r\n?', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = '\n'.join(line.strip() for line in s.splitlines())
    return s.strip()


def json_output(data, exit_code: int = 0):
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return exit_code


def json_error(message: str, exit_code: int = 1):
    return json_output({"success": False, "error": message}, exit_code)


def strip_tag_prefix(name: str) -> str:
    """去除开头的 [tag] 标签前缀。"""
    return re.sub(r'^\s*\[([^\]]+)\]\s*', '', name).strip()
