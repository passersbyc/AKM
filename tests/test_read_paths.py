"""读路径端到端测试 — 用隔离站点库造数据，验证聚合读函数不报错。

覆盖分库改造的"读路径长尾"（recommend/stats/author 聚合），
这些路径在空库测试里会直接 return []，掩盖了 db 未定义等运行时错误。
"""
import pytest


@pytest.fixture
def isolated_dbs(tmp_path, monkeypatch):
    """隔离站点库 + 主库到临时目录，清空 thread-local 连接缓存。"""
    from src.core import database, config

    def _clear():
        for attr in list(vars(database._thread_local).keys()):
            try:
                delattr(database._thread_local, attr)
            except AttributeError:
                pass

    _clear()
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(database, "get_data_dir", lambda: data_dir)
    yield data_dir
    _clear()


def _seed(isolated_dbs):
    """造数据：pixiv 站点库 1 作者 + 2 作品，主库 1 条 recent_open。"""
    from src.core.database import get_site_db, get_meta_db
    db = get_site_db("pixiv")
    db.execute("INSERT OR REPLACE INTO authors (id, name, source) VALUES ('001', '测试作者', 'pixiv')")
    db.execute(
        "INSERT OR REPLACE INTO works (id, title, author_id, tags, file_type, source, imported_at, favorite, rating) "
        "VALUES ('n001000001', '作品一', '001', 'tag1,tag2', '小说', "
        "'https://www.pixiv.net/novel/show.php?id=1', '2026-08-20 12:00:00', 1, 4.5)")
    db.execute(
        "INSERT OR REPLACE INTO works (id, title, author_id, tags, file_type, source, imported_at) "
        "VALUES ('n001000002', '作品二', '001', 'tag2,tag3', '小说', "
        "'https://www.pixiv.net/novel/show.php?id=2', '2026-08-20 13:00:00')")
    db.commit()

    meta = get_meta_db()
    meta.execute(
        "INSERT INTO recent_opens (site, work_id, title) VALUES ('pixiv', 'n001000001', '作品一')")
    meta.commit()


class TestRecommendations:
    def test_runs_with_data(self, isolated_dbs):
        """有数据时 get_recommendations 应正常执行（不再 NameError/AttributeError）。"""
        _seed(isolated_dbs)
        from src.operations.recommend_op import get_recommendations
        recs = get_recommendations(limit=8)
        assert isinstance(recs, list)

    def test_empty_returns_empty(self, isolated_dbs):
        """空库时返回空列表。"""
        from src.operations.recommend_op import get_recommendations
        assert get_recommendations() == []


class TestStats:
    def test_get_stats_counts(self, isolated_dbs):
        _seed(isolated_dbs)
        from src.core.work_stats import get_stats
        stats = get_stats()
        assert stats["total_books"] == 2
        assert stats["total_authors"] == 1
        assert stats["total_types"] == 1  # 只有"小说"


class TestListAuthor:
    def test_list_author_with_site(self, isolated_dbs):
        _seed(isolated_dbs)
        from src.operations.list_op import list_items
        result = list_items("author")
        items = result["items"]
        assert len(items) == 1
        assert items[0]["name"] == "测试作者"
        assert items[0]["site"] == "pixiv"
        assert items[0]["work_count"] == 2


class TestListWork:
    def test_list_work_aggregates(self, isolated_dbs):
        _seed(isolated_dbs)
        from src.operations.list_op import list_items
        result = list_items("book")
        assert result["total"] == 2
        # 聚合结果带"站点"字段
        assert result["items"][0].get("站点") == "pixiv"


class TestResolveAuthor:
    def test_homepage_from_tracking(self, isolated_dbs):
        """pixiv 作者主页在 pixiv_trackings（authors.homepage 空），resolve_author 应合并返回。"""
        from src.core.database import get_site_db
        db = get_site_db("pixiv")
        db.execute("INSERT OR REPLACE INTO authors (id, name, source) VALUES ('001', '跟踪作者', 'pixiv')")
        db.execute(
            "INSERT OR REPLACE INTO pixiv_trackings (author_id, pixiv_uid, homepage) "
            "VALUES ('001', '12345', 'https://www.pixiv.net/users/12345')")
        db.commit()

        from src.operations.matcher import resolve_author
        r = resolve_author("p.1")
        assert r is not None
        assert r["homepage"] == "https://www.pixiv.net/users/12345"

    def test_homepage_from_authors(self, isolated_dbs):
        """非 pixiv 作者主页在 authors.homepage。"""
        from src.core.database import get_site_db
        db = get_site_db("pawchive")
        db.execute("INSERT OR REPLACE INTO authors (id, name, source, homepage) "
                   "VALUES ('001', '漫画作者', 'local', 'https://pawchive.pw/fanbox/user/9')")
        db.commit()

        from src.operations.matcher import resolve_author
        r = resolve_author("w.1")
        assert r is not None
        assert r["homepage"] == "https://pawchive.pw/fanbox/user/9"
