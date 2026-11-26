"""오늘의 숨은 여행지: 후보 선정(build_intro_lookup) · 날짜별 선택(daily_pick) · GET /api/daily-pick. 외부 API 호출 없음."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odiro.tools import daily_pick as dp
from odiro.tools import tour_intro

ROOT = Path(__file__).resolve().parent.parent
IMG = "https://tong.visitkorea.or.kr/cms/resource/15/3542815_image2_1.jpg"
LONG = ("청령포는 영월군 남면 광천리 남한강 상류에 있다. 왕위를 빼앗기고 영월로 유배된 단종이 머무르던 곳이다. "
        "삼면이 물로 둘러싸이고 한쪽은 험준한 암벽이 솟아 있어 나룻배를 이용하지 않고는 드나들 수 없는 곳이다. "
        "울창한 송림이 장관을 이룬다. 단종이 한양을 그리며 쌓았다는 망향탑과 노산대가 남아 있다.")


def _bil():
    spec = importlib.util.spec_from_file_location("bil", ROOT / "scripts" / "build_intro_lookup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _place(cid, title, sido="51", addr="강원특별자치도 영월군 남면 광천리", **kw):
    return {"content_id": cid, "title": title, "content_type_id": 12, "sido_code": sido, "addr": addr,
            "lat": 37.17, "lng": 128.44, "image": IMG, "image_thumb": "", "cat1": "", "lcls1": "NA", **kw}


def _write(tour: Path, code: str, area: list[dict], details: dict[str, str], intro: list[dict] | None = None) -> None:
    (tour / f"area_{code}.jsonl").write_text("\n".join(json.dumps(a, ensure_ascii=False) for a in area), encoding="utf-8")
    (tour / f"detail_{code}.jsonl").write_text(
        "\n".join(json.dumps({"content_id": k, "overview": v}, ensure_ascii=False) for k, v in details.items()), encoding="utf-8")
    if intro:
        (tour / f"intro_{code}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in intro), encoding="utf-8")


# ---------- 후보 선정 ----------


def test_pick_candidates_filters(tmp_path, monkeypatch):
    bil = _bil()
    tour = tmp_path / "tour"
    tour.mkdir()
    _write(tour, "51", [
        _place("1", "영월 청령포"),
        _place("2", "역사 유적", lcls1="HS"),
        _place("3", "옛 분류 인문", cat1="A02", lcls1="VE"),  # cat1 이 있으면 cat1 기준
        _place("4", "체험장", lcls1="EX"),  # 자연·인문 아님
        _place("5", "옛 분류 레포츠", cat1="A03", lcls1="NA"),  # cat1 이 레포츠면 lcls1 이 NA 여도 제외
        _place("6", "식당", content_type_id=39),  # 관광지 아님
        _place("7", "사진 없음", image="", image_thumb=IMG),  # 대표 이미지(firstimage) 없음
        _place("8", "설명 짧음"),
        _place("9", "설명 없음"),
    ], {k: LONG for k in "1234567"} | {"8": "짧은 소개글입니다."}, intro=[{"content_id": "1", "rest_date": "연중무휴"}])
    _write(tour, "11", [_place("20", "서울 공원", sido="11", addr="서울특별시 종로구 세종로")], {"20": LONG})  # 제외 시도
    _write(tour, "50", [_place("30", "제주 오름", sido="50", addr="제주특별자치도 제주시 조천읍")], {"30": LONG})
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    rows = {r["n"]: r for r in bil.build()}
    picks = {n for n, r in rows.items() if r.get("pick")}
    assert picks == {"영월 청령포", "역사 유적", "옛 분류 인문"}
    r = rows["영월 청령포"]
    # 기존 필드(이름·좌표·이용 정보·img)는 그대로, 후보 필드만 더해진다
    assert {k: r[k] for k in ("n", "lat", "lng", "rest_date", "img")} == {"n": "영월 청령포", "lat": 37.17, "lng": 128.44, "rest_date": "연중무휴", "img": IMG}
    assert r["pick"] == 1 and r["cid"] == "1" and r["sd"] == "강원" and r["sg"] == "영월군"
    assert len(LONG) > 140 and len(r["desc"]) <= 140 and r["desc"].endswith("이룬다.") and LONG.startswith(r["desc"])  # 문장 단위로 자름
    for n in ("체험장", "식당", "사진 없음", "설명 짧음", "서울 공원", "제주 오름"):
        assert n in rows and not {"pick", "cid", "sd", "sg", "desc"} & set(rows[n])  # 후보가 아닌 줄은 예전 모양
    assert "설명 없음" in rows and "pick" not in rows["설명 없음"]


def test_pick_last_line_wins_and_region_names(tmp_path, monkeypatch):
    bil = _bil()
    tour = tmp_path / "tour"
    tour.mkdir()
    _write(tour, "12", [
        _place("1", "옛 이름", sido="12", addr="전라남도 담양군 담양읍"),
        _place("1", "새 이름", sido="12", addr="전라남도 담양군 담양읍"),  # 같은 장소 갱신 → 마지막 줄
        _place("2", "무등산", sido="12", addr="광주광역시 북구 금곡동"),
    ], {"1": LONG, "2": LONG})
    _write(tour, "36110", [_place("3", "세종 호수", sido="36110", addr="세종특별자치시 연기면 세종리")], {"3": LONG})
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    rows = {r["n"]: r for r in bil.build()}
    assert "옛 이름" not in rows and (rows["새 이름"]["sd"], rows["새 이름"]["sg"]) == ("전남", "담양군")
    # 전남·광주는 코드가 같아 주소로 나눈다 (광주 북구는 광역시 자치구라 후보에서는 빠진다)
    assert bil.sido_short("12", "광주광역시 북구 금곡동") == "광주" and "pick" not in rows["무등산"]
    assert (rows["세종 호수"]["sd"], rows["세종 호수"]["sg"]) == ("세종", "")


def test_pick_excludes_metro_districts_only(tmp_path, monkeypatch):
    # 광역시 도심(자치구)은 빼고, 광역시의 군·세종·도 소속 시(와 그 안의 구)는 남긴다
    bil = _bil()
    tour = tmp_path / "tour"
    tour.mkdir()
    _write(tour, "27", [_place("1", "대구 고분군", sido="27", addr="대구광역시 북구 구암동"),
                        _place("2", "비슬산 유가사", sido="27", addr="대구광역시 달성군 유가읍")], {"1": LONG, "2": LONG})
    _write(tour, "31", [_place("3", "울산 공원", sido="31", addr="울산광역시 남구 신정동"),
                        _place("4", "간절곶", sido="31", addr="울산광역시 울주군 서생면")], {"3": LONG, "4": LONG})
    _write(tour, "30", [_place("5", "대전 생태관", sido="30", addr="대전광역시 서구 둔산동")], {"5": LONG})
    _write(tour, "12", [_place("6", "무등산", sido="12", addr="광주광역시 북구 금곡동"),
                        _place("7", "죽녹원", sido="12", addr="전라남도 담양군 담양읍")], {"6": LONG, "7": LONG})
    _write(tour, "47", [_place("8", "금산서원", sido="47", addr="경상북도 포항시 남구 장기면"),
                        _place("9", "불국사", sido="47", addr="경상북도 경주시 진현동")], {"8": LONG, "9": LONG})
    _write(tour, "36110", [_place("10", "세종 호수", sido="36110", addr="세종특별자치시 연기면 세종리")], {"10": LONG})
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    rows = {r["n"]: r for r in bil.build()}
    picks = {n for n, r in rows.items() if r.get("pick")}
    assert picks == {"비슬산 유가사", "간절곶", "죽녹원", "금산서원", "불국사", "세종 호수"}
    assert not picks & {"대구 고분군", "울산 공원", "대전 생태관", "무등산"}  # 광역시 구 제외
    assert all(n in rows for n in ("대구 고분군", "무등산"))  # 후보가 아닐 뿐 조회 줄(이미지)은 그대로
    assert (rows["금산서원"]["sd"], rows["금산서원"]["sg"]) == ("경북", "포항시")  # 도 소속 시의 구 유지
    assert bil.is_metro_district("광주", "북구") and not bil.is_metro_district("대구", "군위군")
    assert not bil.is_metro_district("경북", "남구") and not bil.is_metro_district("세종", "")


def test_short_desc_sentences_and_cleanup():
    bil = _bil()
    assert bil.short_desc("<p>첫 문장이다.</p>  두 번째<br>문장이다. " + "가" * 200) == "첫 문장이다. 두 번째 문장이다."  # HTML·공백 정리
    long_one = "아주 " * 80 + "긴 문장이다."
    out = bil.short_desc(long_one)
    assert len(out) <= 140 and out.endswith("…") and not out.endswith(" …")  # 첫 문장부터 넘치면 단어 경계에서 자름
    assert len(bil.short_desc(LONG)) <= 140


def test_find_intro_ignores_pick_fields(tmp_path, monkeypatch):
    p = tmp_path / "tour_intro.json"
    rows = [{"n": "영월 청령포", "lat": 37.17, "lng": 128.44, "img": IMG, "pick": 1, "cid": "1", "sd": "강원", "sg": "영월군", "desc": "소개"},
            {"n": "유적", "lat": 36.0, "lng": 128.0, "use_time": "09:00~18:00", "pick": 1, "cid": "2", "sd": "경북", "sg": "경주시", "desc": "소개"}]
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tour_intro, "PATH", p)
    tour_intro._table.cache_clear()
    assert tour_intro.find_intro("영월 청령포", 37.17, 128.44) is None  # 후보 필드만 있는 줄은 이용 정보 없음
    assert tour_intro.find_intro("유적", 36.0, 128.0) == {"use_time": "09:00~18:00"}
    assert tour_intro.find_image("영월 청령포", 37.17, 128.44) == IMG
    tour_intro._table.cache_clear()


# ---------- 날짜별 선택 ----------


def _rows(spec: dict[tuple[str, str], int]) -> list[dict]:
    out, i = [], 0
    for (sd, sg), n in spec.items():
        for _ in range(n):
            i += 1
            out.append({"n": f"{sg or sd} 장소{i}", "lat": 37.0, "lng": 128.0, "img": IMG, "pick": 1, "cid": str(i), "sd": sd, "sg": sg, "desc": "소개"})
    return out


SPEC = {("경북", "경주시"): 20, ("강원", "영월군"): 2, ("전남", "담양군"): 3, ("세종", ""): 1, ("충북", "단양군"): 4}


def test_order_round_robin_by_sigungu():
    rows = _rows(SPEC) + [{"n": "후보 아님", "lat": 1, "lng": 1, "img": IMG}]
    order = dp.build_order(rows)
    assert len(order) == 30 and len({r["cid"] for r in order}) == 30  # 한 바퀴 동안 중복 없음, 후보만
    first = [(r["sd"], r["sg"]) for r in order[:5]]
    assert len(set(first)) == 5  # 첫 바퀴: 장소가 많은 경주시도 한 번, 군 단위도 한 번
    assert [r["cid"] for r in dp.build_order(list(reversed(rows)))] == [r["cid"] for r in order]  # 입력 순서와 무관 (고정 시드)
    assert dp.build_order([]) == []


def test_pick_for_dates():
    order = dp.build_order(_rows(SPEC))
    d = date(2026, 11, 26)
    assert dp.pick_for(d, order) == dp.pick_for(d, order)  # 같은 날짜 같은 결과
    days = [dp.pick_for(d + timedelta(days=i), order) for i in range(len(order))]
    assert len({p["content_id"] for p in days}) == len(order)  # 한 바퀴 동안 중복 없음
    assert dp.pick_for(d + timedelta(days=len(order)), order) == {**days[0], "date": (d + timedelta(days=len(order))).isoformat()}
    start = (dp.PICK_EPOCH - dp.PICK_EPOCH).days
    week = [dp.pick_for(dp.PICK_EPOCH + timedelta(days=start + i), order) for i in range(5)]
    assert len({(p["sido"], p["sigungu"]) for p in week}) == 5  # 연속 날짜는 다른 시군구로 넘어간다
    p = days[0]
    assert p["region"] == " ".join(x for x in (p["sido"], p["sigungu"]) if x) and p["source"] == "한국관광공사"
    assert p["kakao_map_url"].startswith("https://map.kakao.com/link/map/") and p["kakao_map_url"].endswith(",37.0,128.0")
    assert dp.pick_for(d, []) is None


def test_today_kst():
    assert dp.today_kst(datetime(2026, 11, 25, 16, 30, tzinfo=UTC)) == date(2026, 11, 26)  # UTC 16:30 = KST 01:30 다음 날
    assert dp.today_kst(datetime(2026, 11, 25, 14, 59, tzinfo=UTC)) == date(2026, 11, 25)


# ---------- 엔드포인트 ----------


@pytest.fixture
def client(tmp_path, monkeypatch):
    from odiro.api import main

    def use(rows):
        p = tmp_path / "tour_intro.json"
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(tour_intro, "PATH", p)
        dp._order.cache_clear()

    yield TestClient(main.app), use
    dp._order.cache_clear()


def test_daily_pick_endpoint(client, monkeypatch):
    c, use = client
    use(_rows(SPEC))
    r = c.get("/api/daily-pick", params={"date": "2026-11-26"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"date", "content_id", "name", "sido", "sigungu", "region", "description", "image", "lat", "lng", "kakao_map_url", "source"}
    assert body["date"] == "2026-11-26" and body["image"] == IMG and body["source"] == "한국관광공사"
    assert c.get("/api/daily-pick", params={"date": "2026-11-26"}).json() == body
    monkeypatch.setattr(dp, "today_kst", lambda: date(2026, 11, 26))  # date 생략 → KST 오늘
    assert c.get("/api/daily-pick").json() == body
    for bad in ("2026-13-01", "20261126", "2026-11-26T00:00", "내일"):
        assert c.get("/api/daily-pick", params={"date": bad}).status_code == 422


def test_daily_pick_404_without_candidates(client, tmp_path, monkeypatch):
    c, use = client
    use([{"n": "후보 아님", "lat": 1, "lng": 1, "img": IMG}])
    assert c.get("/api/daily-pick", params={"date": "2026-11-26"}).status_code == 404
    monkeypatch.setattr(tour_intro, "PATH", tmp_path / "none.json")
    dp._order.cache_clear()
    assert c.get("/api/daily-pick").status_code == 404
