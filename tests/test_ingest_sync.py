"""변경·삭제 갱신 테스트 (네트워크·OpenAI 없음)."""

import json
from pathlib import Path

import pytest

from odiro.data.ingest import sync, tour_api
from odiro.data.ingest.common import read_jsonl, write_jsonl


def place(cid, modified="20260101000000", ctype=12, title=None):
    return {"content_id": cid, "title": title or f"장소{cid}", "content_type_id": ctype, "modified": modified}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    tour, labeled, state = tmp_path / "tour", tmp_path / "labeled", tmp_path / "state"
    for d in (tour, labeled, state):
        d.mkdir()
    for mod in (sync, tour_api):
        monkeypatch.setattr(mod, "TOUR_DIR", tour, raising=False)
        monkeypatch.setattr(mod, "STATE_DIR", state, raising=False)
    monkeypatch.setattr(sync, "LABELED_DIR", labeled)
    monkeypatch.setattr(tour_api, "META_PATH", tour / "area_{code}.jsonl")
    monkeypatch.setattr(tour_api, "DETAIL_PATH", tour / "detail_{code}.jsonl")
    monkeypatch.setattr(tour_api, "INTRO_PATH", tour / "intro_{code}.jsonl")
    return tour, labeled, state


# ---------- 비교 ----------


def test_plan_sync_classifies():
    old = [place("1"), place("2", "A"), place("3")]
    new = [place("1"), place("2", "B"), place("4")]
    plan = sync.plan_sync(old, new)
    assert plan.added == ["4"] and plan.changed == ["2"] and plan.removed == ["3"]


def test_removal_guard_blocks_mass_delete():
    sync.check_removal_safe(1000, 960, 40)  # 5% 이내
    with pytest.raises(sync.SyncAborted):
        sync.check_removal_safe(1000, 900, 100)
    sync.check_removal_safe(1000, 900, 100, force=True)


def test_removal_guard_floor_for_small_regions():
    sync.check_removal_safe(200, 180, 20)  # 작은 시도는 최소 30건까지 허용
    with pytest.raises(sync.SyncAborted):
        sync.check_removal_safe(200, 160, 40)


def test_removal_guard_empty_new_list():
    with pytest.raises(sync.SyncAborted):
        sync.check_removal_safe(100, 0, 100)


# ---------- 파일 유틸 ----------


def test_compact_keeps_last(tmp_path):
    p = tmp_path / "d.jsonl"
    write_jsonl(p, [{"content_id": "1", "v": "old"}, {"content_id": "2", "v": "x"}, {"content_id": "1", "v": "new"}])
    assert sync.compact_jsonl(p) == 1
    rows = {r["content_id"]: r["v"] for r in read_jsonl(p)}
    assert rows == {"1": "new", "2": "x"}


def test_stamp_legacy_only_missing(tmp_path):
    p = tmp_path / "d.jsonl"
    write_jsonl(p, [{"content_id": "1"}, {"content_id": "2", "modified": "KEEP"}, {"content_id": "9"}])
    assert sync.stamp_legacy(p, {"1": "M1", "2": "M2"}) == 1
    rows = {r["content_id"]: r.get("modified") for r in read_jsonl(p)}
    assert rows == {"1": "M1", "2": "KEEP", "9": None}


# ---------- apply_sync ----------


def seed(tour, labeled, code="11"):
    write_jsonl(tour / f"area_{code}.jsonl", [place("1", "A"), place("2", "A"), place("3", "A"), place("4", "A", ctype=39)])
    write_jsonl(tour / f"detail_{code}.jsonl", [{"content_id": c, "overview": f"o{c}"} for c in "123"])  # modified 없는 옛 기록
    write_jsonl(tour / f"intro_{code}.jsonl", [{"content_id": c, "use_time": "9~18"} for c in "123"])
    write_jsonl(labeled / f"area_{code}.jsonl", [{"doc_id": f"place:{c}", "doc_type": "place"} for c in "123"] + [{"doc_id": "blog:x", "doc_type": "blog"}])


def test_apply_sync_removes_everything_for_deleted(dirs):
    tour, labeled, state = dirs
    seed(tour, labeled)
    # 3 삭제, 2 변경, 5 신규. 타입 12 만 받았으므로 39(4번)는 건드리지 않는다
    new = [place("1", "A"), place("2", "B"), place("5", "A")]
    res = sync.apply_sync("11", new, [12], force=True)
    assert (res.added, res.changed, res.removed) == (1, 1, 1)

    assert {r["content_id"] for r in read_jsonl(tour / "detail_11.jsonl")} == {"1", "2"}
    assert {r["content_id"] for r in read_jsonl(tour / "intro_11.jsonl")} == {"1", "2"}
    meta = {r["content_id"]: r["modified"] for r in read_jsonl(tour / "area_11.jsonl")}
    assert meta == {"4": "A", "1": "A", "2": "B", "5": "A"}  # 4(타입 39)는 그대로 보존
    assert sync.pending_purge("11") == ["3"]  # 라벨·벡터는 큐로


def test_apply_sync_marks_changed_for_refetch(dirs):
    tour, labeled, state = dirs
    seed(tour, labeled)
    sync.apply_sync("11", [place("1", "A"), place("2", "B"), place("3", "A")], [12])
    have = tour_api._stored_modified(tour / "detail_11.jsonl")
    assert have == {"1": "A", "2": "A", "3": "A"}  # 옛 기록에 그때의 modified 가 채워졌다
    meta = {p["content_id"]: p for p in read_jsonl(tour / "area_11.jsonl")}
    todo = [c for c, p in meta.items() if p["content_type_id"] == 12 and tour_api.needs_fetch(p, have)]
    assert todo == ["2"]  # 바뀐 것만 다시 받는다


def test_apply_sync_aborts_without_touching_files(dirs):
    tour, labeled, state = dirs
    seed(tour, labeled)
    before = (tour / "area_11.jsonl").read_text(encoding="utf-8")
    with pytest.raises(sync.SyncAborted):
        sync.apply_sync("11", [], [12])  # API 가 빈 목록을 줬다
    assert (tour / "area_11.jsonl").read_text(encoding="utf-8") == before
    assert len(list(read_jsonl(tour / "detail_11.jsonl"))) == 3
    assert sync.pending_purge("11") == []


def test_purge_queue_drops_labels_and_vectors(dirs):
    tour, labeled, state = dirs
    seed(tour, labeled)
    sync.queue_purge("11", ["2", "3"])
    sync.queue_purge("11", ["3", "9"])  # 합쳐진다
    assert sync.pending_purge("11") == ["2", "3", "9"]

    class FakeCol:
        calls: list = []

        def delete(self, where):
            self.calls.append(where)

    class FakeVS:
        _collection = FakeCol()

    assert sync.process_purge_queue("11", FakeVS()) == 3
    ids = {r["doc_id"] for r in read_jsonl(labeled / "area_11.jsonl")}
    assert ids == {"place:1", "blog:x"}  # 블로그는 건드리지 않는다
    assert FakeCol.calls == [{"content_id": {"$in": ["2", "3", "9"]}}]
    assert sync.pending_purge("11") == []
    assert sync.process_purge_queue("11", FakeVS()) == 0


def test_synced_once_per_day(dirs):
    assert not sync.synced_today("11")
    sync.mark_synced("11")
    assert sync.synced_today("11")


# ---------- 수집 단계: 변경분 재수집 ----------


class FakeQuota:
    remaining = 100


class FakeClient:
    quota_detail = FakeQuota()

    def fetch_detail(self, cid):
        return {"content_id": cid, "overview": f"NEW-{cid}", "source": "tourapi"}


def test_collect_detail_refetches_changed_and_queues_purge(dirs):
    tour, labeled, state = dirs
    seed(tour, labeled)
    sync.apply_sync("11", [place("1", "A"), place("2", "B"), place("3", "A"), place("7", "A")], [12])
    n = tour_api.collect_detail(FakeClient(), "11", None, [12])
    assert n == 2  # 변경 2 + 신규 7
    assert sync.pending_purge("11") == ["2"]  # 신규(7)는 지울 게 없고, 다시 받은 2 만 옛 라벨·벡터를 지운다
    sync.compact_jsonl(tour / "detail_11.jsonl")
    rows = {r["content_id"]: r for r in read_jsonl(tour / "detail_11.jsonl")}
    assert rows["2"]["overview"] == "NEW-2" and rows["2"]["modified"] == "B"
    assert rows["1"]["overview"] == "o1"  # 안 바뀐 건 그대로
    assert rows["7"]["modified"] == "A"
    # 다시 돌리면 더 받을 게 없다
    assert tour_api.collect_detail(FakeClient(), "11", None, [12]) == 0


def test_collect_detail_legacy_records_not_refetched_without_sync(dirs):
    tour, labeled, state = dirs
    seed(tour, labeled)  # modified 없는 옛 기록
    assert tour_api.collect_detail(FakeClient(), "11", None, [12]) == 0


# ---------- 실제 Chroma 에서 삭제가 되는지 ----------


def test_purge_vectors_real_chroma(tmp_path):
    chromadb = pytest.importorskip("chromadb")
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    col = client.get_or_create_collection("test_docs")
    col.add(
        ids=["place:1#0", "place:1#1", "place:2#0", "blog:x#0"],
        embeddings=[[0.1, 0.2], [0.2, 0.1], [0.3, 0.3], [0.4, 0.1]],
        metadatas=[{"content_id": "1"}, {"content_id": "1"}, {"content_id": "2"}, {"doc_type": "blog"}],
    )

    class VS:
        _collection = col

    sync.purge_vectors(VS(), ["1"])
    assert sorted(col.get()["ids"]) == ["blog:x#0", "place:2#0"]
    sync.purge_vectors(VS(), ["2", "nope"])
    assert col.get()["ids"] == ["blog:x#0"]
    json.dumps(col.get()["ids"])
