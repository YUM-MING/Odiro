"""summarize_reviews Tool — Tavily 웹검색 + LLM 으로 '조건 관점' 한 줄 리뷰 요약.

- Tavily 월 1,000회 → 장소당 검색 1회, 결과는 7일 캐시. 코스 하나에 4~6회.
- 여러 장소를 한 번의 LLM 호출로 요약 (summarize_many) 해서 지연·비용을 줄인다.
- 실패하면 빈 문자열 (코스 생성은 계속).
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from odiro.config import settings
from odiro.tools._util import cached, http

TAVILY_URL = "https://api.tavily.com/search"
CACHE_TTL = 7 * 24 * 3600


def web_search(query: str, max_results: int = 4, days: int | None = None) -> list[dict[str, Any]]:
    """Tavily 검색 (캐시). 결과: [{title, url, content, published_date?}]"""
    if not settings.tavily_api_key:
        return []

    def _do() -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        if days:
            body["days"] = days
            body["topic"] = "news"
        r = http().post(TAVILY_URL, json=body)
        r.raise_for_status()
        return [
            {"title": x.get("title", ""), "url": x.get("url", ""), "content": (x.get("content") or "")[:600],
             "published_date": x.get("published_date", "")}
            for x in r.json().get("results", [])
        ]

    try:
        return cached("tavily", CACHE_TTL, _do, query, max_results, days)
    except Exception:  # noqa: BLE001
        return []


class _Summary(BaseModel):
    idx: int
    name: str = Field(description="입력에 적힌 장소명 그대로")
    summary: str = Field(description="조건 관점에서 25~45자 한 문장. 근거 없으면 '리뷰 정보 부족'")


class _Summaries(BaseModel):
    items: list[_Summary]


def _llm():
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.llm_model, api_key=settings.anthropic_api_key, temperature=0, timeout=20)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0, timeout=20)


def summarize_many(places: list[dict[str, str]], conditions: str) -> list[str]:
    """places: [{name, region}] → 각 장소의 조건 관점 한 줄 요약. 길이는 입력과 같다."""
    if not places:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(places))) as ex:
        results = list(ex.map(lambda p: web_search(f"{p.get('region', '')} {p['name']} 후기".strip(), 4), places))
    blocks = []
    for i, (p, res) in enumerate(zip(places, results, strict=True)):
        snippets = "\n".join(f"- {r['title']}: {r['content'][:220]}" for r in res[:4]) or "- (검색 결과 없음)"
        blocks.append(f"[{i}] {p['name']}\n{snippets}")
    prompt = (
        f"사용자 조건: {conditions or '일반 데이트/나들이'}\n"
        "아래 장소별 웹 검색 발췌를 읽고, 각 장소를 '사용자 조건 관점'에서 25~45자 한 문장으로 요약하세요. "
        "예) '평일 오후 한산하고 창가 자리에서 서울숲 뷰가 좋다는 평'. 발췌에 근거 없는 내용은 쓰지 말고 "
        "정보가 부족하면 '리뷰 정보 부족'이라고 쓰세요.\n\n" + "\n\n".join(blocks)
    )
    try:
        out: _Summaries = _llm().with_structured_output(_Summaries).invoke(prompt)
    except Exception:  # noqa: BLE001
        return ["" for _ in places]
    # idx 가 어긋나는 경우가 있어 이름으로 먼저 맞추고, 없으면 idx
    result = [""] * len(places)
    norm = lambda s: re.sub(r"\s+", "", s).lower()
    by_name = {norm(p["name"]): i for i, p in enumerate(places)}
    for s in out.items:
        i = by_name.get(norm(s.name))
        if i is None and 0 <= s.idx < len(places):
            i = s.idx
        if i is not None and not result[i]:
            result[i] = s.summary.strip()
    return result


@tool
def summarize_reviews(place_name: str, region: str = "", conditions: str = "") -> str:
    """장소의 최근 웹 리뷰를 검색해 사용자 조건(분위기·웨이팅·아이동반 등) 관점으로 한 줄 요약한다.

    Args:
        place_name: 장소명
        region: 지역 힌트 (동명이인 장소 구분용)
        conditions: 사용자 조건 요약. 예) "조용한 분위기, 웨이팅 적은 곳"
    """
    s = summarize_many([{"name": place_name, "region": region}], conditions)
    return json.dumps({"place": place_name, "summary": s[0] if s else ""}, ensure_ascii=False)
