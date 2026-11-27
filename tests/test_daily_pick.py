"""오늘의 숨은 여행지: 후보 선정(build_intro_lookup) · 날짜별 선택(daily_pick) · GET /api/daily-pick. 외부 API 호출 없음."""

from __future__ import annotations

import importlib.util
import itertools
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


def test_sigungu_from_address_forms():
    bil = _bil()
    cases = {
        "전라남도 곡성군 오곡면": "곡성군",
        "전남 곡성군 곡성읍": "곡성군",
        "전남광주통합특별시 곡성군 입면 청계동로": "곡성군",
        "곡성군 곡성읍 신기리 산 190-1": "곡성군",  # 시도 없이 시군구로 시작
        "전북특별자치도 전주시 완산구 효자동": "전주시",
        "전라북도 김제시 죽산면": "김제시",
        "강원특별자치도 강릉시 주문진읍": "강릉시",
        "경상북도 경주시 진현동": "경주시",
        "충청남도 공주시 웅진동": "공주시",
        "닫기 경상북도 영덕군 영해면": "영덕군",  # 앞에 잡음이 붙은 주소
        "세종특별자치시 조치원읍": "",
        "제주특별자치도": "",
        "": "",
    }
    for addr, sg in cases.items():
        assert bil.sigungu_name(addr) == sg, addr
    # 전남·광주(코드 12): 통합 뒤 주소 접두어가 같아 시군구로 가른다
    assert bil.sido_short("12", "전남광주통합특별시 북구 금곡동", "북구") == "광주"
    assert bil.sido_short("12", "전남광주통합특별시 곡성군 입면", "곡성군") == "전남"
    assert bil.sido_short("12", "곡성군 곡성읍", "곡성군") == "전남"
    assert bil.sido_short("52", "전북특별자치도 전주시", "전주시") == "전북"
    assert bil.sido_short("51", "강원특별자치도 강릉시", "강릉시") == "강원"


def test_pick_sigungu_from_code_and_skip_unknown(tmp_path, monkeypatch):
    bil = _bil()
    tour = tmp_path / "tour"
    tour.mkdir()
    _write(tour, "12", [
        # 같은 시군구 코드(720)의 다른 장소 주소에서 '곡성군' 을 알아내 시도 없는 주소에도 쓴다 (코드 기반 우선)
        _place("1", "국립곡성치유의숲", sido="12", addr="전남광주통합특별시 곡성군 곡성읍 청계동로 519", sigungu_code="720"),
        _place("2", "청계동계곡", sido="12", addr="곡성군 곡성읍 신기리 산 190-1", sigungu_code="720"),
        _place("3", "무등산 자락", sido="12", addr="전남광주통합특별시 북구 금곡동", sigungu_code="170"),  # 광주 자치구 → 제외
        _place("4", "주소 없는 곳", sido="12", addr="", sigungu_code=""),  # 시군구를 못 얻음 → 후보 제외
    ], {"1": LONG, "2": LONG, "3": LONG, "4": LONG})
    _write(tour, "36110", [_place("5", "세종 호수", sido="36110", addr="세종특별자치시 연기면 세종리", sigungu_code="")], {"5": LONG})
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    monkeypatch.setattr(bil, "SIGUNGU_DIRS", ())  # 공식 코드표 없이
    rows = {r["n"]: r for r in bil.build()}
    assert (rows["청계동계곡"]["sd"], rows["청계동계곡"]["sg"]) == ("전남", "곡성군")
    assert (rows["국립곡성치유의숲"]["sd"], rows["국립곡성치유의숲"]["sg"]) == ("전남", "곡성군")
    assert "pick" not in rows["무등산 자락"]  # '전남 북구' 로 잘못 들어가지 않고 광주 자치구로 빠진다
    assert "주소 없는 곳" in rows and "pick" not in rows["주소 없는 곳"]  # 이미지 조회 줄은 남고 후보만 빠진다
    assert bil.SKIPPED_NO_SIGUNGU == {"전남": 1}
    assert (rows["세종 호수"]["sd"], rows["세종 호수"]["sg"]) == ("세종", "")  # 세종은 시군구 없이 유지


def test_pick_official_sigungu_table_first(tmp_path, monkeypatch):
    bil = _bil()
    tour = tmp_path / "tour"
    tour.mkdir()
    sgdir = tmp_path / "sigungu"
    sgdir.mkdir()
    (sgdir / "sigungu_47.json").write_text(json.dumps([{"code": "111", "name": "포항시 남구"}], ensure_ascii=False), encoding="utf-8")
    _write(tour, "47", [_place("1", "호미곶", sido="47", addr="호미곶면 대보리", sigungu_code="111")], {"1": LONG})  # 주소로는 못 얻음
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    monkeypatch.setattr(bil, "SIGUNGU_DIRS", (sgdir,))
    rows = {r["n"]: r for r in bil.build()}
    assert (rows["호미곶"]["sd"], rows["호미곶"]["sg"]) == ("경북", "포항시")  # 공식 코드표 이름(첫 단어)


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
        dp._orders.cache_clear()

    yield TestClient(main.app), use
    dp._orders.cache_clear()


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
    dp._orders.cache_clear()
    assert c.get("/api/daily-pick").status_code == 404


# ---------- 계절 필터: 추운 달에는 물놀이 위주 장소를 건너뛴다 ----------


def _seq(names_wet):
    return [{"n": n, "lat": 37.0, "lng": 128.0, "img": IMG, "pick": 1, "cid": str(i), "sd": "강원", "sg": f"군{i}", "desc": "소개",
             **({"wet": 1} if wet else {})} for i, (n, wet) in enumerate(names_wet)]


def _days(start, n):
    import datetime as _dt
    return [start + _dt.timedelta(days=i) for i in range(n)]


def test_cold_month_uses_order_without_wet_places():
    import datetime as _dt
    seq = _seq([("용담계곡", True), ("합강정", False), ("망상해수욕장", True), ("청령포", False), ("월정사", False), ("옥계해변", True)])
    cold = [r["n"] for r in dp.cold_order(seq)]
    assert cold == ["합강정", "청령포", "월정사"]  # 전체 순서에서 물놀이만 뺀 상대 순서 그대로
    dec = _days(_dt.date(2026, 12, 1), 30)
    names = [dp.pick_for(d, seq)["name"] for d in dec]
    assert not {"용담계곡", "망상해수욕장", "옥계해변"} & set(names)  # 추운 달에는 물놀이 장소 없음
    assert all(a != b for a, b in itertools.pairwise(names))  # 연속 날짜에 같은 장소가 연달아 나오지 않음
    assert len(set(names[:3])) == 3  # 한 바퀴(추운 달 순서 길이) 동안 중복 없음
    assert [dp.pick_for(d, seq)["name"] for d in dec] == names  # 같은 날짜 같은 결과
    for d in _days(_dt.date(2027, 3, 1), 31):  # 3월도 추운 달
        assert not dp.is_wet({"n": dp.pick_for(d, seq)["name"]})
    jul = _days(_dt.date(2027, 7, 1), 6)
    assert {dp.pick_for(d, seq)["name"] for d in jul} == {r["n"] for r in seq}  # 7월은 계곡 포함 전체 순서
    d = _dt.date(2027, 7, 10)
    assert dp.pick_for(d, seq)["name"] == seq[(d - dp.PICK_EPOCH).days % len(seq)]["n"]


def test_cold_order_in_memory_and_no_repeat_on_real_order(tmp_path, monkeypatch):
    import datetime as _dt
    rows = _rows(SPEC)
    for r in rows[::3]:
        r["wet"] = 1
    p = tmp_path / "tour_intro.json"
    p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tour_intro, "PATH", p)
    dp._orders.cache_clear()
    full, cold = dp._orders()
    assert len(full) == 30 and len(cold) == 20 and not any(dp.is_wet(r) for r in cold)
    assert dp._orders() is dp._orders()  # 한 번 만들어 메모리에 둔다
    picks = [dp.pick_for(d)["content_id"] for d in _days(_dt.date(2026, 12, 1), 20)]
    assert len(set(picks)) == 20  # 한 바퀴 동안 중복 없음
    dp._orders.cache_clear()


def test_wet_by_name_and_waterfall_kept():
    import datetime as _dt
    seq = _seq([("동강 래프팅 계곡", False), ("비룡폭포 계곡", False), ("오대산 해변", False), ("옥계 물놀이장", False), ("월정사", False)])
    assert dp.is_wet(seq[0]) and dp.is_wet(seq[2]) and dp.is_wet(seq[3])  # 표시가 없는 옛 파일도 이름으로 판별
    assert not dp.is_wet(seq[1]) and not dp.is_wet(seq[4])  # 폭포는 빼지 않는다
    assert [r["n"] for r in dp.cold_order(seq)] == ["비룡폭포 계곡", "월정사"]
    assert {dp.pick_for(d, seq)["name"] for d in _days(_dt.date(2026, 12, 1), 10)} == {"비룡폭포 계곡", "월정사"}


def test_all_wet_falls_back_to_original():
    seq = _seq([("A계곡", True), ("B해수욕장", True)])
    import datetime as _dt
    day = _dt.date(2026, 12, 2)
    base = seq[(day - dp.PICK_EPOCH).days % 2]["n"]
    assert dp.cold_order(seq) == ()
    assert dp.pick_for(day, seq)["name"] == base  # 추운 달 순서가 비면 전체 순서로 폴백 (배너가 비지 않게)


def test_build_marks_wet_candidates(tmp_path, monkeypatch):
    bil = _bil()
    tour = tmp_path / "tour"
    tour.mkdir()
    _write(tour, "51", [
        _place("1", "용담계곡", lcls3="NA010400"),
        _place("2", "망상", lcls3="NA020900"),  # 이름에 단어가 없어도 분류 코드로
        _place("3", "옥계 물놀이장", lcls3=""),  # 분류가 없으면 이름으로
        _place("4", "구룡폭포", lcls3="NA010400"),  # 폭포는 아님
        _place("5", "청령포", lcls3="HS010100", lcls1="HS"),
    ], {k: LONG for k in "12345"})
    monkeypatch.setattr(bil, "TOUR_DIR", tour)
    rows = {r["n"]: r for r in bil.build()}
    assert {n for n, r in rows.items() if r.get("wet")} == {"용담계곡", "망상", "옥계 물놀이장"}
    assert all(r.get("pick") for r in rows.values())
