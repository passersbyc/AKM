"""共享 fixtures。"""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_project(tmp_path):
    """创建一个临时项目根目录，含最小 config.json。"""
    import json
    config = {
        "project_settings": {
            "library_path": "library",
        },
        "pixiv": {"cookie": "test_cookie"},
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "library").mkdir()
    return tmp_path


@pytest.fixture
def fake_db(tmp_path):
    """创建一个内存 SQLite 连接并初始化最小表结构。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE works (
            id TEXT PRIMARY KEY, title TEXT, author_id TEXT, series_id TEXT,
            tags TEXT, source TEXT, source_status TEXT DEFAULT 'ok',
            file_ext TEXT, file_type TEXT, imported_at TEXT,
            file_size_kb REAL, md5 TEXT, file_path TEXT,
            favorite INTEGER DEFAULT 0, rating REAL DEFAULT 0,
            description TEXT, likes INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE authors (
            id TEXT PRIMARY KEY, name TEXT, pixiv_uid TEXT,
            homepage TEXT, follow_status TEXT DEFAULT 'active',
            last_checked TEXT, latest_work_id TEXT,
            favorite INTEGER DEFAULT 0, note TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE series (
            id TEXT PRIMARY KEY, author_id TEXT, name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE id_counters (
            name TEXT PRIMARY KEY, value INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sample_rows():
    """构造一组用于测试的模拟作品行。"""
    return [
        {
            "ID": "a001000001", "标题": "测试作品A", "作者": "张三",
            "系列": "系列一", "标签": "tag1,tag2", "来源": "https://pixiv.net/artworks/100",
            "后缀": ".epub", "分类": "漫画", "文件大小(KB)": 1024,
            "MD5": "abc123", "文件路径": "/tmp/lib/test_a.epub",
            "收藏": "是", "评分": 4.5, "简介": "简介A", "点赞": 100,
        },
        {
            "ID": "b002000001", "标题": "测试作品B", "作者": "李四",
            "系列": "", "标签": "tag3", "来源": "https://pixiv.net/artworks/200",
            "后缀": ".txt", "分类": "小说", "文件大小(KB)": 512,
            "MD5": "def456", "文件路径": "/tmp/lib/test_b.txt",
            "收藏": "否", "评分": 0, "简介": "", "点赞": 50,
        },
        {
            "ID": "a001000002", "标题": "测试作品C", "作者": "张三",
            "系列": "系列一", "标签": "tag1,tag4", "来源": "",
            "后缀": ".epub", "分类": "漫画", "文件大小(KB)": 2048,
            "MD5": "ghi789", "文件路径": "/tmp/lib/test_c.epub",
            "收藏": "否", "评分": 3.0, "简介": "简介C", "点赞": 200,
        },
    ]
