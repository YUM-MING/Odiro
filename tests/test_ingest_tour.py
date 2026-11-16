"""tour_api 파싱·정규화 단위 테스트 (네트워크 없음)."""

import pytest

from odiro.data.ingest import regions
from odiro.data.ingest.tour_api import (
    QuotaExceeded,
    TourApiError,
    clean_text,
    normalize_detail,
    normalize_intro,
    normalize_place,
    parse_body,
)

SAMPLE_ITEM = {
    "addr1": "서울특별시 종로구 사직로 161",
    "addr2": "(세종로)",
    "areacode": "1",
    "cat1": "A02",
    "cat2": "A0201",
    "cat3": "A02010100",
    "contentid": "126508",
    "contenttypeid": "12",
    "createdtime": "20031106000000",
    "firstimage": "http://tong.visitkorea.or.kr/cms/resource/1.jpg",
    "firstimage2": "http://tong.visitkorea.or.kr/cms/resource/1_thumb.jpg",
    "lDongRegnCd": "11",
    "lDongSignguCd": "110",
    "lclsSystm1": "HS",
    "lclsSystm2": "HS01",
    "lclsSystm3": "HS010100",
    "mapx": "126.9769930325",
    "mapy": "37.5788222356",
    "mlevel": "6",
    "modifiedtime": "20250101120000",
    "sigungucode": "23",
    "tel": "02-3700-3900",
    "title": "경복궁",
    "zipcode": "03045",
}


def _ok_payload(items, total):
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {"items": {"item": items} if items else "", "numOfRows": 1000, "pageNo": 1, "totalCount": total},
        }
    }


def test_parse_body_ok():
    rows, total = parse_body(_ok_payload([SAMPLE_ITEM], 769))
    assert total == 769
    assert rows[0]["contentid"] == "126508"


def test_parse_body_empty_items_is_string():
    rows, total = parse_body(_ok_payload([], 0))
    assert rows == [] and total == 0


def test_parse_body_single_dict_item():
    payload = _ok_payload([SAMPLE_ITEM], 1)
    payload["response"]["body"]["items"]["item"] = SAMPLE_ITEM  # 1건일 때 dict 로 오는 케이스
    rows, _ = parse_body(payload)
    assert len(rows) == 1


def test_parse_body_auth_error():
    payload = {
        "OpenAPI_ServiceResponse": {
            "cmmMsgHeader": {
                "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                "returnAuthMsg": "등록되지 않은 서비스키",
                "returnReasonCode": "30",
            }
        }
    }
    with pytest.raises(TourApiError, match="등록되지 않은 서비스키"):
        parse_body(payload)


def test_parse_body_quota_error_is_quota_exceeded():
    payload = {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"returnReasonCode": "22", "returnAuthMsg": "한도 초과"}}}
    with pytest.raises(QuotaExceeded):
        parse_body(payload)


def test_normalize_place():
    p = normalize_place(SAMPLE_ITEM)
    assert p["content_id"] == "126508"
    assert p["title"] == "경복궁"
    assert p["content_type_id"] == 12 and p["content_type"] == "관광지"
    assert p["sido_code"] == "11" and p["sigungu_code"] == "110"
    assert p["addr"] == "서울특별시 종로구 사직로 161 (세종로)"
    assert p["lat"] == pytest.approx(37.5788, abs=1e-3)
    assert p["lng"] == pytest.approx(126.9770, abs=1e-3)
    assert p["source"] == "tourapi"


def test_normalize_place_missing_coords():
    p = normalize_place({**SAMPLE_ITEM, "mapx": "", "mapy": None})
    assert p["lat"] is None and p["lng"] is None


def test_normalize_detail_strips_html():
    d = normalize_detail(
        {
            "contentid": "126508",
            "overview": "조선의 법궁.<br>경복궁은&nbsp;1395년에 <b>창건</b>되었다.\n\n넓다.",
            "homepage": '<a href="https://royal.khs.go.kr/" target="_blank">https://royal.khs.go.kr/</a>',
        }
    )
    assert d["overview"] == "조선의 법궁. 경복궁은 1395년에 창건 되었다. 넓다."
    assert d["homepage"] == "https://royal.khs.go.kr/"


def test_clean_text_none():
    assert clean_text(None) == ""


def test_clean_text_unescapes_entities():
    assert clean_text("&quot;마!&quot; 월미도 <b>후기</b>&nbsp;&#39;카페&#39; &amp; 바다") == "\"마!\" 월미도 후기 '카페' & 바다"



def test_parse_area_args_defaults_to_capital():
    assert regions.parse_area_args(None, False) == ["11", "28", "41"]


def test_parse_area_args_all_excludes_capital():
    areas = regions.parse_area_args(None, True)
    assert "11" not in areas and "26" in areas


def test_parse_area_args_rejects_unknown():
    with pytest.raises(SystemExit):
        regions.parse_area_args(["99"], False)


def test_normalize_intro_tourist_spot():
    r = normalize_intro({"contentid": "1", "contenttypeid": 12, "restdate": "매주 월요일", "usetime": "09:00~18:00",
                         "parking": "가능", "chkpet": "불가", "infocenter": "02-1"})
    assert r["rest_date"] == "매주 월요일" and r["use_time"] == "09:00~18:00"
    assert r["parking"] == "가능" and r["pet"] == "불가" and r["use_fee"] == ""


def test_normalize_intro_suffixed_fields_and_parking_fee():
    r = normalize_intro({"contentid": "2", "contenttypeid": 14, "restdateculture": "연중무휴", "usefee": "5,000원",
                         "parkingculture": "가능", "parkingfee": "무료", "chkpetculture": "가능"})
    assert r["rest_date"] == "연중무휴" and r["use_fee"] == "5,000원"
    assert r["parking"] == "가능" and r["parking_fee"] == "무료"


def test_normalize_intro_empty_values_stay_empty():
    r = normalize_intro({"contentid": "3", "contenttypeid": 28, "restdateleports": "", "usetimeleports": " ",
                         "parkingfeeleports": "무료"})
    assert r["rest_date"] == "" and r["use_time"] == "" and r["parking"] == "" and r["parking_fee"] == "무료"


def test_normalize_intro_festival_fee_not_use_time():
    r = normalize_intro({"contentid": "4", "contenttypeid": 15, "usetimefestival": "무료", "playtime": "10:00~18:00"})
    assert r["use_fee"] == "무료" and r["use_time"] == "10:00~18:00"
