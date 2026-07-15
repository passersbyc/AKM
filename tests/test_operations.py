"""operations 层 mock 测试（clean_op, stats_op, search_op）。"""
from unittest.mock import patch, MagicMock

import pytest


class TestCleanOp:
    @patch("src.operations.clean_op.WorkManager")
    def test_get_pixiv_entries(self, mock_wm):
        from src.operations.clean_op import get_pixiv_entries
        mock_wm.read.return_value = [
            {"来源": "https://pixiv.net/artworks/100", "ID": "a001000001"},
            {"来源": "https://example.com/1", "ID": "b002000001"},
            {"来源": "https://pixiv.net/novel/200", "ID": "c003000001"},
        ]
        result = get_pixiv_entries()
        assert len(result) == 2

    @patch("src.operations.clean_op.WorkManager")
    def test_source_set(self, mock_wm):
        from src.operations.clean_op import source_set
        mock_wm.source_set.return_value = {"url1", "url2"}
        assert source_set() == {"url1", "url2"}


class TestStatsOp:
    @patch("src.operations.stats_op.WorkManager")
    def test_get_stats(self, mock_wm):
        from src.operations.stats_op import get_stats
        mock_wm.get_stats.return_value = {
            "total_books": 100,
            "total_size_kb": 50000,
        }
        result = get_stats()
        assert result["total_books"] == 100


class TestSearchOp:
    @patch("src.operations.search_op._search")
    def test_id_prefix_filter(self, mock_search):
        from src.operations.search_op import search_works
        mock_search.return_value = [
            {"ID": "a001000001", "标题": "A"},
            {"ID": "b002000001", "标题": "B"},
            {"ID": "a001000002", "标题": "C"},
        ]
        result = search_works(query="test", id_prefix="a001")
        assert len(result) == 2
        assert all(r["ID"].startswith("a001") for r in result)

    @patch("src.operations.search_op._search")
    def test_liked_yes_filter(self, mock_search):
        from src.operations.search_op import search_works
        mock_search.return_value = [
            {"ID": "1", "点赞": "100"},
            {"ID": "2", "点赞": "0"},
            {"ID": "3", "点赞": "200"},
        ]
        result = search_works(liked="yes")
        assert len(result) == 2

    @patch("src.operations.search_op._search")
    def test_no_filter(self, mock_search):
        from src.operations.search_op import search_works
        mock_search.return_value = [{"ID": "1"}, {"ID": "2"}]
        result = search_works()
        assert len(result) == 2


class TestDeleteOpFilterRows:
    @patch("src.operations.delete_op.WorkManager")
    def test_filter_by_author(self, mock_wm):
        from src.operations.delete_op import filter_rows
        mock_wm.search.return_value = [
            {"作者": "张三", "ID": "1"},
            {"作者": "李四", "ID": "2"},
        ]
        result = filter_rows(author="张三")
        mock_wm.search.assert_called_once()

    @patch("src.operations.delete_op.WorkManager")
    def test_filter_favorite(self, mock_wm):
        from src.operations.delete_op import filter_rows
        mock_wm.search.return_value = [
            {"收藏": "是", "ID": "1"},
            {"收藏": "否", "ID": "2"},
        ]
        result = filter_rows(favorite=True)
        mock_wm.search.assert_called_once()
