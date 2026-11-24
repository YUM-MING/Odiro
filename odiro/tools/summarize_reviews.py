"""summarize_reviews Tool — Tavily 웹검색 + LLM 으로 '조건 관점' 한 줄 리뷰 요약.

- Tavily 월 1,000회 → 장소당 검색 1회, 결과는 7일 캐시. 코스 하나에 4~6회.
- 여러 장소를 한 번의 LLM 호출로 요약 (summarize_many) 해서 지연·비용을 줄인다.
- 실패하면 빈 문자열 (코스 생성은 계속).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from odiro.config import settings
from odiro.tools._util import cached, http

TAVILY_URL = "https://api.tavily.com/search"
CACHE_TTL = 7 * 24 * 3600
log = logging.getLogger(__name__)

# ---------- T1-b: 크레딧 소진·인증 오류면 잠시 Tavily 호출을 멈춘다 ----------
# 같은 프로세스에서 PAUSE_SEC 동안 네트워크 요청 없이 바로 빈 결과 (캐시에 있는 결과는 그대로 쓴다).
# 401·403(인증), 432(플랜 한도)·433(종량제 한도)는 바로 멈춤. 429 는 본문에 크레딧·한도 표현만 있고 rate limit 표현이 없을 때만 멈춤
# (분당 제한 같은 일시적 rate limit·구분 불가는 멈추지 않는다 — 잘못 멈추면 10분 동안 웹 검색이 빈다). 타임아웃·네트워크 오류도 멈추지 않는다.
# 로그·trace 에는 상태 코드와 분류만 남긴다 (키·응답 본문은 남기지 않는다).
PAUSE_SEC = 600
_PAUSE_STATUS = {401: "인증 오류", 403: "인증 오류", 432: "크레딧·한도 초과", 433: "크레딧·한도 초과"}
_CREDIT_WORDS = re.compile(r"credit|quota|usage limit|plan'?s? (?:set )?(?:usage )?limit|monthly|billing|upgrade", re.IGNORECASE)
_RATE_WORDS = re.compile(r"rate.?limit|too many requests|per (?:minute|second)|slow down|try again", re.IGNORECASE)
_pause: dict[str, Any] = {"until": 0.0, "status": 0, "kind": ""}
_pause_lock = threading.Lock()


def _now() -> float:
    return time.time()


class _Paused(Exception):
    """Tavily 호출 멈춤 중 (네트워크 요청 없이 빈 결과)."""


def _pause_kind(status: int, text: str) -> str | None:
    """오류 응답 → 멈출 이유 또는 None (멈추지 않음)."""
    if status in _PAUSE_STATUS:
        return _PAUSE_STATUS[status]
    if status == 429 and _CREDIT_WORDS.search(text or "") and not _RATE_WORDS.search(text or ""):
        return "크레딧·한도 초과"
    return None


def pause_status() -> str:
    """멈춘 상태면 trace 용 한 줄 (상태 코드·분류·남은 시간), 아니면 빈 문자열."""
    with _pause_lock:
        left = _pause["until"] - _now()
        if left <= 0:
            return ""
        return f"Tavily 일시 중단(HTTP {_pause['status']}, {_pause['kind']}, 약 {max(1, round(left / 60))}분 남음)"


def web_search(query: str, max_results: int = 4, days: int | None = None) -> list[dict[str, Any]]:
    """Tavily 검색 (캐시). 결과: [{title, url, content, published_date?}]"""
    if not settings.tavily_api_key:
        return []

    def _do() -> list[dict[str, Any]]:
        if pause_status():
            raise _Paused()
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
        if r.status_code >= 400:
            kind = _pause_kind(r.status_code, r.text if r.status_code == 429 else "")
            if kind:
                with _pause_lock:
                    _pause.update(until=_now() + PAUSE_SEC, status=r.status_code, kind=kind)
                log.warning("Tavily 호출 %d분 중단 (HTTP %d, %s)", PAUSE_SEC // 60, r.status_code, kind)
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


_NAME_NORM_RE = re.compile(r"[\s\(\)\[\]·,\.\-_&'\"]+")


def mentions(name: str, text: str) -> bool:
    """text 가 그 장소를 언급하는지. 지점명·수식어가 붙는 경우가 많아 상호의 첫 단어(2자 이상)가 들어 있으면 인정한다."""
    norm = lambda s: _NAME_NORM_RE.sub("", s).lower()
    head = norm(name.split()[0]) if name.split() else ""
    if head.endswith("맛집"):  # '송도맛집' 같은 상호는 "송도 맛집 추천" 류 글에 전부 걸려서 근거가 못 된다
        return False
    return len(head) >= 2 and head in norm(text)


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
    """places: [{name, region, category?}] → 각 장소의 조건 관점 한 줄 요약. 길이는 입력과 같다."""
    if not places:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(places))) as ex:
        results = list(ex.map(lambda p: web_search(f"{p.get('region', '')} {p['name']} 후기".strip(), 4), places))
    # 검색 결과에는 이름만 비슷한 다른 가게·무관한 글이 많이 섞인다 → 그 장소를 언급한 발췌만 남긴다
    results = [[r for r in res if mentions(p["name"], f"{r['title']} {r['content']}")] for p, res in zip(places, results, strict=True)]
    if not any(results):  # T1-a: 근거 발췌가 하나도 없으면 LLM 요약을 부르지 않는다 (나와도 근거가 없어 전부 버려진다)
        return ["" for _ in places]
    blocks = []
    for i, (p, res) in enumerate(zip(places, results, strict=True)):
        snippets = "\n".join(f"- {r['title']}: {r['content'][:220]}" for r in res[:4]) or "- (검색 결과 없음)"
        kind = f" (업종: {p['category']})" if p.get("category") else ""
        blocks.append(f"[{i}] {p['name']}{kind}\n{snippets}")
    prompt = (
        f"사용자 조건: {conditions or '일반 데이트/나들이'}\n"
        "아래 장소별 웹 검색 발췌를 읽고, 각 장소를 '사용자 조건 관점'에서 25~45자 한 문장으로 요약하세요. "
        "예) '평일 오후 한산하고 창가 자리에서 서울숲 뷰가 좋다는 평'. 발췌에 근거 없는 내용은 쓰지 말고 "
        "정보가 부족하면 '리뷰 정보 부족'이라고 쓰세요. "
        "이름이 비슷한 다른 곳(호텔·다른 지점 등 업종이 다른 대상)에 대한 발췌는 무시하고, 그것밖에 없으면 '리뷰 정보 부족'. "
        "발췌에 없는 실내/야외 여부를 지어내지 마세요 (공원·수목원·호수·거리는 야외입니다).\n\n" + "\n\n".join(blocks)
    )
    try:
        out: _Summaries = _llm().with_structured_output(_Summaries).invoke(prompt)
    except Exception:  # noqa: BLE001
        return ["" for _ in places]
    # idx 가 어긋나는 경우가 있어 이름으로 먼저 맞추고, 없으면 idx
    result = [""] * len(places)
    has_source = [bool(res) for res in results]
    norm = lambda s: re.sub(r"\s+", "", s).lower()
    by_name = {norm(p["name"]): i for i, p in enumerate(places)}
    for s in out.items:
        i = by_name.get(norm(s.name))
        if i is None and 0 <= s.idx < len(places):
            i = s.idx
        if i is not None and not result[i] and has_source[i]:  # 근거 발췌가 없는데 나온 요약은 버린다
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
