"""TourAPI 지역·분류 코드표.

TourAPI 4.0(KorService2) 은 구 `areaCode` 대신 **법정동 시도코드(`lDongRegnCd`)** 를 쓴다.
(`areaCode` 로 조회하면 서울이 1,057건, `lDongRegnCd=11` 로 조회하면 8,008건 — 2026-11 확인)

시도 목록은 `ldongCode2` 로 조회할 수 있지만, 네트워크 없이도 CLI 인자 검증이 되도록 여기 고정해 둔다.
시군구 목록은 `tour_api.fetch_sigungu()` 로 받아 캐시한다 (수도권 66개).
"""

from __future__ import annotations

# 법정동 시도코드 -> 이름 (2026-11 ldongCode2 응답 기준. 전남+광주 통합(12), 세종은 5자리(36110))
SIDO: dict[str, str] = {
    "11": "서울",
    "28": "인천",
    "41": "경기",
    "26": "부산",
    "27": "대구",
    "30": "대전",
    "31": "울산",
    "36110": "세종",
    "51": "강원",
    "43": "충북",
    "44": "충남",
    "52": "전북",
    "12": "전남광주",
    "47": "경북",
    "48": "경남",
    "50": "제주",
}

# 1주차 담당 (수도권). 2주차는 `--all` 로 나머지.
CAPITAL_AREA: tuple[str, ...] = ("11", "28", "41")
OTHER_AREAS: tuple[str, ...] = tuple(c for c in SIDO if c not in CAPITAL_AREA)

# 콘텐츠타입 코드 -> 이름
CONTENT_TYPES: dict[int, str] = {
    12: "관광지",
    14: "문화시설",
    15: "행사",
    25: "여행코스",
    28: "레포츠",
    32: "숙박",
    38: "쇼핑",
    39: "음식점",
}

# 코스 후보로 쓸 가치가 높은 순. 상세(overview) 사전 수집도 이 순서로 한다.
# 쇼핑(38)은 수도권에서만 8천 건이고 대부분 시장·상가라 뒤로 보낸다.
DETAIL_PRIORITY: tuple[int, ...] = (12, 14, 39, 28, 15, 32, 25, 38)

# 블로그 수집·라벨링에 쓰는 분위기 테마 (DATA_AND_API.md 3번과 동일 체계)
MOOD_TAGS: tuple[str, ...] = (
    "감성/조용한",
    "힙한/트렌디",
    "뷰맛집/일몰",
    "레트로",
    "자연/산책",
    "실내(비오는날)",
    "액티비티",
    "사진맛집",
    "웨이팅적은",
    "아이동반",
    "반려동물",
    "광고성(제외용)",
)


def sido_name(code: str) -> str:
    return SIDO.get(code, code)


def parse_area_args(areas: list[str] | None, all_areas: bool) -> list[str]:
    """CLI 의 --area / --all 을 시도코드 목록으로. 기본은 수도권."""
    if all_areas:
        return list(OTHER_AREAS) if areas is None else list(SIDO)
    if not areas:
        return list(CAPITAL_AREA)
    bad = [a for a in areas if a not in SIDO]
    if bad:
        raise SystemExit(f"알 수 없는 시도코드 {bad}. 가능한 값: {', '.join(f'{k}={v}' for k, v in SIDO.items())}")
    return areas
