"""source_op.py 纯函数与 mock 测试。"""
import time
import types
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest
from src.operations.source_op import (
    should_recheck_dead, author_id_matches, compute_update_flags,
    build_work_index, unfollow_targets, resolve_sync_candidates,
    backfill_homepages, reset_dead_authors, check_user_exists,
    list_sources_data, update_single_work_metadata,
    has_new_favorites, save_updated_ids,
)


class TestShouldRecheckDead:
    def test_empty_string(self):
        assert should_recheck_dead("", time.time()) is True

    def test_recent_date(self):
        now = time.time()
        recent = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 3600))
        assert should_recheck_dead(recent, now) is False

    def test_old_date(self):
        now = time.time()
        old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 8 * 86400))
        assert should_recheck_dead(old, now) is True

    def test_invalid_format(self):
        assert should_recheck_dead("not-a-date", time.time()) is True


class TestAuthorIdMatches:
    def test_match(self):
        assert author_id_matches("a001000001", "001") is True

    def test_no_match(self):
        assert author_id_matches("a002000001", "001") is False

    def test_short_rid(self):
        assert author_id_matches("a0", "001") is False

    def test_exact_length(self):
        assert author_id_matches("a001", "001") is True


class TestComputeUpdateFlags:
    def _make_args(self, **kwargs):
        defaults = {
            "tags": False, "likes": False, "description": False,
            "title": False, "update_author": False, "update_all": False,
        }
        defaults.update(kwargs)
        return types.SimpleNamespace(**defaults)

    def test_no_specific_flags(self):
        flags = compute_update_flags(self._make_args())
        assert flags["update_tags"] is True
        assert flags["update_likes"] is True
        assert flags["update_desc"] is True
        assert flags["update_title"] is False
        assert flags["update_author"] is False

    def test_tags_only(self):
        flags = compute_update_flags(self._make_args(tags=True))
        assert flags["update_tags"] is True
        assert flags["update_likes"] is False
        assert flags["update_desc"] is False

    def test_update_all(self):
        flags = compute_update_flags(self._make_args(update_all=True))
        assert flags["update_tags"] is True
        assert flags["update_likes"] is True
        assert flags["update_desc"] is True
        assert flags["update_title"] is False  # requires args.title explicitly
        assert flags["update_author"] is True

    def test_title_only(self):
        flags = compute_update_flags(self._make_args(title=True))
        assert flags["update_title"] is True
        assert flags["update_author"] is False


class TestBuildWorkIndex:
    @patch("src.operations.source_op.WorkManager")
    @patch("src.operations.source_op.extract_pixiv_id")
    def test_basic_index(self, mock_extract, mock_wm):
        mock_extract.side_effect = lambda url: url.split("/")[-1] if "pixiv" in url else ""
        mock_wm.read.return_value = [
            {"ID": "a001000001", "来源": "https://pixiv.net/100"},
            {"ID": "a001000002", "来源": "https://pixiv.net/200"},
            {"ID": "b002000001", "来源": ""},
        ]
        targets = [{"id": "001", "pixiv_uid": "12345"}]
        work_index, source_to_id = build_work_index(targets)
        assert "001" in work_index
        assert "100" in work_index["001"]
        assert "https://pixiv.net/100" in source_to_id


class TestUnfollowTargets:
    @patch("src.operations.source_op.unfollow")
    @patch("src.operations.source_op.resolve")
    def test_basic(self, mock_resolve, mock_unfollow):
        mock_resolve.side_effect = lambda t: {"pixiv_uid": f"uid_{t}", "name": f"作者{t}"} if t else None
        mock_unfollow.return_value = True
        result = unfollow_targets("a,b")
        assert result["unfollowed"] == 2

    @patch("src.operations.source_op.unfollow")
    @patch("src.operations.source_op.resolve")
    def test_not_found(self, mock_resolve, mock_unfollow):
        mock_resolve.return_value = None
        result = unfollow_targets("x")
        assert result["unfollowed"] == 0


class TestResolveSyncCandidates:
    @patch("src.operations.source_op.list_all")
    @patch("src.operations.source_op.migrate_follows_csv")
    def test_no_target(self, mock_migrate, mock_list):
        mock_list.return_value = [
            {"follow_status": "active", "pixiv_uid": "1", "favorite": False, "id": "001"},
            {"follow_status": "dead", "pixiv_uid": "2", "favorite": False, "id": "002"},
            {"follow_status": "paused", "pixiv_uid": "", "favorite": False, "id": "003"},
        ]
        candidates = resolve_sync_candidates(None)
        assert len(candidates) == 2  # active + dead, paused has no uid

    @patch("src.operations.source_op.resolve")
    @patch("src.operations.source_op.migrate_follows_csv")
    def test_with_target_found(self, mock_migrate, mock_resolve):
        mock_resolve.return_value = {"name": "test"}
        candidates = resolve_sync_candidates("test")
        assert len(candidates) == 1

    @patch("src.operations.source_op.resolve")
    @patch("src.operations.source_op.migrate_follows_csv")
    def test_with_target_not_found(self, mock_migrate, mock_resolve):
        mock_resolve.return_value = None
        candidates = resolve_sync_candidates("test")
        assert len(candidates) == 0


class TestBackfillHomepages:
    @patch("src.operations.source_op.update")
    def test_fills_missing(self, mock_update):
        candidates = [
            {"pixiv_uid": "123", "homepage": ""},
            {"pixiv_uid": "456", "homepage": "https://www.pixiv.net/users/456"},
        ]
        backfill_homepages(candidates)
        mock_update.assert_called_once()
        assert candidates[0]["homepage"] == "https://www.pixiv.net/users/123"


class TestResetDeadAuthors:
    @patch("src.operations.source_op.update")
    @patch("src.operations.source_op.list_all")
    def test_reset_all(self, mock_list, mock_update):
        mock_list.return_value = [
            {"pixiv_uid": "1", "name": "A", "follow_status": "dead"},
            {"pixiv_uid": "2", "name": "B", "follow_status": "active"},
        ]
        result = reset_dead_authors(None)
        assert result["reset"] == 1
        assert "A (1)" in result["names"]

    @patch("src.operations.source_op.update")
    @patch("src.operations.source_op.list_all")
    def test_reset_target_not_found(self, mock_list, mock_update):
        mock_list.return_value = [
            {"pixiv_uid": "1", "name": "A", "follow_status": "dead"},
        ]
        result = reset_dead_authors("unknown")
        assert result["not_found"] is True


class TestCheckUserExists:
    @patch("src.operations.source_op.requests.get")
    def test_no_cookie(self, mock_get):
        assert check_user_exists("123", None) is True
        mock_get.assert_not_called()

    @patch("src.operations.source_op.requests.get")
    def test_user_exists(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"body": {"userId": "123"}}
        mock_get.return_value = mock_resp
        assert check_user_exists("123", "cookie") is True

    @patch("src.operations.source_op.requests.get")
    def test_user_deleted(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"error": True}
        mock_get.return_value = mock_resp
        assert check_user_exists("123", "cookie") is False


class TestListSourcesData:
    @patch("src.operations.source_op.WorkManager")
    @patch("src.operations.source_op.list_all")
    @patch("src.operations.source_op.migrate_follows_csv")
    def test_basic(self, mock_migrate, mock_list, mock_wm):
        mock_list.return_value = [
            {"name": "A", "pixiv_uid": "1", "id": "001",
             "follow_status": "active", "last_checked": "2025-01-01", "favorite": False},
        ]
        mock_wm.read.return_value = [
            {"作者": "A"}, {"作者": "A"}, {"作者": "B"},
        ]
        result = list_sources_data()
        assert result["total"] == 1
        assert result["sources"][0]["works_count"] == 2


class TestUpdateSingleWorkMetadata:
    def test_no_changes(self):
        work = {"ID": "a001000001", "标题": "test", "来源": "url",
                "作者": "A", "系列": "", "标签": "t1", "点赞": "50",
                "简介": "desc"}
        dl = MagicMock()
        dl.get_info.return_value = {"tags": ["t1"], "like_count": 50, "description": "desc"}
        flags = {"update_tags": True, "update_likes": True, "update_desc": True,
                 "update_title": False, "update_author": False}
        result = update_single_work_metadata(work, dl, flags)
        assert result is None

    @patch("src.operations.source_op.WorkManager")
    def test_tag_added(self, mock_wm):
        work = {"ID": "a001000001", "标题": "test", "来源": "url",
                "作者": "A", "系列": "", "标签": "t1", "点赞": "50",
                "简介": "desc"}
        dl = MagicMock()
        dl.get_info.return_value = {"tags": ["t1", "t2"], "like_count": 50,
                                     "description": "desc"}
        flags = {"update_tags": True, "update_likes": False, "update_desc": False,
                 "update_title": False, "update_author": False}
        result = update_single_work_metadata(work, dl, flags)
        assert result is not None
        assert "t2" in result["changes"][0]


class TestHasNewFavorites:
    def test_no_file(self, tmp_path):
        with patch("src.operations.source_op.get_project_root", return_value=tmp_path):
            assert has_new_favorites() is False

    def test_empty_file(self, tmp_path):
        (tmp_path / ".new_favorites").write_text("")
        with patch("src.operations.source_op.get_project_root", return_value=tmp_path):
            assert has_new_favorites() is False

    def test_has_content(self, tmp_path):
        (tmp_path / ".new_favorites").write_text("001,002")
        with patch("src.operations.source_op.get_project_root", return_value=tmp_path):
            assert has_new_favorites() is True


class TestSaveUpdatedIds:
    def test_saves_changed(self, tmp_path):
        with patch("src.operations.source_op.get_project_root", return_value=tmp_path):
            targets = [
                {"pixiv_uid": "1", "id": "001"},
                {"pixiv_uid": "2", "id": "002"},
            ]
            results = {"1": {"new": 2, "deleted": 0}, "2": {}}
            save_updated_ids(targets, results)
            ids_file = tmp_path / ".updated_authors"
            assert ids_file.exists()
            assert "001" in ids_file.read_text()
