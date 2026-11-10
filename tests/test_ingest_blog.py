"""naver_blog 쿼리 생성·광고 플래그·정규화 단위 테스트 (네트워크 없음)."""

from odiro.data.ingest.naver_blog import (
    THEMES,
    build_queries,
    is_ad_suspect,
    is_off_region,
    merge_post,
    normalize_post,
    query_region_name,
)


def test_query_region_name():
    assert query_region_name("수원시") == "수원"
    assert query_region_name("가평군") == "가평"
    assert query_region_name("성동구") == "성동구"
    assert query_region_name("중구") == "중구"  # 2글자는 그대로
    assert query_region_name("시흥시") == "시흥"


def test_build_queries_seoul_prefix_and_count():
    qs = build_queries("11", [{"code": "110", "name": "종로구"}, {"code": "200", "name": "성동구"}])
    assert len(qs) == 2 * len(THEMES)
    assert qs[0]["query"].startswith("서울 종로구 ")
    assert {q["theme"] for q in qs} == set(THEMES)


def test_build_queries_gyeonggi_no_prefix():
    qs = build_queries("41", [{"code": "110", "name": "수원시"}])
    assert qs[0]["query"].startswith("수원 ")
    assert qs[0]["sigungu"] == "수원시"


def test_ad_suspect():
    assert is_ad_suspect("성수 카페 추천", "업체로부터 소정의 원고료를 제공받아 작성")
    assert is_ad_suspect("[광고] 성수동 맛집", "")
    assert not is_ad_suspect("성수동 조용한 카페 5곳", "주말에 다녀온 후기입니다. 사람 적고 분위기 좋아요")


def test_normalize_and_merge():
    q1 = {"query": "서울 성동구 데이트 코스", "theme": "데이트", "sigungu_code": "200", "sigungu": "성동구"}
    q2 = {"query": "서울 성동구 조용한 감성 카페", "theme": "감성/조용한", "sigungu_code": "200", "sigungu": "성동구"}
    item = {
        "title": "<b>성수동</b> 데이트 코스 추천",
        "link": "https://blog.naver.com/a/1",
        "description": "서울숲 &amp; 카페 거리 후기",
        "bloggername": "민지",
        "postdate": "20261001",
    }
    p1 = normalize_post(item, q1, "11")
    assert p1["title"] == "성수동 데이트 코스 추천"
    assert p1["description"] == "서울숲 & 카페 거리 후기"
    assert p1["themes"] == ["데이트"] and p1["ad_suspect"] is False
    merged = merge_post(p1, normalize_post(item, q2, "11"))
    assert merged["themes"] == ["데이트", "감성/조용한"]
    assert len(merged["queries"]) == 2


def test_off_region():
    assert is_off_region("대전시 실내 아이와 갈 만한 곳 총정리", "대전 유성구 ...", "28")
    assert is_off_region("부산 연제만화도서관", "초4 아들과", "28")
    assert not is_off_region("송도 실내 가볼만한곳 송도국제도서관", "비 오는 주말에", "28")
    assert not is_off_region("서울 근교 양평 당일치기", "두물머리부터 북한강", "41")  # 수도권 교차 언급은 OK
    assert not is_off_region("인천 여행 월미도", "부산 사람의 인천 방문기", "28")  # 자기 시도 언급 있으면 OK
