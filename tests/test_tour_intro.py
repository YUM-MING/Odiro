"""tour_intro 조회 (이름 + 좌표 근접) 단위 테스트."""

import json

from odiro.tools import tour_intro


def _use(tmp_path, monkeypatch, rows):
    p = tmp_path / "tour_intro.json"
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tour_intro, "PATH", p)
    tour_intro._table.cache_clear()


ROW = {"n": "경복궁 (서울)", "lat": 37.5796, "lng": 126.977, "rest_date": "화요일", "use_time": "09:00~18:00"}


def test_find_intro_by_name_and_distance(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, [ROW])
    r = tour_intro.find_intro("경복궁", 37.5797, 126.9771)
    assert r == {"rest_date": "화요일", "use_time": "09:00~18:00"}


def test_find_intro_rejects_far_or_other_name(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, [ROW])
    assert tour_intro.find_intro("경복궁", 37.7, 126.977) is None  # 같은 이름이라도 멀면 다른 곳
    assert tour_intro.find_intro("창덕궁", 37.5796, 126.977) is None


def test_find_intro_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tour_intro, "PATH", tmp_path / "none.json")
    tour_intro._table.cache_clear()
    assert tour_intro.find_intro("경복궁", 37.5, 127.0) is None
