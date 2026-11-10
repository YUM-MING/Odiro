"""search_place Tool — Kakao Local 키워드 검색 (실존 검증 + 좌표 + 카카오맵 링크).

에이전트의 '할루시네이션 장소 0건' 보장은 이 툴이 책임진다: LLM 이 낸 장소명은 여기서 찾은 것만 살아남는다.
일 30만 회 무료. 응답은 24시간 캐시.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import tool

from odiro.config import settings
from odiro.tools._util import cached, haversine_m, http

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
CACHE_TTL = 24 * 3600

# 카카오 category_group_code → 우리 카테고리
_GROUP_TO_CATEGORY = {
    "FD6": "식당",
    "CE7": "카페",
    "AT4": "관광지",
    "CT1": "문화시설",
    "AD5": "숙소",
    "PK6": "주차장",
    "SW8": "지하철역",
    "MT1": "마트",
    "CS2": "편의점",
    "PO3": "공공기관",
    "AC5": "학원",
    "HP8": "병원",
    "PM9": "약국",
    "BK9": "은행",
    "OL7": "주유소",
    "AG2": "중개업소",
    "SC4": "학교",
    "PS3": "어린이집",
}


def _headers() -> dict[str, str]:
    return {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}


def _normalize(doc: dict[str, Any]) -> dict[str, Any]:
    cat_full = doc.get("category_name", "")
    group = doc.get("category_group_code", "")
    category = _GROUP_TO_CATEGORY.get(group) or (cat_full.split(" > ")[-1] if cat_full else "")
    return {
        "name": doc.get("place_name", ""),
        "kakao_place_id": doc.get("id", ""),
        "category": category,
        "category_group": group,  # FD6 식당 / CE7 카페 / AT4 관광지 / CT1 문화시설 / AD5 숙소 ...
        "category_full": cat_full,
        "address": doc.get("road_address_name") or doc.get("address_name", ""),
        "lat": float(doc["y"]),
        "lng": float(doc["x"]),
        "phone": doc.get("phone", ""),
        "place_url": doc.get("place_url", ""),
        "distance_m": int(doc["distance"]) if doc.get("distance") else None,
    }


def _kakao_keyword(query: str, lat: float | None, lng: float | None, radius_m: int | None, size: int) -> list[dict]:
    if not settings.kakao_rest_api_key:
        raise RuntimeError("KAKAO_REST_API_KEY 없음")
    params: dict[str, Any] = {"query": query, "size": min(max(size, 1), 15)}
    if lat is not None and lng is not None:
        params.update({"y": lat, "x": lng})
        if radius_m:
            params["radius"] = min(radius_m, 20000)
            params["sort"] = "distance" if radius_m <= 3000 else "accuracy"
    r = http().get(KAKAO_KEYWORD_URL, params=params, headers=_headers())
    r.raise_for_status()
    return [_normalize(d) for d in r.json().get("documents", [])]


def search(
    query: str,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int | None = None,
    size: int = 5,
) -> list[dict[str, Any]]:
    """키워드로 장소 검색. 중심좌표가 있으면 거리순(반경 ≤3km) 또는 정확도순."""
    return cached(
        "kakao_kw", CACHE_TTL, lambda: _kakao_keyword(query, lat, lng, radius_m, size), query, lat, lng, radius_m, size
    )


def geocode_region(region: str) -> dict[str, Any] | None:
    """지역명 → 중심 좌표. 행정구역(주소 검색)을 먼저 보고, 없으면 키워드 검색(랜드마크·역 등) 첫 결과.

    '가평' 을 키워드로 먼저 찾으면 '쁘띠프랑스' 같은 명소 좌표가 나와 중심이 치우치므로 주소를 우선한다.
    """

    def _do() -> dict[str, Any] | None:
        r = http().get(KAKAO_ADDRESS_URL, params={"query": region, "size": 1}, headers=_headers())
        r.raise_for_status()
        docs = r.json().get("documents", [])
        if docs:
            d = docs[0]
            return {"lat": float(d["y"]), "lng": float(d["x"]), "label": d.get("address_name", region), "name": region}
        hits = _kakao_keyword(region, None, None, None, 3)
        if hits:
            h = hits[0]
            return {"lat": h["lat"], "lng": h["lng"], "label": h["address"] or h["name"], "name": h["name"]}
        return None

    return cached("kakao_geo", 7 * 24 * 3600, _do, region)


_NORM_RE = re.compile(r"[\s\(\)\[\]·,\.\-_'\"]+")


def _norm_name(s: str) -> str:
    return _NORM_RE.sub("", s).lower()


# 상호 뒤에 흔히 붙는 꼬리말. 비교 전에 떼어낸다 ('가평레일파크 가평점' vs '가평레일파크')
_SUFFIX_RE = re.compile(r"(본점|[가-힣]{1,4}점|카페|cafe|coffee|커피|레스토랑|식당|공원|근린공원)$")
MATCH_THRESHOLD = 0.5


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def name_similarity(a: str, b: str) -> float:
    """정규화된 두 이름의 유사도 0~1. 완전일치 1, 포함 0.85, 그 외 문자 바이그램 Dice (꼬리말 제거 후도 시도)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = min(len(a), len(b)) / max(len(a), len(b))
    # 포함 관계는 길이가 비슷할 때만 인정 ('서울숲'⊂'서울숲공원' OK, '청평호반'⊂'청평호반닭갈비막국수설악점' 은 다른 가게)
    if (a in b or b in a) and ratio >= 0.6:
        return 0.85
    a2, b2 = _SUFFIX_RE.sub("", a) or a, _SUFFIX_RE.sub("", b) or b
    if a2 == b2:
        return 0.9
    ratio2 = min(len(a2), len(b2)) / max(len(a2), len(b2))
    if len(a2) >= 2 and len(b2) >= 2 and (a2 in b2 or b2 in a2) and ratio2 >= 0.6:
        return 0.8
    ga, gb = _bigrams(a2), _bigrams(b2)
    dice = 2 * len(ga & gb) / (len(ga) + len(gb))
    # 짧은 이름이 긴 상호 안에 통째로 들어가면 Dice 가 부풀므로 길이 비율로 눌러준다
    return dice * (0.5 + 0.5 * ratio2)


def verify(
    name: str,
    center_lat: float,
    center_lng: float,
    radius_m: int = 5000,
    hint: str = "",
) -> dict[str, Any] | None:
    """LLM 이 제안한 장소명이 실제로 존재하는지 확인하고 좌표·id 를 돌려준다.

    1) 중심 좌표 반경 내 키워드 검색 → 이름 유사도 높은 것
    2) 없으면 'hint(지역) + name' 으로 전국 검색 후 반경 2배 안쪽만 인정
    """
    target = _norm_name(name)

    def pick(cands: list[dict[str, Any]], max_dist: int) -> dict[str, Any] | None:
        best, best_score = None, 0.0
        for c in cands:
            cn = _norm_name(c["name"])
            if not cn:
                continue
            score = name_similarity(target, cn)
            dist = haversine_m(center_lat, center_lng, c["lat"], c["lng"])
            if dist > max_dist:
                continue
            if score > best_score:
                best, best_score = c, score
        return best if best_score >= MATCH_THRESHOLD else None

    hit = pick(search(name, center_lat, center_lng, radius_m, 10), radius_m)
    if hit:
        return {**hit, "match": "nearby"}
    q = f"{hint} {name}".strip() if hint else name
    hit = pick(search(q, None, None, None, 10), radius_m)
    if hit:
        return {**hit, "match": "wide"}
    return None


@tool
def search_place(query: str, lat: float | None = None, lng: float | None = None, radius_m: int | None = None) -> str:
    """카카오 지도에서 장소를 검색해 실존 여부·좌표·주소·카테고리·카카오맵 링크를 돌려준다.

    Args:
        query: 장소명 또는 '지역 + 업종' 키워드. 예) "성수동 어니언", "서울숲 근처 브런치"
        lat: 중심 위도 (선택). lng 와 함께 주면 가까운 순
        lng: 중심 경도 (선택)
        radius_m: 반경(m, 최대 20000). 중심좌표가 있을 때만 의미 있음
    """
    return json.dumps(search(query, lat, lng, radius_m, size=5), ensure_ascii=False)
