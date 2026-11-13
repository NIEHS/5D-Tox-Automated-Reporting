"""The .bm2 cache is keyed by the file's content and makes room when full
(bm2_cache)."""

import lmdb
import pytest

from bmdx_pipe import bm2_cache


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(bm2_cache, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(bm2_cache, "_env", None)
    monkeypatch.setattr(bm2_cache, "_digests", {})
    yield bm2_cache
    if bm2_cache._env is not None:
        bm2_cache._env.close()


def test_a_file_replaced_at_the_same_path_is_not_served_the_old_project(cache, tmp_path):
    path = tmp_path / "Hormones.bm2"
    path.write_bytes(b"first project")
    cache.put_json(str(path), {"name": "first"})
    cache.put_categories(str(path), {("exp", "TSH"): {"bmd": 1.0}})
    assert cache.get_json(str(path)) == {"name": "first"}
    assert cache.get_categories(str(path)) == {("exp", "TSH"): {"bmd": 1.0}}

    path.write_bytes(b"a corrected project")           # same path, new content
    assert cache.get_json(str(path)) is None
    assert cache.get_categories(str(path)) is None


def test_identical_files_share_an_entry_and_a_missing_file_is_not_cached(cache, tmp_path):
    a, b = tmp_path / "a.bm2", tmp_path / "b.bm2"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    cache.put_json(str(a), {"name": "same"})
    assert cache.get_json(str(b)) == {"name": "same"}
    cache.put_json(str(tmp_path / "gone.bm2"), {"x": 1})   # nothing to key it by
    assert cache.get_json(str(tmp_path / "gone.bm2")) is None


def test_a_full_cache_grows_then_clears_instead_of_failing_every_write(cache, tmp_path, monkeypatch):
    monkeypatch.setattr(bm2_cache, "_MAP_SIZE", 256 * 1024)
    monkeypatch.setattr(bm2_cache, "_MAX_MAP_SIZE", 1024 * 1024)
    big = {"data": "x" * 200_000}
    paths = []
    for i in range(8):                                   # ~1.6 MB into a 1 MB cap
        p = tmp_path / f"{i}.bm2"
        p.write_bytes(str(i).encode())
        cache.put_json(str(p), big)
        paths.append(p)
        assert cache.get_json(str(p)) == big             # every write lands
    assert cache._get_env().info()["map_size"] == 1024 * 1024
    assert cache.get_json(str(paths[0])) is None         # cleared at the cap


def test_the_cache_never_raises_on_a_write(cache, tmp_path, monkeypatch):
    p = tmp_path / "x.bm2"
    p.write_bytes(b"x")

    def full(*a, **k):
        raise lmdb.MapFullError("full")
    monkeypatch.setattr(bm2_cache, "_write", full)
    cache.put_json(str(p), {"x": 1})                     # logged, not raised
