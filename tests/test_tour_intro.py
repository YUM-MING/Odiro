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


# ---------- F4: 핀 팝업 이미지 (TourAPI firstimage, 이름 + 300m 로 매칭된 장소만) ----------

IMG = "https://tong.visitkorea.or.kr/cms/resource/15/3542815_image2_1.jpg"


def test_find_image_and_intro_are_separate(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, [{**ROW, "img": IMG}, {"n": "산장관광지", "lat": 37.7542, "lng": 127.4106, "img": IMG}])
    assert tour_intro.find_intro("경복궁", 37.5797, 126.9771) == {"rest_date": "화요일", "use_time": "09:00~18:00"}  # img 는 이용 정보에 안 섞인다
    assert tour_intro.find_image("경복궁", 37.5797, 126.9771) == IMG
    assert tour_intro.find_intro("산장관광지", 37.7542, 127.4106) is None  # 이미지만 있는 줄은 이용 정보 없음
    assert tour_intro.find_image("산장관광지", 37.7543, 127.4107) == IMG
    assert tour_intro.find_image("산장관광지", 37.80, 127.4106) is None  # 멀면 다른 곳
    assert tour_intro.find_image("경복궁", 37.5797, 126.9771) and tour_intro.find_image("없는곳", 37.5, 127.0) is None


def test_https_image_rules():
    assert tour_intro.https_image(IMG) == IMG
    assert tour_intro.https_image("http://tong.visitkorea.or.kr/cms/resource/1/2_image2_1.jpg") == "https://tong.visitkorea.or.kr/cms/resource/1/2_image2_1.jpg"
    assert tour_intro.https_image("http://example.com/a.jpg") == ""  # https 지원이 확인되지 않은 호스트는 쓰지 않는다
    assert tour_intro.https_image("") == "" and tour_intro.https_image(None) == ""


def test_build_lookup_keeps_image_rows_without_intro(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("bil", Path(__file__).resolve().parent.parent / "scripts" / "build_intro_lookup.py")
    bil = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bil)
    tour = tmp_path / "tour"
    tour.mkdir()
    area = [{"content_id": "1", "title": "경복궁", "lat": 37.5796, "lng": 126.977, "image": "http://tong.visitkorea.or.kr/x_image2_1.jpg", "image_thumb": "t"},
            {"content_id": "2", "title": "산장관광지", "lat": 37.7542, "lng": 127.4106, "image": IMG, "image_thumb": ""},
            {"content_id": "3", "title": "정보없음", "lat": 37.0, "lng": 127.0, "image": "", "image_thumb": ""}]
    (tour / "area_11.jsonl").write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in area), encoding="utf-8")
    (tour / "intro_11.jsonl").write_text(json.dumps({"content_id": "1", "rest_date": "화요일"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    rows = {r["n"]: r for r in bil.build()}
    assert rows["경복궁"] == {"n": "경복궁", "lat": 37.5796, "lng": 126.977, "rest_date": "화요일", "img": "https://tong.visitkorea.or.kr/x_image2_1.jpg"}
    assert rows["산장관광지"]["img"] == IMG and "rest_date" not in rows["산장관광지"]
    assert "정보없음" not in rows  # 이용 정보도 이미지도 없으면 넣지 않는다


def test_response_image_from_lookup_only_for_matched_places(tmp_path, monkeypatch):
    from odiro.agent import run
    from odiro.api.schemas import CourseRequest

    _use(tmp_path, monkeypatch, [{"n": "산장관광지", "lat": 37.7542, "lng": 127.4106, "img": IMG}])
    base = {"order": 1, "day": 1, "category": "관광지", "verified": True}
    state = {"places": [{**base, "name": "산장관광지", "lat": 37.7542, "lng": 127.4106},  # 카카오 확인 장소 → 조회 파일로 이미지
                        {**base, "order": 2, "name": "카카오식당", "lat": 37.75, "lng": 127.41},  # TourAPI 에 없음 → 빈 값
                        {**base, "order": 3, "name": "큐레이션", "lat": 37.7, "lng": 127.4, "image": "http://tong.visitkorea.or.kr/c.jpg"}],  # RAG 이미지
             "legs": []}
    resp = run._to_response(state, CourseRequest(region="가평", date="2026-11-26"), 10)
    assert [p.image for p in resp.places] == [IMG, "", "https://tong.visitkorea.or.kr/c.jpg"]
