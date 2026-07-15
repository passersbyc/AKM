"""queries.py row_to_manifest 纯函数测试。"""
import pytest
from src.core.queries import row_to_manifest


class TestRowToManifest:
    def test_full_row(self):
        row = {
            "id": "a001000001",
            "title": "测试",
            "_author_name": "张三",
            "_series_name": "系列一",
            "tags": "tag1,tag2",
            "source": "https://example.com",
            "source_status": "ok",
            "file_ext": ".epub",
            "file_type": "漫画",
            "imported_at": "2025-01-01",
            "file_size_kb": 1024.0,
            "md5": "abc123",
            "file_path": "/lib/test.epub",
            "favorite": 1,
            "rating": 4.5,
            "description": "简介",
            "likes": 100,
        }
        result = row_to_manifest(row)
        assert result["ID"] == "a001000001"
        assert result["标题"] == "测试"
        assert result["作者"] == "张三"
        assert result["系列"] == "系列一"
        assert result["收藏"] == "是"
        assert result["评分"] == "4.5"
        assert result["点赞"] == "100"

    def test_empty_row(self):
        result = row_to_manifest({})
        assert result["ID"] == ""
        assert result["标题"] == ""
        assert result["作者"] == ""
        assert result["系列"] == ""
        assert result["收藏"] == "否"
        assert result["评分"] == ""
        assert result["点赞"] == "0"

    def test_no_favorite(self):
        result = row_to_manifest({"favorite": 0})
        assert result["收藏"] == "否"

    def test_none_author_becomes_empty(self):
        result = row_to_manifest({"_author_name": None})
        assert result["作者"] == ""

    def test_none_series_becomes_empty(self):
        result = row_to_manifest({"_series_name": None})
        assert result["系列"] == ""

    def test_zero_rating_empty(self):
        result = row_to_manifest({"rating": 0})
        assert result["评分"] == ""
