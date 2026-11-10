"""rag_search Tool — Chroma 큐레이션 문서 검색 (분위기 태그·지역 필터).

사용:
    from odiro.tools.rag_search import rag_search
    rag_search.invoke({"query": "성수동 조용한 카페 데이트", "moods": ["감성/조용한"], "region": "성동구", "k": 5})

    # 또는 순수 함수
    from odiro.tools.rag_search import search
    search("강화도 일몰 드라이브", moods=["뷰맛집/일몰"], region="인천", k=5)

반환: [{doc_id, doc_type, title, snippet, one_line, tags, url, sido_code, sigungu, score, (place) content_id, lat, lng, addr}]

필터 규칙
- moods: 하나라도 붙은 문서 (OR). 빈 리스트면 필터 없음.
- region: "서울", "성동구", "수원", "인천 강화" 같은 자유 텍스트 → 시도/시군구 코드로 해석.
  해석 못 하면 필터 없이 전체 검색 (전국 어디든 동작해야 하므로 실패보다 폴백).
- 광고 문서(is_ad) 는 인덱스 단계에서 이미 제외.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from langchain_core.tools import tool

from odiro.data.ingest import regions
from odiro.data.ingest.build_index import TAG_KEYS, get_vectorstore
from odiro.data.ingest.common import STATE_DIR

# 시도 별칭 → 법정동 코드
_SIDO_ALIASES: dict[str, str] = {
    "서울": "11", "서울시": "11", "서울특별시": "11",
    "인천": "28", "인천시": "28", "인천광역시": "28",
    "경기": "41", "경기도": "41",
    "부산": "26", "대구": "27", "대전": "30", "울산": "31", "세종": "36110",
    "강원": "51", "강원도": "51", "충북": "43", "충남": "44", "전북": "52",
    "전남": "12", "광주": "12", "경북": "47", "경남": "48", "제주": "50", "제주도": "50",
}


@lru_cache(maxsize=1)
def _sigungu_table() -> list[tuple[str, str, str]]:
    """(시도코드, 시군구코드, 시군구이름). tour_api.fetch_sigungu 가 남긴 캐시에서 읽는다."""
    rows: list[tuple[str, str, str]] = []
    for p in STATE_DIR.glob("sigungu_*.json"):
        sido = p.stem.split("_", 1)[1]
        for sg in json.loads(p.read_text(encoding="utf-8")):
            rows.append((sido, sg["code"], sg["name"]))
    return rows


def resolve_region(text: str | None) -> dict[str, str]:
    """자유 텍스트 지역명 → {"sido_code": ..} 또는 {"sido_code":.., "sigungu_code":..}. 모르면 {}."""
    if not text:
        return {}
    t = text.replace(" ", "")
    # 시군구 먼저 (더 구체적). '수원' 이 '수원시' 에, '성동구' 가 '성동구' 에 매칭
    best: tuple[int, dict[str, str]] | None = None
    for sido, code, name in _sigungu_table():
        stem = name[:-1] if len(name) >= 3 and name[-1] in "시군" else name
        for cand in {name, stem}:
            if cand and cand in t:
                # 같은 이름의 구가 여러 시도에 있으면(중구 등) 시도 별칭이 함께 있는 쪽을 우선
                sido_hit = any(a in t and c == sido for a, c in _SIDO_ALIASES.items())
                score = len(cand) + (10 if sido_hit else 0)
                if best is None or score > best[0]:
                    best = (score, {"sido_code": sido, "sigungu_code": code})
    if best:
        return best[1]
    for alias, code in sorted(_SIDO_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in t:
            return {"sido_code": code}
    return {}


def build_filter(moods: list[str] | None, region: str | None) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    reg = resolve_region(region)
    if "sigungu_code" in reg:
        clauses.append({"sido_code": reg["sido_code"]})
        clauses.append({"sigungu_code": reg["sigungu_code"]})
    elif "sido_code" in reg:
        clauses.append({"sido_code": reg["sido_code"]})
    keys = [TAG_KEYS[m] for m in (moods or []) if m in TAG_KEYS]
    if len(keys) == 1:
        clauses.append({keys[0]: True})
    elif keys:
        clauses.append({"$or": [{k: True} for k in keys]})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _format(doc, score: float) -> dict[str, Any]:
    md = doc.metadata
    out = {
        "doc_id": md.get("doc_id"),
        "doc_type": md.get("doc_type"),
        "title": md.get("title"),
        "snippet": doc.page_content.split("\n", 1)[-1][:300],
        "one_line": md.get("one_line", ""),
        "tags": [t for t in (md.get("tags") or "").split("|") if t],
        "url": md.get("url", ""),
        "sido_code": md.get("sido_code", ""),
        "sido": regions.sido_name(md.get("sido_code", "")),
        "sigungu": md.get("sigungu", ""),
        "score": round(float(score), 4),
    }
    if md.get("doc_type") == "place":
        out.update(
            content_id=md.get("content_id"), content_type=md.get("content_type"),
            lat=md.get("lat"), lng=md.get("lng"), addr=md.get("addr"), image=md.get("image"),
        )
    return out


def search(
    query: str,
    moods: list[str] | None = None,
    region: str | None = None,
    k: int = 5,
    doc_type: str | None = None,
) -> list[dict[str, Any]]:
    vs = get_vectorstore()
    where = build_filter(moods, region)
    if doc_type:
        where = {"$and": [where, {"doc_type": doc_type}]} if where else {"doc_type": doc_type}
    # 청크 단위로 넉넉히 받은 뒤 문서 단위로 중복 제거
    hits = vs.similarity_search_with_relevance_scores(query, k=k * 3, filter=where)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for doc, score in hits:
        did = doc.metadata.get("doc_id")
        if did in seen:
            continue
        seen.add(did)
        out.append(_format(doc, score))
        if len(out) >= k:
            break
    if not out and where is not None:  # 필터가 너무 좁으면 지역만 남기고 재시도 → 그래도 없으면 전체
        return search(query, moods=None, region=region, k=k, doc_type=doc_type) if moods else \
            search(query, moods=None, region=None, k=k, doc_type=doc_type) if region else []
    return out


@tool
def rag_search(query: str, moods: list[str] | None = None, region: str | None = None, k: int = 5) -> str:
    """큐레이션 데이터(블로그 글·관광지 설명)에서 분위기 조건에 맞는 장소·글을 찾는다.

    Args:
        query: 자연어 검색어. 예) "성수동 조용한 카페 데이트"
        moods: 분위기 태그 목록. 가능한 값: 감성/조용한, 힙한/트렌디, 뷰맛집/일몰, 레트로, 자연/산책,
               실내(비오는날), 액티비티, 사진맛집, 웨이팅적은, 아이동반, 반려동물
        region: 지역명 (시도 또는 시군구). 예) "서울", "성동구", "수원", "인천 강화"
        k: 반환 문서 수
    """
    return json.dumps(search(query, moods=moods, region=region, k=k), ensure_ascii=False)


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "성수동 조용한 카페 데이트"
    for r in search(q, k=5):
        print(f"[{r['score']:.3f}] ({r['doc_type']}) {r['title']} — {r['one_line']} {r['tags']} {r['sigungu']}")
