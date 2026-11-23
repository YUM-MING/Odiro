"""LangGraph 노드 구현.

parse_intent → retrieve(RAG ∥ 웹 ∥ 날씨 ∥ 일출) → draft_course → verify_places(예비 후보로 채우고 부족하면 LLM 1회 보충)
    → optimize_route → enrich → compose_answer
modify(수정 요청) → verify_places → optimize_route → enrich → compose_answer

상태(state)는 dict 로 다룬다 (odiro.agent.state.CourseState 키). 각 노드는 바뀐 키만 돌려준다.
모든 외부 호출은 Tool 쪽에서 타임아웃·캐시·폴백을 책임지고, 노드는 '실패해도 다음 단계가 돌아가게' 만 신경 쓴다.
"""

from __future__ import annotations

import itertools
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from odiro.agent.llm import chat
from odiro.api.schemas import MOODS
from odiro.config import settings
from odiro.tools import get_route, get_sun_times, get_weather, search_place, summarize_reviews
from odiro.tools import rag_search as rag
from odiro.tools._util import estimate_minutes, haversine_m

log = logging.getLogger("odiro.agent")

MAX_VERIFY_ROUNDS = 1  # 예비 후보(spares)로 먼저 채우고, 그래도 비면 LLM 보충 1회
MAX_PLACES_PER_DAY = 6
MAX_PLACES_PER_DAY_TRIP = 5
MIN_PLACES_PER_DAY = 3
SLOT_MIN = 105  # 장소 하나당 평균 소요(체류 60~90분 + 이동)
SPARES_PER_DAY = 3
VERIFY_RADIUS = {"walk": 1500, "car": 30000}
# 카카오 카테고리 대분류 중 코스 장소가 될 수 없는 것 (이름이 완전히 같으면 예외)
NON_VENUE_TOP_CATEGORIES = {"부동산", "의료,건강", "금융,보험", "행정,사회기관", "교육,학문", "서비스,산업", "가정,생활", "교통,수송"}
WALK_OUTLIER_M = 1100  # 뚜벅이: 그날 동선의 한가운데 장소에서 직선으로 이보다 멀면(도보 약 20분+) 동선에서 뺀다
# RAG 장소 문서를 중심에서 이 거리 안쪽만 쓴다. "인천 송도" 처럼 동 단위 요청은 시도 전체가 검색돼 코스가 퍼지기 때문.
RAG_RADIUS_M = {"walk": 1500, "car_local": 8000, "car_wide": 30000}
PLAY_CATEGORIES = {"관광지", "놀거리", "산책", "쇼핑", "기타"}  # 비 예보 때 실내 여부를 따지는 역할 (식당·카페·숙소는 실내로 본다)


# ---------- LLM 출력 스키마 ----------


class DraftPlace(BaseModel):
    name: str = Field(description="실제 존재하는 구체적 상호/장소명. 체인점이면 지점명까지. 예) '어니언 성수', '서울숲'")
    category: Literal["식당", "카페", "관광지", "놀거리", "산책", "쇼핑", "숙소", "기타"]
    reason: str = Field(description="이 조건에 왜 맞는지 1문장 (근거 문서가 있으면 그 내용으로)")
    stay_min: int = Field(60, ge=20, le=180)
    est_cost: int = Field(0, ge=0, le=300000, description="1인 예상 비용(원): 식당은 대표 메뉴 1인분, 카페는 음료+디저트, 관광지·체험은 입장료/체험비. 무료면 0. 정확히 모르면 업종 평균으로 추정")
    indoor: bool = Field(True, description="실내에서 머무는 곳이면 true (전시·박물관·식당·카페·쇼핑몰·실내 체험). 공원·수목원·호수·섬·산책로·전망대·야외 거리는 false")
    tags: list[str] = Field(default_factory=list, description=f"해당하는 분위기 태그. 가능한 값: {', '.join(MOODS)}")
    source: Literal["rag", "web", "llm"] = Field("llm", description="근거 출처: 제공된 큐레이션 문서=rag, 웹검색=web, 일반지식=llm")


class DraftDay(BaseModel):
    day: int = 1
    places: list[DraftPlace] = Field(description="방문 순서대로, 요구된 개수만큼")
    spares: list[DraftPlace] = Field(default_factory=list, description="지도 확인에 실패할 때 대신 쓸 예비 후보 2~3개 (역할 다양하게)")


class CourseDraft(BaseModel):
    title: str = Field(description="코스 제목 (15자 이내, 감성적으로)")
    days: list[DraftDay]


class Replacement(BaseModel):
    slot: int = Field(description="교체할 후보의 인덱스 (입력에서 준 번호)")
    place: DraftPlace


class Replacements(BaseModel):
    items: list[Replacement]


class MustHave(BaseModel):
    keywords: list[str] = Field(
        default_factory=list,
        description="자유 조건이 '특정 종류의 장소·체험' 을 원할 때 그것을 지도 앱에서 찾을 검색어 1~3개 (짧은 업종명, 지역명 제외). "
        "예) '반지공방' → ['반지공방', '커플링공방'] / '비건 메뉴 꼭' → ['비건식당'] / '보드게임 하고 싶어' → ['보드게임카페']. "
        "장소 종류가 아닌 조건(주차 편한 곳, 조용하게, 많이 안 걷게)은 빈 목록. "
        "분위기·성격 수식어가 붙은 평범한 카페·식당('조용한 카페', '분위기 좋은 식당', '뷰 좋은 카페')도 빈 목록 — 분위기는 따로 태그로 처리하고 카페·식당은 코스에 원래 들어간다. "
        "특별한 업종(공방·보드게임카페·키즈카페·스터디카페·비건식당)일 때만 채운다",
    )


MOOD_MODEL = "gpt-4o"  # 분위기 태그 변환 전용: gpt-4o-mini 는 문장에 없는 태그를 갖다 붙인다 (11/21 확인). 호출이 짧아 비용은 미미
MoodTag = Literal[MOODS]  # type: ignore[valid-type]  # 자유 단어('차분한')가 아니라 태그 11개 중에서만 고르게 스키마로 막는다


MOOD_GUIDE = """태그와 뜻:
- 감성/조용한: 조용한, 한적한, 잔잔한, 아늑한, 차분한, 카공(공부·작업하기 좋은)
- 힙한/트렌디: 핫플, 요즘 뜨는, 힙한, 트렌디한
- 뷰맛집/일몰: 뷰가 좋은, 전망, 노을·일몰, 야경
- 레트로: 옛날 감성, 레트로, 빈티지
- 자연/산책: 자연, 산책, 공원, 숲, 걷기 좋은
- 실내(비오는날): 실내, 비 오는 날
- 액티비티: 몸으로 하는 체험·활동
- 사진맛집: 사진 찍기 좋은, 포토스팟
- 웨이팅적은: 줄 안 서는, 웨이팅 없는, 한산한, 사람 적은
- 아이동반: 아이와 함께, 키즈
- 반려동물: 강아지·반려동물 동반"""


class MoodHit(BaseModel):
    phrase: str = Field(description="태그의 근거가 되는 표현을 문장에서 **글자 그대로** 인용 (문장에 없는 말은 쓸 수 없다)")
    tag: MoodTag


class MoodTags(BaseModel):
    moods: list[MoodHit] = Field(
        default_factory=list,
        description="문장에 직접 드러난 분위기·성격만, 최대 2개. 장소 종류·메뉴·예산·시간·'N번째 바꿔줘' 같은 요구는 태그가 아니다. 해당 없거나 확실하지 않으면 빈 목록",
    )


class BlogCafe(BaseModel):
    name: str = Field(description="블로그 제목에 적힌 카페 상호 그대로 (지역명·수식어 제외). 예) '성수동 카페 천상가옥, 핫한…' → '천상가옥'")
    doc: int = Field(description="그 상호가 나온 제목의 번호")


class BlogCafes(BaseModel):
    items: list[BlogCafe] = Field(default_factory=list, description="제목에 카페 상호가 분명히 나온 것만. 여러 곳을 소개하는 글·상호가 없는 글은 제외")


class TimeChange(BaseModel):
    day: int = Field(description="시작 시각을 바꿀 날짜 (첫째날=1, 둘째날=2)")
    start_time: str = Field(description="그날 시작 시각 24시간제 HH:MM. 예) 오전 9시 → 09:00")


class EditPlan(BaseModel):
    time_changes: list[TimeChange] = Field(default_factory=list, description="일정 시작 시각을 바꿔 달라는 요청이면 날짜별로 채운다. 장소 교체 요청이면 빈 목록")
    schedule_only: bool = Field(False, description="장소는 그대로 두고 시작 시각만 바꾸는 요청이면 true. 이때 target_number=0, place=null")
    target_number: int = Field(description="바꿀 장소의 번호 (현재 코스 목록의 '번호', 1부터). 전체 재구성 요청이면 0")
    place: DraftPlace | None = Field(None, description="그 자리에 넣을 새 장소. 전체 재구성이면 null")
    alternates: list[DraftPlace] = Field(default_factory=list, description="place 가 지도에서 확인되지 않을 때 대신 쓸, 같은 요청을 만족하는 다른 실존 장소 2~3개")
    keywords: list[str] = Field(default_factory=list, description="새 장소를 지도 앱에서 찾을 때 쓸 업종 검색어 2~3개 (지도에 실제로 쓰이는 짧은 업종명). 예) ['키즈카페', '실내놀이터'], ['미술관', '전시'], ['브런치']. 지역명·수식어는 넣지 않는다")
    note: str = Field("", description="사용자에게 한 줄로 전할 변경 요약")


# ---------- 공통 ----------


def _now_ms() -> int:
    return int(time.time() * 1000)


def _conditions_text(req: dict[str, Any]) -> str:
    mode = "나들이(1일 데이트/나들이)" if req.get("mode") == "outing" else f"여행 {req.get('days', 1)}일"
    transport = "뚜벅이(도보+대중교통, 장소 간 짧게)" if req.get("transport") == "walk" else "자차(주차 편한 곳, 반경 넓게 OK)"
    parts = [
        f"지역: {req.get('region')}",
        f"모드: {mode}",
        f"이동: {transport}",
        f"날짜: {req.get('date')} {req.get('start_time')}~{req.get('end_time')}",
        f"1인 예산: {int(req.get('budget', 0)):,}원"
        + (
            f" ({_trip_days(req)}일 전체 합계, 숙박비 제외 → 하루 약 {int(req.get('budget', 0)) // _trip_days(req):,}원)"
            if _trip_days(req) > 1
            else " (하루 합계)"
        ),
    ]
    if req.get("day_starts"):
        parts.append("날짜별 시작 시각(우선 적용): " + ", ".join(f"Day {d} {t}" for d, t in sorted(req["day_starts"].items())))
    if req.get("moods"):
        parts.append("분위기: " + ", ".join(req["moods"]))
    if req.get("party"):
        parts.append(f"동행: {req['party']}")
    headcount = int(req.get("headcount") or 1)
    if headcount > 1:
        total = f", 전체 약 {int(req.get('budget', 0)) * headcount:,}원" if req.get("budget") else ""
        parts.append(f"총 인원: {headcount}명 (예산·예상 비용은 모두 1인 기준{total}. 여러 명이 함께 먹고 즐기기 좋은 곳으로)")
    if req.get("free_text"):
        parts.append(f"추가 조건(반드시 반영): {req['free_text']}")
    if req.get("lodging") and _trip_days(req) > 1:
        parts.append(f"숙소(사용자가 이미 정함): {req['lodging']}")
    return "\n".join(parts)


def _places_per_day(req: dict[str, Any]) -> int:
    try:
        sh, sm = map(int, req.get("start_time", "11:00").split(":"))
        eh, em = map(int, req.get("end_time", "20:00").split(":"))
        hours = max(2.0, (eh * 60 + em - sh * 60 - sm) / 60)
    except ValueError:
        hours = 8.0
    n = int(hours * 60 // SLOT_MIN)  # 올림하면 종료 시각을 넘기기 쉬워 내림한다
    cap = MAX_PLACES_PER_DAY_TRIP if req.get("mode") == "trip" else MAX_PLACES_PER_DAY
    return max(MIN_PLACES_PER_DAY, min(cap, n))


def _fmt_rag_docs(docs: list[dict[str, Any]], limit: int = 20) -> str:
    lines = []
    for d in docs[:limit]:
        if d.get("doc_type") == "place":
            lines.append(f"- [장소 ✔지도확인] {d.get('title')} ({d.get('content_type', '')}, {d.get('addr', '')}) — {d.get('one_line') or ''} {d.get('tags') or ''}")
        else:
            lines.append(f"- [블로그] {d.get('title')} — {d.get('one_line') or d.get('snippet', '')[:120]} {d.get('tags') or ''}")
    return "\n".join(lines) or "- (없음)"


def _fmt_pois(pois: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {p['name']} ({p.get('category_full', '').split(' > ')[-1] or p.get('category')}, {p.get('address', '')})"
        + (f" ★블로그 언급 {p['blog_mentions']}건: {p['blog_hint']}" if p.get("blog_mentions") else "")
        for p in pois
    ) or "- (없음)"


POI_PER_GROUP = 8  # 카카오 후보를 LLM 에 넘기는 개수 (식당·카페 각각)
POI_FETCH = 15  # 재정렬 전에 카카오에서 가져오는 개수


def _poi_mentioned(name: str, text: str) -> bool:
    """블로그 글이 그 상호를 언급하는지. '송도맛집'·'○○카페' 같은 일반 명사형 상호는 아무 글에나 걸리므로 제외한다."""
    head = search_place._norm_name(name.split()[0]) if name.split() else ""
    if len(head) < 3 or head.endswith(("맛집", "카페", "식당")):
        return False
    return summarize_reviews.mentions(name, text)


BLOG_CAFE_WALK_M = 800  # 뚜벅이: 블로그 근거 카페를 우선하되 지역 중심에서 이 거리 안쪽만 (11/21 결정)
BLOG_CAFE_MAX = 4  # 블로그 근거 카페로 올리는 최대 개수 (나머지 자리는 가까운 카페로 유지)


def _blog_backed_cafes(
    req: dict[str, Any], center: dict[str, Any], docs: list[dict[str, Any]], moods: list[str], radius: int, taken: set[str],
) -> list[dict[str, Any]]:
    """분위기 태그가 붙은 블로그 제목에서 카페 상호를 뽑아 카카오에서 찾는다 → 근거가 있는 실존 카페 후보.

    카카오 '근처 카페' 상위 목록에는 블로그가 말하는 카페가 거의 안 들어오므로(거리순이라서), 이름으로 따로 찾아 온다.
    거리 상한: 뚜벅이 800m, 자차는 radius. 제목에 없는 상호는 LLM 이 지어낸 것으로 보고 버린다.
    """
    want = set(moods)
    seen: set[str] = set()
    titles: list[dict[str, Any]] = []
    for d in docs:
        if d.get("doc_type") == "blog" and want & set(d.get("tags") or []) and d.get("doc_id") not in seen and d.get("title"):
            seen.add(d["doc_id"])
            titles.append(d)
    titles = titles[:20]
    if not titles or not center:
        return []
    try:
        res = chat(0).with_structured_output(BlogCafes).invoke([
            ("system", "블로그 글 제목에서 카페 상호를 뽑습니다. 제목에 상호가 분명히 적힌 것만 뽑고, 짐작하지 않습니다."),
            ("human", "\n".join(f"{i}. {d['title']}" for i, d in enumerate(titles))),
        ])
        items = getattr(res, "items", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("블로그 카페 상호 추출 실패: %s", e)
        return []
    squeeze = lambda t: re.sub(r"\s+", "", t or "").lower()
    named: dict[str, dict[str, Any]] = {}
    for it in items:
        if 0 <= it.doc < len(titles) and squeeze(it.name) and squeeze(it.name) in squeeze(titles[it.doc]["title"]):
            named.setdefault(squeeze(it.name), {"name": it.name.strip(), "doc": titles[it.doc]})
    limit = min(radius, BLOG_CAFE_WALK_M) if req.get("transport") == "walk" else radius

    def lookup(n: dict[str, Any]) -> dict[str, Any] | None:
        try:
            hits = search_place.search(f"{req['region']} {n['name']}", center["lat"], center["lng"], radius, size=5)
        except Exception as e:  # noqa: BLE001
            log.debug("블로그 카페 검색 실패 %s: %s", n["name"], e)
            return None
        for h in hits:
            near = squeeze(n["name"]) in squeeze(h["name"]) or squeeze(h["name"]) in squeeze(n["name"])
            if (
                h.get("category_group") == "CE7"
                and near
                and h.get("kakao_place_id") not in taken
                and haversine_m(center["lat"], center["lng"], h["lat"], h["lng"]) <= limit
            ):
                return {**h, "blog_mentions": 1, "blog_hint": str(n["doc"].get("one_line") or "")}
        return None

    with ThreadPoolExecutor(max_workers=5) as ex:
        found = [p for p in ex.map(lookup, list(named.values())) if p]
    if not _chains_allowed(req):
        found = [p for p in found if not _is_chain(p["name"])]
    found.sort(key=lambda p: haversine_m(center["lat"], center["lng"], p["lat"], p["lng"]))
    return found[:BLOG_CAFE_MAX]


def _rank_pois_by_blogs(pois: list[dict[str, Any]], docs: list[dict[str, Any]], moods: list[str]) -> list[dict[str, Any]]:
    """카카오 후보(거리순)를 블로그 근거가 있는 곳 위로 올린다. 카카오는 분위기를 모르므로 RAG 블로그가 분위기의 유일한 근거다.

    점수: 상호를 언급한 글마다 +1, 그 글에 사용자가 원한 분위기 태그가 붙어 있으면 +2. 같은 점수끼리는 원래(거리) 순서를 지킨다.
    근거 글이 있으면 blog_mentions·blog_hint(그 글의 한 줄 요약)를 달아 LLM 이 reason 을 지어내지 않고 이걸 쓰게 한다.
    """
    want = set(moods)
    scored: list[tuple[int, int, dict[str, Any]]] = []  # (그룹 순서, -점수, 후보) → 그룹(식당/카페) 안에서만 정렬
    groups: dict[str, int] = {}
    for p in pois:
        g = groups.setdefault(p.get("category_group") or "", len(groups))
        score, count, hint = 0, 0, ""
        for d in docs:
            if d.get("doc_type") != "blog" or not _poi_mentioned(p["name"], f"{d.get('title') or ''} {d.get('snippet') or ''}"):
                continue
            count += 1
            hit = bool(want & set(d.get("tags") or []))
            score += 3 if hit else 1
            if d.get("one_line") and (not hint or hit):
                hint = str(d["one_line"])
        scored.append((g, -score, {**p, "blog_mentions": count, "blog_hint": hint} if count else p))
    scored.sort(key=lambda t: (t[0], t[1]))  # 안정 정렬: 점수가 같으면 입력(거리) 순서 유지
    return [p for _, _, p in scored]


def _weekdays_text(req: dict[str, Any]) -> str:
    """'Day 1 토요일, Day 2 일요일' — 휴무일 판단용."""
    try:
        d0 = datetime.strptime(req["date"], "%Y-%m-%d")
    except (KeyError, ValueError):
        return "요일 모름"
    names = "월화수목금토일"
    return ", ".join(f"Day {i + 1} {names[(d0 + timedelta(days=i)).weekday()]}요일" for i in range(_trip_days(req)))


def _trip_days(req: dict[str, Any]) -> int:
    return int(req.get("days", 1)) if req.get("mode") == "trip" else 1


# 어디에나 있는 프랜차이즈는 코스에 넣을 이유가 없다 (사용자가 직접 이름을 적은 경우만 예외)
_CHAINS = (
    "메가MGC커피", "메가커피", "컴포즈커피", "빽다방", "스타벅스", "이디야", "투썸플레이스", "할리스", "파스쿠찌", "커피빈", "엔제리너스", "더벤티",
    "매머드커피", "매머드익스프레스", "탐앤탐스", "공차", "폴바셋", "커피에반하다", "텐퍼센트커피", "하삼동커피", "더리터", "카페봄봄", "요거프레소",
    "맥도날드", "롯데리아", "버거킹", "KFC", "맘스터치", "서브웨이", "노브랜드버거", "프랭크버거", "김밥천국", "본죽", "한솥", "홍콩반점", "역전우동",
    "새마을식당", "명륜진사갈비", "교촌치킨", "BHC", "BBQ", "파리바게뜨", "뚜레쥬르", "던킨", "배스킨라빈스", "설빙", "이삭토스트", "에그드랍",
)
_CHAIN_KEYS = tuple(c.replace(" ", "").lower() for c in _CHAINS)


def _is_chain(name: str) -> bool:
    n = name.replace(" ", "").lower()
    return any(n.startswith(k) for k in _CHAIN_KEYS)


def _chains_allowed(req: dict[str, Any]) -> bool:
    """사용자가 자유 조건에 프랜차이즈 이름을 직접 적었으면 허용."""
    text = (req.get("free_text") or "").replace(" ", "").lower()
    return any(k in text for k in _CHAIN_KEYS)


def _with_kids(req: dict[str, Any]) -> bool:
    return "아이동반" in (req.get("moods") or []) or any(w in (req.get("party") or "") for w in ("아이", "아기", "유아", "어린이", "키즈"))


def _max_outdoor(req: dict[str, Any]) -> int:
    """비 예보일 때 Day 당 허용하는 야외 장소 수. 자연/산책을 고른 사용자는 하나 더."""
    return 2 if "자연/산책" in (req.get("moods") or []) else 1


_OUTDOOR_NAME_RE = re.compile(r"(공원|수목원|호수|저수지|유원지|해변|해수욕장|산책로|둘레길|캠핑장|전망대|출렁다리|[가-힣]섬$|숲$|계곡|폭포)")


def _is_outdoor(p: dict[str, Any]) -> bool:
    """비 예보 때 줄일 야외 장소인지. LLM 이 indoor 를 잘못 채우는 경우가 있어 이름으로도 본다 ('송도센트럴파크' 는 영문 Park 라 별도)."""
    if p.get("category") not in PLAY_CATEGORIES:
        return False
    name = p.get("name", "")
    return not p.get("indoor", True) or bool(_OUTDOOR_NAME_RE.search(name)) or name.endswith(("파크", "가든")) and "테마" not in name


def _enforce_rain(cands: list[dict[str, Any]], spares: list[dict[str, Any]], max_outdoor: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """비 예보: Day 마다 야외 장소가 max_outdoor 를 넘으면 뒤쪽부터 같은 날의 실내 예비 후보로 바꾼다.

    반환: (cands, 남은 spares, 바꾸지 못하고 남은 초과 야외 장소 수)
    """
    cands, spares = list(cands), list(spares)
    leftover = 0
    for day in sorted({c["day"] for c in cands}):
        outdoor = [i for i, c in enumerate(cands) if c["day"] == day and _is_outdoor(c)]
        for i in reversed(outdoor[max_outdoor:]):
            pick = next((s for s in spares if s["day"] == day and s.get("category") in PLAY_CATEGORIES and s.get("indoor", True)), None)
            if pick is None:
                leftover += 1
                continue
            spares.remove(pick)
            cands[i] = {**pick, "order": cands[i]["order"], "day": day}
    return cands, spares, leftover


_ORDINALS = {"첫": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8}
_ORDINAL_RE = re.compile(r"(\d+|첫|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟)\s*번\s*째")
_DAY_RE = re.compile(r"(?:day|데이)\s*(\d)|(\d)\s*일\s*차|(첫|둘|셋)\s*째?\s*날", re.IGNORECASE)


def _parse_target(instruction: str, places: list[dict[str, Any]]) -> int | None:
    """'3번째를 실내로', '마지막 장소를 …', '2일차 첫 번째' 처럼 순서로 가리킨 수정 대상을 places 인덱스로 바꾼다.

    LLM 에게 맡기면 0/1 기준이 섞여 한 칸씩 밀리는 일이 있어, 순서 표현이 정확히 하나일 때는 여기서 확정한다. 모르면 None.
    """
    if not places:
        return None
    day = None
    m = _DAY_RE.search(instruction)
    if m:
        day = int(m.group(1) or m.group(2) or 0) or _ORDINALS.get(m.group(3) or "")
    pool = [i for i, p in enumerate(places) if day is None or p.get("day", 1) == day]
    if not pool:
        return None
    ords = _ORDINAL_RE.findall(instruction)
    has_last = "마지막" in instruction or "맨 끝" in instruction
    if len(ords) + int(has_last) != 1:
        return None
    if has_last:
        return pool[-1]
    n = int(ords[0]) if ords[0].isdigit() else _ORDINALS[ords[0]]
    return pool[n - 1] if 1 <= n <= len(pool) else None


def _radius_key(req: dict[str, Any]) -> str:
    """뚜벅이 / 자차(동 단위 요청: 시군구까지 해석되지 않음) / 자차(시군구 단위 요청)."""
    if req.get("transport", "walk") == "walk":
        return "walk"
    return "car_wide" if "sigungu_code" in rag.resolve_region(req.get("region")) else "car_local"


def _near_center(docs: list[dict[str, Any]], center: dict[str, Any], radius_m: int) -> list[dict[str, Any]]:
    """좌표가 있는 장소 문서 중 중심에서 radius_m 보다 먼 것을 뺀다 (좌표 없는 블로그 문서는 그대로)."""
    return [
        d for d in docs
        if not (d.get("lat") and d.get("lng")) or haversine_m(center["lat"], center["lng"], float(d["lat"]), float(d["lng"])) <= radius_m
    ]


_KAKAO_ATTRACTION_PREFIX = "여행 > 관광,명소"  # 카카오 카테고리(category_full = API 의 category_name)
# 업종이 관광명소여도 코스에 넣기 부적절한 세부 분류 (확인된 사례만: '전주종합관광안내소' = 여행 > 관광,명소 > 관광안내소,
# 카지노 = 여행 > 관광,명소 > 카지노 — 성인 전용이라 데이트·가족 코스에 맞지 않음)
_NOT_A_VISIT_SPOTS = {"관광안내소", "카지노"}


def _is_kakao_attraction(h: dict[str, Any]) -> bool:
    """카카오 검색 결과가 볼거리 후보인지.

    관광명소(AT4)·문화시설(CT1) 그룹은 지금처럼 허용. 카카오는 문화유적·산봉우리 등에 그룹 코드를 붙이지 않으므로,
    그룹이 비어 있으면 카테고리가 '여행 > 관광,명소' 로 시작할 때 허용한다. 식당(FD6)·카페(CE7)·숙소 등 다른 그룹이 있으면 그것이 우선(제외).
    관광안내소처럼 방문 장소가 아닌 세부 분류는 그룹과 관계없이 제외.
    """
    group = h.get("category_group") or ""
    full = h.get("category_full") or ""
    if _NOT_A_VISIT_SPOTS & set(full.split(" > ")):
        return False
    if group:
        return group in ("AT4", "CT1")
    return full.startswith(_KAKAO_ATTRACTION_PREFIX)


def _find_attractions(req: dict[str, Any], hub: tuple[float, float], rain: bool) -> list[dict[str, Any]]:
    """hub 주변의 실존 볼거리 (카카오 관광명소 AT4 · 문화시설 CT1). 비 예보면 실내 시설 검색어를 먼저 쓴다.

    큐레이션 장소 문서(TourAPI 상세)가 아직 서울만 있어서, 다른 지역은 이걸로 볼거리 후보를 보충한다.
    반환 형식은 rag 장소 문서와 맞춘다: {title, lat, lng, addr, kakao_place_id, place_url, one_line}
    """
    radius = WALK_OUTLIER_M if req.get("transport", "walk") == "walk" else 15000
    words = (["박물관", "미술관", "전시관"] if rain else []) + ["관광명소", "가볼만한곳"]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for w in words:
            for h in search_place.search(f"{req['region']} {w}", hub[0], hub[1], radius, size=10):
                if _is_kakao_attraction(h) and h.get("kakao_place_id") not in seen:
                    seen.add(h.get("kakao_place_id"))
                    out.append({
                        "doc_type": "place", "title": h["name"], "lat": h["lat"], "lng": h["lng"], "addr": h.get("address", ""),
                        "kakao_place_id": h.get("kakao_place_id", ""), "place_url": h.get("place_url", ""),
                        "one_line": (h.get("category_full") or "").split(" > ")[-1],
                    })
            if len(out) >= 6:
                break
    except Exception as e:  # noqa: BLE001
        log.warning("볼거리 검색 실패: %s", e)
    return out


def _find_stays(req: dict[str, Any], center: dict[str, Any] | None) -> list[dict[str, Any]]:
    """중심 주변의 실존 숙소 (카카오 카테고리 AD5)."""
    if not center:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for q in ("숙소", "펜션", "호텔"):
            for h in search_place.search(f"{req['region']} {q}", center["lat"], center["lng"], 20000, size=15):
                if h.get("category_group") == "AD5" and h.get("kakao_place_id") not in seen:
                    seen.add(h.get("kakao_place_id"))
                    out.append(h)
    except Exception as e:  # noqa: BLE001
        log.warning("숙소 검색 실패: %s", e)
    return out[:12]


def _extract_moods(text: str) -> list[str]:
    """자유 문장('조용한 카페로 바꿔줘') → 분위기 태그(MOODS). 태그를 직접 골랐을 때와 같은 RAG 필터를 타게 한다. 실패하면 빈 목록."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        res = chat(0, MOOD_MODEL if settings.llm_provider == "openai" else None).with_structured_output(MoodTags).invoke(
            [("system", "여행·데이트 코스 요청 문장에서 원하는 분위기·성격을 태그로 바꿉니다. 문장에 직접 드러난 것만 고르고, 짐작하지 않습니다. "
                        "장소 종류(공방·카페)나 메뉴(비건)는 태그가 아니므로 무시합니다.\n" + MOOD_GUIDE), ("human", text)]
        )
        hits = getattr(res, "moods", None) or []
    except Exception as e:  # noqa: BLE001
        log.warning("분위기 태그 변환 실패: %s", e)
        return []
    squeezed = text.replace(" ", "")
    # 작은 모델은 문장에 없는 분위기도 갖다 붙이므로, 근거 표현이 실제 문장에 있는 태그만 쓴다
    return list(dict.fromkeys(h.tag for h in hits if h.tag in MOODS and h.phrase.replace(" ", "") and h.phrase.replace(" ", "") in squeezed))


def _find_must(req: dict[str, Any], center: dict[str, Any] | None) -> tuple[list[str], list[dict[str, Any]]]:
    """자유 조건 → (지도 검색어, 그 검색어로 찾은 중심 주변 실존 장소). 장소 종류를 가리키지 않으면 ([], [])."""
    text = (req.get("free_text") or "").strip()
    if not text:
        return [], []
    try:
        must: MustHave = chat(0, MOOD_MODEL if settings.llm_provider == "openai" else None).with_structured_output(MustHave).invoke(
            [("system", "여행·데이트 코스 조건에서 '꼭 가고 싶은 장소 종류' 만 뽑아 지도 검색어로 바꿉니다."), ("human", text)]
        )
        keywords = [k.strip() for k in must.keywords if k.strip()][:3]
    except Exception as e:  # noqa: BLE001
        log.warning("자유 조건 해석 실패: %s", e)
        keywords = [text] if len(text) <= 12 and " " not in text else []
    if not keywords or not center:
        return keywords, []
    radius = 2000 if req.get("transport", "walk") == "walk" else 10000
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for kw in keywords:
            for h in search_place.search(kw, center["lat"], center["lng"], radius, size=8):
                if h.get("kakao_place_id") not in seen:
                    seen.add(h.get("kakao_place_id"))
                    docs.append({**h, "keyword": kw})
    except Exception as e:  # noqa: BLE001
        log.warning("자유 조건 장소 검색 실패: %s", e)
    return keywords, docs[:8]


def _find_user_stay(req: dict[str, Any], center: dict[str, Any] | None) -> dict[str, Any] | None:
    """사용자가 적은 숙소 이름을 지도에서 찾는다 (이름이 충분히 비슷한 것만)."""
    name = req["lodging"].strip()
    target = search_place._norm_name(name)
    try:
        hits = search_place.search(f"{req['region']} {name}", size=5) + search_place.search(name, size=5)
        if center:
            hits = search_place.search(name, center["lat"], center["lng"], 20000, size=5) + hits
    except Exception as e:  # noqa: BLE001
        log.warning("숙소 검색 실패: %s", e)
        return None
    scored = [(search_place.name_similarity(target, search_place._norm_name(h["name"])), h) for h in hits]
    scored = [x for x in scored if x[0] >= search_place.MATCH_THRESHOLD]
    return max(scored, key=lambda x: x[0])[1] if scored else None


def _stay_place(s: dict[str, Any], day: int, reason: str) -> dict[str, Any]:
    return {
        "name": s["name"], "category": "숙소", "reason": reason, "stay_min": 60, "indoor": True, "tags": [], "source": "rag",
        "est_cost": 0, "day": day, "order": 99, "verified": True, "lat": s["lat"], "lng": s["lng"], "address": s.get("address", ""),
        "kakao_place_id": s.get("kakao_place_id", ""), "place_url": s.get("place_url", ""), "phone": s.get("phone", ""),
        "kakao_category": s.get("category_full", ""),
    }


def _centroid(ps: list[dict[str, Any]]) -> tuple[float, float]:
    return sum(p["lat"] for p in ps) / len(ps), sum(p["lng"] for p in ps) / len(ps)


def _regroup_days(places: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """여행(2일 이상): 서로 가까운 장소를 같은 날로 묶어, 전날 지나간 권역을 다음 날 다시 가지 않게 한다.

    볼거리(관광지·놀거리 등)를 권역별로 나눈 뒤, 식당·카페는 가까운 권역에 날마다 고르게 배분한다. 숙소는 건드리지 않는다.
    날별 흩어짐(각 장소 ↔ 그날 중심 거리 합)이 20% 이상 줄 때만 적용하고, 아니면 LLM 이 짠 날짜 배정을 그대로 둔다.
    """
    movable = [p for p in places if p.get("category") != "숙소"]
    anchors = [p for p in movable if p.get("category") in PLAY_CATEGORIES]
    if days < 2 or len(anchors) < days:
        return places

    def spread(assign: dict[int, list[dict[str, Any]]]) -> float:
        total = 0.0
        for ps in assign.values():
            if ps:
                c = _centroid(ps)
                total += sum(haversine_m(c[0], c[1], p["lat"], p["lng"]) for p in ps)
        return total

    before: dict[int, list[dict[str, Any]]] = {}
    for p in movable:
        before.setdefault(p["day"], []).append(p)

    # 1) 볼거리: 가장 먼 것끼리 씨앗으로 잡고(farthest-point), 정원을 지키며 가까운 씨앗에 배정 → 중심 갱신을 몇 번 반복
    seeds = [anchors[0]]
    while len(seeds) < days:
        seeds.append(max(anchors, key=lambda a: min(haversine_m(a["lat"], a["lng"], s["lat"], s["lng"]) for s in seeds)))
    centers = [(s["lat"], s["lng"]) for s in seeds]
    cap = -(-len(anchors) // days)
    groups: list[list[dict[str, Any]]] = []
    for _ in range(4):
        groups = [[] for _ in range(days)]
        pairs = sorted(((haversine_m(c[0], c[1], a["lat"], a["lng"]), i, k) for i, a in enumerate(anchors) for k, c in enumerate(centers)))
        placed: set[int] = set()
        for _, i, k in pairs:
            if i not in placed and len(groups[k]) < cap:
                placed.add(i)
                groups[k].append(anchors[i])
        centers = [_centroid(g) if g else centers[k] for k, g in enumerate(groups)]
    if any(not g for g in groups):
        return places

    # 2) 식당·카페: 날마다 하나씩 돌아가며 그 권역에서 가장 가까운 곳을 가져간다 (한 날에 식당이 몰리고 다른 날은 없는 일 방지)
    for role in ("식당", "카페"):
        items = [p for p in movable if p.get("category") == role]
        while items:
            for k in sorted(range(days), key=lambda k: sum(1 for p in groups[k] if p.get("category") == role)):
                if not items:
                    break
                pick = min(items, key=lambda p: haversine_m(centers[k][0], centers[k][1], p["lat"], p["lng"]))
                items.remove(pick)
                groups[k].append(pick)

    # 3) 원래 Day 1 장소가 많이 들어간 권역을 Day 1 로 (사용자가 보는 순서가 크게 뒤집히지 않게)
    groups.sort(key=lambda g: sum(p["day"] for p in g) / len(g))
    after = {k + 1: g for k, g in enumerate(groups)}
    if spread(after) > spread(before) * 0.8:
        return places
    out: list[dict[str, Any]] = []
    for d in sorted(after):
        seq = _day_sequence(after[d])
        stays = [p for p in places if p.get("category") == "숙소" and p["day"] == d]
        # fixed_order: 시간대에 맞춰 다시 짠 순서이므로 optimize_route 가 거리만 보고 뒤섞지 않게 한다
        out += [{**p, "day": d, "order": i + 1, "fixed_order": True} for i, p in enumerate(seq + stays)]
    return out


def _day_sequence(ps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """하루치 장소를 시간대 틀에 맞춰 줄 세운다: 오전 볼거리 → 점심 식당 → 카페 → 남은 볼거리 → 남은 카페 → 저녁 식당.

    각 자리에는 해당 역할 중 직전 장소에서 가장 가까운 곳을 넣는다 (첫 자리는 그날 중심에서 가장 먼 볼거리부터 → 한 방향으로 훑게).
    """
    plays = [p for p in ps if p.get("category") in PLAY_CATEGORIES]
    eats = [p for p in ps if p.get("category") == "식당"]
    cafes = [p for p in ps if p.get("category") == "카페"]
    roles = (["play"] if plays else []) + (["eat"] if eats else []) + (["cafe"] if cafes else [])
    roles += ["play"] * max(0, len(plays) - 1) + ["cafe"] * max(0, len(cafes) - 1) + ["eat"] * max(0, len(eats) - 1)
    pools = {"play": plays, "eat": eats, "cafe": cafes}
    hub = _centroid(ps)
    seq: list[dict[str, Any]] = []
    for role in roles:
        pool = pools[role]
        if not seq:
            pick = max(pool, key=lambda p: haversine_m(hub[0], hub[1], p["lat"], p["lng"]))
        else:
            pick = min(pool, key=lambda p: haversine_m(seq[-1]["lat"], seq[-1]["lng"], p["lat"], p["lng"]))
        pool.remove(pick)
        seq.append(pick)
    return seq


def _fmt_web_docs(docs: list[dict[str, Any]], limit: int = 5) -> str:
    return "\n".join(f"- {d.get('title')}: {d.get('content', '')[:160]}" for d in docs[:limit]) or "- (없음)"


# ---------- 노드 ----------


def parse_intent(state: dict[str, Any]) -> dict[str, Any]:
    req = state["request"]
    t0 = _now_ms()
    center = None
    try:
        center = search_place.geocode_region(req["region"])
    except Exception as e:  # noqa: BLE001
        log.warning("geocode 실패: %s", e)
    region_filter = rag.resolve_region(req["region"])
    warnings = list(state.get("warnings", []))
    if not center:
        warnings.append(f"'{req['region']}' 위치를 찾지 못해 지역 중심 없이 진행합니다")
    detail = f"{req['region']} → {center['label'] if center else '?'}"

    # 자유 조건이 특정 종류의 장소(예: 반지공방)를 원하면 지도에서 실존 후보를 미리 찾아 둔다 → 초안·검증에서 반드시 포함
    # 같은 문장에서 분위기 태그도 뽑아 선택한 태그에 합친다 (LLM 호출이 겹치지 않게 병렬로)
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_must, f_moods = ex.submit(_find_must, req, center), ex.submit(_extract_moods, req.get("free_text", ""))
        must_keywords, must_docs = f_must.result()
        text_moods = f_moods.result()
    new_moods = [m for m in text_moods if m not in (req.get("moods") or [])]
    if new_moods:
        req = {**req, "moods": [*(req.get("moods") or []), *new_moods]}
    if new_moods:
        detail += f" / 자유 조건 → 분위기 태그 {new_moods}"
    if must_keywords:
        detail += f" / 꼭 넣을 곳 '{must_keywords[0]}' 후보 {len(must_docs)}곳"
        if not must_docs:
            warnings.append(f"'{req['free_text']}' 에 맞는 장소를 근처 지도에서 찾지 못했어요")

    # 사용자가 숙소를 직접 적었으면 지도에서 확인해 둔다
    user_stay = None
    if req.get("lodging") and _trip_days(req) > 1:
        user_stay = _find_user_stay(req, center)
        if user_stay:
            detail += f" / 숙소 {user_stay['name']}"
        else:
            warnings.append(f"숙소 '{req['lodging']}' 을(를) 지도에서 찾지 못해 근처 숙소로 대신했어요")
    return {
        **({"request": req} if new_moods else {}),
        "must_keywords": must_keywords,
        "must_docs": must_docs,
        "user_stay": user_stay,
        "center": center,
        "region_filter": region_filter,
        "conditions": _conditions_text(req),
        "per_day": _places_per_day(req),
        "warnings": warnings,
        "trace": state.get("trace", []) + [{"node": "parse_intent", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def retrieve(state: dict[str, Any]) -> dict[str, Any]:
    req, center = state["request"], state.get("center")
    t0 = _now_ms()
    moods = req.get("moods") or []
    base_q = f"{req['region']} {' '.join(moods)} {req.get('free_text', '')} {'데이트' if req.get('mode') == 'outing' else '여행'} 코스".strip()

    def do_rag() -> list[dict[str, Any]]:
        try:
            places = rag.search(base_q, moods=moods, region=req["region"], k=8, doc_type="place")
            # 식당·카페 후보가 빠지지 않도록 따로 뽑는다 (TourAPI 장소 문서는 관광지 비중이 커서)
            eats = rag.search(f"{req['region']} 맛집 식당 {' '.join(moods)}", moods=None, region=req["region"], k=5, doc_type="blog")
            cafes = rag.search(f"{req['region']} 카페 {' '.join(moods)}", moods=None, region=req["region"], k=4, doc_type="blog")
            blogs = rag.search(base_q, moods=moods, region=req["region"], k=6, doc_type="blog")
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for d in places + eats + cafes + blogs:
                if d["doc_id"] not in seen:
                    seen.add(d["doc_id"])
                    out.append(d)
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("rag 실패: %s", e)
            return []

    def do_web() -> list[dict[str, Any]]:
        q1 = f"{req['region']} {'데이트' if req.get('mode') == 'outing' else '여행'} 코스 추천 {' '.join(moods)}".strip()
        q2 = f"{req['region']} 팝업 전시 축제 이번주"
        return summarize_reviews.web_search(q1, 4) + summarize_reviews.web_search(q2, 3, days=14)

    def do_weather() -> dict[str, Any]:
        if not center:
            return {"available": False, "rain": False, "note": "위치 없음"}
        sh = int(req.get("start_time", "11:00").split(":")[0])
        eh = int(req.get("end_time", "20:00").split(":")[0])
        return get_weather.weather(center["lat"], center["lng"], req["date"], sh, max(eh, sh + 1))

    def do_sun() -> dict[str, str]:
        lat, lng = (center["lat"], center["lng"]) if center else (37.5665, 126.9780)
        return get_sun_times.sun_times(lat, lng, req["date"])

    def do_pois() -> list[dict[str, Any]]:
        """중심 주변의 실존 식당·카페 (카카오). LLM 이 지어내지 않고 여기서 고르게 한다."""
        if not center:
            return []
        radius = 1500 if req.get("transport") == "walk" else 8000
        out: list[dict[str, Any]] = []
        try:
            # 분위기 단어를 섞으면 카카오 검색이 비어 버리므로 업종 키워드만 쓴다. 분위기 판단은 LLM 이 RAG 문서로 한다.
            for q, group in (("맛집", "FD6"), ("카페", "CE7")):
                hits = search_place.search(f"{req['region']} {q}", center["lat"], center["lng"], radius, size=POI_FETCH)
                picked = [h for h in hits if h.get("category_group", group) == group]
                if not _chains_allowed(req):
                    picked = [h for h in picked if not _is_chain(h["name"])]
                if _with_kids(req):  # 아이 동반: 술집은 후보에서 뺀다
                    picked = [h for h in picked if "술집" not in (h.get("category_full") or "") and "술집" not in h["name"]]
                out += picked  # 자르는 건 블로그 근거로 재정렬한 뒤에 한다 (근거 있는 곳이 9번째 이후에 있으면 버려지므로)
        except Exception as e:  # noqa: BLE001
            log.warning("poi 검색 실패: %s", e)
        return out

    def do_blog_pool() -> list[dict[str, Any]]:
        """카카오 후보의 분위기 근거를 찾을 블로그 풀. LLM 에 넘기지 않고 재정렬에만 쓴다 (넓게 뽑는다)."""
        try:
            tail = ' '.join(moods)
            return rag.search(f"{req['region']} 카페 {tail}", moods=None, region=req["region"], k=30, doc_type="blog") + rag.search(
                f"{req['region']} 맛집 식당 {tail}", moods=None, region=req["region"], k=20, doc_type="blog"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("블로그 풀 검색 실패: %s", e)
            return []

    def do_stays() -> list[dict[str, Any]]:
        return _find_stays(req, center) if _trip_days(req) > 1 else []

    with ThreadPoolExecutor(max_workers=7) as ex:
        f_rag, f_web, f_wx, f_sun, f_poi, f_stay, f_pool = (
            ex.submit(do_rag), ex.submit(do_web), ex.submit(do_weather), ex.submit(do_sun), ex.submit(do_pois), ex.submit(do_stays),
            ex.submit(do_blog_pool),
        )
        rag_docs, web_docs, weather, sun, pois, stays, blog_pool = (
            f_rag.result(), f_web.result(), f_wx.result(), f_sun.result(), f_poi.result(), f_stay.result(), f_pool.result()
        )

    # 카카오 후보를 블로그 근거(상호 언급 + 분위기 태그)가 있는 곳 위로 올린 뒤 그룹별로 자른다
    pois = _rank_pois_by_blogs(pois, rag_docs + blog_pool, moods)
    if moods and center:
        taken_ids = {p.get("kakao_place_id") for p in pois}
        backed = _blog_backed_cafes(req, center, rag_docs + blog_pool, moods, 1500 if req.get("transport") == "walk" else 8000, taken_ids)
        pois = backed + [p for p in pois if p.get("kakao_place_id") not in {b.get("kakao_place_id") for b in backed}]
    kept: dict[str, int] = {}
    ranked: list[dict[str, Any]] = []
    for p in pois:
        g = p.get("category_group") or ""
        if kept.get(g, 0) < POI_PER_GROUP:
            kept[g] = kept.get(g, 0) + 1
            ranked.append(p)
    pois = ranked
    n_backed = sum(1 for p in pois if p.get("blog_mentions"))

    warnings = list(state.get("warnings", []))
    if weather.get("rain"):
        warnings.append(f"비 예보(강수확률 {int((weather.get('pop') or 0) * 100)}%) → 실내 위주로 구성했어요")
        # 분위기 태그가 야외 쪽(자연/산책 등)이면 실내 후보가 거의 안 잡히므로 실내 문서를 따로 더 뽑는다
        try:
            seen = {d["doc_id"] for d in rag_docs}
            q = f"{req['region']} 실내 비오는날 전시 박물관 체험"
            indoor = rag.search(q, moods=["실내(비오는날)"], region=req["region"], k=6, doc_type="place") + rag.search(
                q, moods=["실내(비오는날)"], region=req["region"], k=4, doc_type="blog"
            )
            rag_docs = [d for d in indoor if d["doc_id"] not in seen] + rag_docs
        except Exception as e:  # noqa: BLE001
            log.warning("실내 rag 실패: %s", e)
    if center:
        rag_docs = _near_center(rag_docs, center, RAG_RADIUS_M[_radius_key(req)])
    detail = f"RAG {len(rag_docs)}건 / 웹 {len(web_docs)}건 / 주변 식당·카페 {len(pois)}곳(블로그 근거 {n_backed}곳) / 날씨 {weather.get('summary') or weather.get('note', '-')}"
    if stays:
        detail += f" / 숙소 {len(stays)}곳"
    return {
        "rag_docs": rag_docs,
        "web_docs": web_docs,
        "poi_docs": pois,
        "stay_docs": stays,
        "weather": weather,
        "sun_times": sun,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "retrieve", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


DRAFT_SYSTEM = """당신은 Odiro, 국내 여행·데이트 코스 플래너입니다. 사용자 조건에 맞는 코스를 JSON 으로 설계합니다.

원칙
1. **실제로 존재하는 구체적인 장소명만** 씁니다. 모호한 표현("성수동 감성 카페")이나 지어낸 상호는 금지. 확신이 없으면 유명한 곳을 고릅니다.
   장소명은 지도 앱에 등록된 공식 명칭으로 (예: "가평레일파크", "쁘띠프랑스", "어니언 성수").
2. **[장소 ✔지도확인]** 문서와 **"주변 실존 식당·카페"** 목록은 실존이 확인된 장소입니다. 식당·카페는 가능한 한 이 목록에서 고르고(조건에 맞는 것으로),
   source="rag" 로 표기합니다. 블로그 글에 나온 상호를 쓰면 source="rag", 웹검색은 "web", 일반 지식은 "llm".
   목록에서 **★블로그 언급** 이 붙은 곳은 분위기 근거가 있는 곳이니 분위기·성격을 요청받으면 우선 고르고, reason 은 그 요약 내용으로만 씁니다.
   ★ 가 없는 곳은 분위기를 알 수 없으니 '조용한'·'감성적인' 같은 성격을 단정하지 말고 업종과 위치만 담백하게 씁니다.
3. **Day 마다 반드시 식당 1곳 이상 + 카페 1곳 이상** 을 넣고 나머지를 관광지·놀거리·산책으로 채웁니다 (나들이 뼈대 "밥 1 + 카페 1 + 놀거리 1 + α").
   식사 시간대(11:30~13:30, 17:30~19:30)에 식당이 오도록 순서를 잡습니다. category 는 실제 업종대로 (카페거리·상업시설은 '놀거리', 복합문화공간은 '관광지').
   여행 모드는 Day 별로, 마지막 Day 를 제외하고 숙소를 마지막에 둡니다.
4. 뚜벅이는 장소 간 도보 15분 안쪽(약 1km)으로 촘촘하게, 자차는 반경을 넓혀도 됩니다.
5. 비 예보면 실내(전시·대형 카페·박물관·쇼핑) 위주로, 일몰 태그가 있으면 일몰 시각 즈음 뷰 좋은 곳을 배치합니다.
6. 예산을 넘기지 않게 (1인 식사 1.5~3만, 카페 1만, 입장료 0~2만 기준). 체류 시간은 식당 60~90, 카페 60, 관광지 60~120 분.
7. 같은 장소를 두 번 넣지 않고, 요청된 개수만큼 정확히 채웁니다. Day 마다 예비 후보(spares) 2~3개를 따로 둡니다.
8. **"꼭 넣을 곳" 목록이 주어지면 그중 딱 1곳을 코스에 넣습니다** (사용자가 직접 적은 조건입니다). 코스 전체에서 한 번이면 충분합니다 — Day 마다 넣거나 같은 종류(예: 파스타집, 반지공방)를 두 곳 넣지 않습니다. 추가 조건의 나머지 내용도 장소 선택에 반영합니다.
9. 동행·태그별 배려: 아이 동반이면 술집·노키즈존·조용해야 하는 곳 제외, 반려동물 태그면 동반 가능하다고 확인된 곳 우선, 웨이팅적은 태그면 줄 서는 유명 맛집 대신 예약 가능하거나 한산한 곳,
   자차면 주차가 어려운 골목 상권은 Day 당 1곳 이하로 하고 주차장 있는 곳 위주로 고릅니다.
10. 요일을 봅니다: 월요일은 박물관·미술관·공공 전시관이 대부분 휴관이라 넣지 않습니다. 휴무 여부를 모르는 곳은 그대로 두되 지어내지 않습니다.
11. 여행(2일 이상): **서로 가까운 장소는 같은 Day 에 묶고 Day 마다 다른 권역**을 돕니다. 전날 지나간 길을 다음 날 되짚지 않게 하고, 유명한 곳이 한 권역에 몰려 있으면 하루에 몰아서 봅니다.
    각 Day 는 숙소에서 출발해 숙소로 돌아오는 동선을 생각해 순서를 잡습니다.
12. est_cost(1인 예상 비용)를 장소마다 채우고, 합계가 1인 예산을 넘지 않게 고릅니다.
13. reason 은 제공된 문서(큐레이션·웹)에 적힌 내용으로만 씁니다. 근거 문서가 없는 장소는 업종과 위치 정도만 담백하게 쓰고, 전망·분위기·인기·주변 명소와의 거리 같은 사실을 지어내지 않습니다 (예: 터미널 안 카페를 "호수 전망 카페" 라고 쓰지 않습니다).
14. 전국 어디에나 있는 프랜차이즈(메가커피·스타벅스·맥도날드 등)는 사용자가 요청하지 않는 한 넣지 않습니다. 그 지역에서만 갈 수 있는 곳을 고릅니다."""


def _draft_prompt(state: dict[str, Any], exclude: list[str] | None = None) -> str:
    req = state["request"]
    days = req.get("days", 1) if req.get("mode") == "trip" else 1
    per_day = state.get("per_day", 4)
    wx = state.get("weather") or {}
    wx_line = (
        f"{wx.get('summary')} {wx.get('temp_c')}°C 강수확률 {int((wx.get('pop') or 0) * 100)}%" + (" ⚠ 비" if wx.get("rain") else "")
        if wx.get("available")
        else f"(예보 없음: {wx.get('note', '')})"
    )
    sun = state.get("sun_times") or {}
    center = state.get("center") or {}
    anchor = center.get("label") or req["region"]
    radius_rule = (
        f"모든 장소는 '{anchor}' 중심 반경 1.5km 안 (도보 이동, 장소 간 15분 이내)"
        if req.get("transport") == "walk"
        else f"장소는 '{anchor}' 기준 차로 30~40분 안, 주차 가능한 곳 위주"
    )
    lines = [
        f"## 사용자 조건\n{state['conditions']}\n{radius_rule}",
        f"## 날씨 / 일출·일몰 / 요일\n{wx_line} / 일출 {sun.get('sunrise', '?')} 일몰 {sun.get('sunset', '?')} / {_weekdays_text(req)}",
        f"## 큐레이션 문서 (RAG)\n{_fmt_rag_docs(state.get('rag_docs', []))}",
        f"## 주변 실존 식당·카페 (카카오 지도, ✔지도확인)\n{_fmt_pois(state.get('poi_docs', []))}",
        f"## 웹 검색\n{_fmt_web_docs(state.get('web_docs', []))}",
        f"## 요구 구조\nDay 수: {days}, Day 당 장소 {per_day}개 (정확히) + 예비 {SPARES_PER_DAY}개. 방문 순서대로.",
    ]
    if wx.get("rain"):
        lines.append(
            f"## ⚠ 비 예보 규칙 (반드시 지킬 것)\nDay 마다 야외 장소(indoor=false: 공원·수목원·호수·섬·산책로·전망대·야외 거리)는 최대 {_max_outdoor(req)}곳. "
            "나머지 관광지·놀거리와 예비 후보(spares)는 전부 실내(indoor=true: 전시·박물관·미술관·실내 체험·쇼핑몰·대형 카페)로 고릅니다."
        )
    if state.get("must_docs"):
        lines.append(
            f"## ★ 꼭 넣을 곳 (사용자 추가 조건 '{req.get('free_text', '')}' — 아래 실존 장소 중 1곳을 반드시 포함. category 는 실제 업종, 체험·공방은 '놀거리')\n"
            + _fmt_pois(state["must_docs"])
        )
    if days > 1 and state.get("user_stay"):
        us = state["user_stay"]
        lines.append(
            f"## 숙소 (사용자가 정함)\n{us['name']} ({us.get('address', '')}). 숙소는 시스템이 Day 1~{days - 1} 끝에 자동으로 넣으니 **장소 목록에 숙소를 넣지 마세요**. "
            "매일 이 숙소에서 출발해 돌아오는 것을 기준으로 권역을 나눕니다."
        )
    elif days > 1:
        lines.append(
            f"## 숙소 규칙 (반드시 지킬 것)\nDay 1~{days - 1} 의 **마지막 장소는 category='숙소'** 로, 아래 실존 숙소 목록에서 고릅니다 (Day 당 장소 수에 포함). "
            f"Day {days} 에는 숙소를 넣지 않습니다.\n{_fmt_pois(state.get('stay_docs', []))}"
        )
    if exclude:
        lines.append("## 제외 (이미 쓰였거나 존재 확인 실패)\n" + ", ".join(exclude))
    return "\n\n".join(lines)


def draft_course(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    try:
        draft: CourseDraft = chat(0.4).with_structured_output(CourseDraft).invoke(
            [("system", DRAFT_SYSTEM), ("human", _draft_prompt(state, exclude=state.get("rejected") or None))]
        )
    except Exception as e:  # noqa: BLE001
        log.error("draft 실패: %s", e)
        return {
            "candidates": [],
            "spares": [],
            "title": f"{state['request']['region']} 코스",
            "trace": state["trace"] + [{"node": "draft_course", "status": "error", "ms": _now_ms() - t0, "detail": str(e)[:80]}],
        }
    cap = MAX_PLACES_PER_DAY_TRIP if state["request"].get("mode") == "trip" else MAX_PLACES_PER_DAY
    cands: list[dict[str, Any]] = []
    spares: list[dict[str, Any]] = []
    days = _trip_days(state["request"])
    for d in draft.days:
        # 숙소는 마지막 날(나들이는 당일)에는 넣지 않는다
        kept = [p for p in d.places[:cap] if not (p.category == "숙소" and (d.day >= days or state.get("user_stay")))]
        extra_spares = [p for p in d.spares if p.category != "숙소"]
        while len(kept) < len(d.places[:cap]) and extra_spares:  # 뺀 숙소 자리는 예비 후보로 채워 장소 수를 유지
            kept.append(extra_spares.pop(0))
        promoted = {p.name for p in kept}
        for i, p in enumerate(kept, 1):
            cands.append({**p.model_dump(), "day": d.day, "order": i, "verified": False})
        for p in [p for p in d.spares if p.name not in promoted][:SPARES_PER_DAY + 1]:
            spares.append({**p.model_dump(), "day": d.day, "order": 0, "verified": False})
    detail = f"{len(cands)}곳 초안 + 예비 {len(spares)} ({sum(1 for c in cands if c['source'] == 'rag')} RAG 근거)"
    out: dict[str, Any] = {}
    if (state.get("weather") or {}).get("rain"):
        before = sum(1 for c in cands if _is_outdoor(c))
        cands, spares, leftover = _enforce_rain(cands, spares, _max_outdoor(state["request"]))
        swapped = before - sum(1 for c in cands if _is_outdoor(c))
        if swapped:
            detail += f", 비 예보로 야외 {swapped}곳 → 실내"
        if leftover:
            out["warnings"] = list(state.get("warnings", [])) + [f"실내 대안을 찾지 못해 야외 장소가 {leftover}곳 더 들어갔어요. 우산을 챙기세요"]
    return {
        **out,
        "candidates": cands,
        "spares": spares,
        "title": draft.title,
        "trace": state["trace"] + [{"node": "draft_course", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


_BAKERY_WORDS = ("제과", "베이커리", "디저트")
# TourAPI 콘텐츠 종류 중 볼거리 빈 자리에 쓰면 안 되는 것 (벡터 DB 메타데이터에 한글 명칭으로 저장됨: '음식점', '숙박').
# 음식점에는 카페도 들어 있어 '관광지'로 끼워 넣으면 분류 오류·같은 가게 중복이 생긴다 (가평 '카페 드 모파상')
_NOT_ATTRACTION_TYPES = {"음식점", "숙박"}


def _attraction_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """볼거리 자리를 채울 수 있는 큐레이션 장소 문서 (좌표 있음, 음식점·숙박 제외. content_type 이 없는 문서는 허용)."""
    return [
        d for d in docs
        if d.get("doc_type") == "place" and d.get("lat") and d.get("lng") and d.get("content_type") not in _NOT_ATTRACTION_TYPES
    ]


def _usable_attractions(
    docs: list[dict[str, Any]], in_use: set[str], taken: Any, hub: tuple[float, float], walk: bool, no_outdoor: bool = False
) -> list[dict[str, Any]]:
    """볼거리 후보 문서 중 지금 쓸 수 있는 것: 아직 코스에 없고(이름·같은 가게), 뚜벅이면 그날 동선 중심에서 도보 거리 안, no_outdoor 면 실내만."""
    return [
        d for d in docs
        if d.get("title") not in in_use
        and not taken({"name": d["title"], "lat": float(d["lat"]), "lng": float(d["lng"]), "kakao_place_id": d.get("kakao_place_id", "")})
        and not (walk and haversine_m(hub[0], hub[1], float(d["lat"]), float(d["lng"])) > WALK_OUTLIER_M)
        and not (no_outdoor and _is_outdoor({"category": "관광지", "name": d["title"]}))
    ]


def _kakao_food_role(hit: dict[str, Any]) -> str | None:
    """카카오 업종이 음식점(FD6)이면 '식당', 카페(CE7)이면 '카페'. 제과·베이커리·디저트(FD6)는 코스에서 카페 역할이라 '카페'.
    관광지·문화시설·업종 없음은 None (LLM 분류를 그대로 쓴다)."""
    group = hit.get("category_group", "")
    if group == "CE7":
        return "카페"
    if group == "FD6":
        return "카페" if any(w in (hit.get("category_full") or "") for w in _BAKERY_WORDS) else "식당"
    return None


def _verify_one(c: dict[str, Any], center: dict[str, Any] | None, radius: int, hint: str) -> dict[str, Any]:
    if c.get("verified") and c.get("lat") and c.get("lng"):
        return c  # 수정 흐름에서 이미 검증된 장소
    hit = None
    names = [c["name"]]
    tokens = c["name"].split()
    if len(tokens) >= 3:  # '성수동 애견동반카페 따우전드 성수' → '따우전드 성수' 처럼 수식어를 떼고 한 번 더
        names.append(" ".join(tokens[-2:]))
    try:
        for nm in names:
            if center:
                hit = search_place.verify(nm, center["lat"], center["lng"], radius, hint)
            else:
                res = search_place.search(f"{hint} {nm}", size=3)
                hit = res[0] if res else None
            if hit:
                break
    except Exception as e:  # noqa: BLE001
        log.warning("verify 오류 %s: %s", c["name"], e)
    if not hit:
        return {**c, "verified": False}
    cat = c.get("category") or ""
    group = hit.get("category_group", "")
    # 코스에 올릴 수 없는 업종 (주거·의료·행정 등). 카카오 카테고리 대분류로 거른다.
    top = (hit.get("category_full") or "").split(" > ")[0]
    if top in NON_VENUE_TOP_CATEGORIES and search_place._norm_name(c["name"]) != search_place._norm_name(hit["name"]):
        return {**c, "verified": False}
    # 역할 불일치 방지: '청평호(관광지)' 가 '청평호반닭갈비(식당)' 로 매칭되는 류. 이름이 완전히 같을 때만 예외.
    exact = search_place._norm_name(c["name"]) == search_place._norm_name(hit["name"])
    if not exact:
        if cat in ("관광지", "산책", "놀거리", "쇼핑") and group in ("FD6", "CE7", "AD5"):
            return {**c, "verified": False}
        if cat == "식당" and group in ("AT4", "CT1", "AD5"):
            return {**c, "verified": False}
        if cat == "숙소" and group and group != "AD5":
            return {**c, "verified": False}
    if cat in ("기타", "") and hit.get("category"):
        cat = hit["category"]
    # 식당·카페는 카카오 업종을 따른다 (LLM 이 카페를 '식당'·'놀거리'로, 식당을 '관광지'로 붙이는 일이 있다).
    # 이름이 완전히 같아 위 불일치 검사를 건너뛴 경우에도 적용된다. 숙소는 여행 날짜 구성의 기준이라 그대로 둔다
    kakao_role = _kakao_food_role(hit)
    if kakao_role and cat != "숙소":
        cat = kakao_role
    return {
        **c,
        "verified": True,
        "name": hit["name"],
        "category": cat,
        "lat": hit["lat"],
        "lng": hit["lng"],
        "address": hit.get("address", ""),
        "kakao_place_id": hit.get("kakao_place_id", ""),
        "place_url": hit.get("place_url", ""),
        "phone": hit.get("phone", ""),
        "kakao_category": hit.get("category_full", ""),
    }


def _same_shop(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """두 장소가 같은 가게인지 (카카오 ID 같음, 또는 search_place.same_place 기준). 둘 다 숙소면 False (날마다 같은 숙소는 의도)."""
    if a.get("category") == "숙소" and b.get("category") == "숙소":
        return False
    if a.get("kakao_place_id") and a.get("kakao_place_id") == b.get("kakao_place_id"):
        return True
    if not (a.get("lat") and a.get("lng") and b.get("lat") and b.get("lng")):
        return bool(a.get("name")) and a.get("name") == b.get("name")
    return search_place.same_place(a["name"], a["lat"], a["lng"], b["name"], b["lat"], b["lng"])[0]


# 같은 가게를 하나로 합칠 때 '장소 정보'로 보는 필드 (카카오 ID 가 있는 쪽을 쓴다). 나머지(날짜·순서·체류·이유 등)는 일정 쪽
_PLACE_INFO_KEYS = ("name", "lat", "lng", "address", "kakao_place_id", "place_url", "phone", "kakao_category", "category")


def _merge_same_shop(a: dict[str, Any], b: dict[str, Any], must: bool) -> dict[str, Any]:
    """같은 가게 두 항목을 하나로. 자리(날짜·순서·체류)는 먼저 배정된 쪽, 장소 정보는 카카오 ID 가 있는 쪽(둘 다 있으면 먼저 배정된 쪽).
    must: 둘 중 하나라도 꼭 넣을 곳이면 남는 쪽에 그 표시를 이어 준다."""
    first, second = sorted((a, b), key=lambda p: (p.get("day", 1), p.get("order", 0)))
    info = first if first.get("kakao_place_id") or not second.get("kakao_place_id") else second
    merged = {**first, **{k: info[k] for k in _PLACE_INFO_KEYS if k in info}}
    if must:
        merged["must"] = True
    return merged


def _same_role(a: str, b: str) -> bool:
    food = {"식당"}
    cafe = {"카페"}
    play = {"관광지", "놀거리", "산책", "쇼핑", "기타"}
    for group in (food, cafe, play, {"숙소"}):
        if a in group and b in group:
            return True
    return a == b


def verify_places(state: dict[str, Any]) -> dict[str, Any]:
    """카카오 지도에 없는 장소는 버리고, 빈 자리는 예비 후보 → (부족하면) LLM 보충 1회로 채운다."""
    t0 = _now_ms()
    req, center = state["request"], state.get("center")
    radius = VERIFY_RADIUS.get(req.get("transport", "walk"), 5000)
    if _radius_key(req) == "car_local":  # "인천 송도" 같은 동 단위 요청은 자차여도 그 동네 안에서
        radius = RAG_RADIUS_M["car_local"]
    hint = req["region"]
    cands = list(state.get("candidates", []))
    spares = list(state.get("spares", []))
    rejected: list[str] = list(state.get("rejected", []))

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda c: _verify_one(c, center, radius, hint), cands + spares))
    cands, spares = results[: len(cands)], results[len(cands) :]
    used_ids = {c.get("kakao_place_id") for c in cands if c["verified"]}
    spare_pool = [s for s in spares if s["verified"] and s.get("kakao_place_id") not in used_ids]
    spares_used = 0

    slot = state.get("edit_slot") if not state.get("full_redraft") else None  # 수정 흐름: 바꾸는 자리 하나
    allow_chain = _chains_allowed(req)
    must = (state.get("must_docs") or []) if not slot else []
    must_ids = {m.get("kakao_place_id") for m in must}
    must_kws = [search_place._norm_name(k) for k in (state.get("must_keywords") or [])] if must else []

    def satisfies(c: dict[str, Any]) -> bool:
        """자유 조건으로 꼭 넣어 달라고 한 종류(예: 반지공방, 라구파스타)에 해당하는 장소인지."""
        if not must:
            return False
        if c.get("must"):  # 같은 가게를 합칠 때 꼭 넣을 곳 표시를 이어받은 장소
            return True
        text = search_place._norm_name(c["name"] + (c.get("kakao_category") or c.get("category_full") or ""))
        return (c.get("kakao_place_id") or "-") in must_ids or any(k and k in text for k in must_kws)

    def must_done() -> bool:
        return any(c["verified"] and satisfies(c) for c in cands)

    def taken(cand: dict[str, Any]) -> bool:
        """채울 후보가 이미 코스에 있는 가게인지 (카카오 ID·이름·같은 가게 기준)."""
        return any(x["verified"] and (x.get("name") == cand.get("name") or _same_shop(x, cand)) for x in cands)

    def drop_unwanted() -> None:
        """(1) 프랜차이즈 식당·카페 (2) 꼭 넣을 곳의 두 번째 이후 → 미확인 처리해 다른 곳으로 다시 채운다."""
        targets = [slot["index"]] if slot else range(len(cands))
        seen_must = False
        for i in targets:
            c = cands[i]
            if not c["verified"]:
                continue
            if not allow_chain and c.get("category") in ("식당", "카페") and _is_chain(c["name"]):
                rejected.append(c["name"])
                cands[i] = {**c, "verified": False}
            elif satisfies(c):
                if seen_must:
                    rejected.append(c["name"])
                    cands[i] = {**c, "verified": False, "must_dup": True}
                seen_must = True

    if not allow_chain:
        spares = [s if not (s["verified"] and s.get("category") in ("식당", "카페") and _is_chain(s["name"])) else {**s, "verified": False} for s in spares]
    walk = req.get("transport", "walk") == "walk"
    # 수정 흐름에서는 사용자가 이미 본 나머지 장소를 건드리지 않는다 → 거리 검사는 바꾸는 자리만
    checkable = {slot["index"]} if slot else set(range(len(cands)))

    def nearest_m(i: int, p: dict[str, Any]) -> float | None:
        """같은 날 다른 확인된 장소들의 한가운데 장소(medoid: 나머지와의 거리 합이 가장 작은 곳)까지의 직선거리.

        가장 가까운 이웃이 아니라 medoid 로 재야, 두 무리로 갈라진 코스(무리 사이 도보 25분)도 걸러진다.
        """
        others = [c for j, c in enumerate(cands) if j != i and c["verified"] and c["day"] == p["day"]]
        if len(others) < 2:
            return None
        hub = min(others, key=lambda a: sum(haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) for b in others))
        return haversine_m(p["lat"], p["lng"], hub["lat"], hub["lng"])

    def drop_walk_outliers() -> None:
        """뚜벅이: 동선 중심에서 멀리 떨어진 장소(도보 20분+)는 미확인 처리해 예비 후보·LLM 보충으로 다시 채우게 한다."""
        if not walk:
            return
        while True:
            far = [(d, i) for i in checkable if cands[i]["verified"] and (d := nearest_m(i, cands[i])) is not None and d > WALK_OUTLIER_M]
            if not far:
                return
            _, i = max(far)
            rejected.append(cands[i]["name"])
            cands[i] = {**cands[i], "verified": False, "too_far": True, "too_far_orig": dict(cands[i])}

    def drop_duplicates() -> None:
        """같은 장소가 두 번 들어가면(이름만 다르게 적힌 경우 포함) 뒤쪽을 미확인 처리해 다시 채우게 한다.

        같은 가게 기준은 _same_shop (카카오 ID 또는 search_place.same_place). 앞 자리에는 두 항목을 합친 것을 남긴다
        (장소 정보는 카카오 ID 가 있는 쪽, 꼭 넣을 곳 표시는 이어받음).
        """
        key = lambda c: c.get("kakao_place_id") or c["name"]
        if slot:  # 수정 흐름: 새로 넣는 자리만 검사 (나머지는 건드리지 않는다)
            i = slot["index"]
            if cands[i]["verified"] and any(j != i and c["verified"] and (key(c) == key(cands[i]) or _same_shop(c, cands[i])) for j, c in enumerate(cands)):
                rejected.append(cands[i]["name"])
                cands[i] = {**cands[i], "verified": False}
            return
        for i, c in enumerate(cands):
            if not c["verified"]:
                continue
            j = next(
                (j for j in range(i) if cands[j]["verified"] and (
                    (key(cands[j]) == key(c) and not (c.get("category") == "숙소" and cands[j].get("category") == "숙소" and cands[j]["day"] != c["day"]))
                    or _same_shop(cands[j], c)
                )),
                None,
            )
            if j is None:
                continue
            cands[j] = {**_merge_same_shop(cands[j], c, satisfies(cands[j]) or satisfies(c)), "verified": True}
            rejected.append(c["name"])
            cands[i] = {**c, "verified": False}

    def fill_from_spares() -> None:
        nonlocal spares_used
        for i, c in enumerate(cands):
            if c["verified"]:
                continue
            in_use = {x.get("kakao_place_id") for x in cands if x["verified"]}
            ok = [
                s for s in spare_pool
                if s["day"] == c["day"] and s.get("kakao_place_id") not in in_use and not (must_done() and satisfies(s)) and not (walk and (d := nearest_m(i, s)) is not None and d > WALK_OUTLIER_M)
            ]
            pick = next((s for s in ok if _same_role(s["category"], c["category"])), None)
            # 수정 흐름, 그리고 식당·카페 자리는 역할이 다른 장소로 대신하지 않는다 (카페 자리가 놀거리로 바뀌어 카페 0곳이 되는 일 방지).
            # 비워 두면 아래 '확인된 후보로 채움' 이 카카오 주변 식당·카페(같은 업종)로 채운다
            if pick is None and not slot and c.get("category") not in ("식당", "카페"):
                pick = next(iter(ok), None)
            if pick:
                spare_pool.remove(pick)
                spares_used += 1
                if c["name"] not in rejected:
                    rejected.append(c["name"])
                cands[i] = {**pick, "order": c["order"], "day": c["day"]}

    drop_duplicates()
    drop_unwanted()
    drop_walk_outliers()
    fill_from_spares()
    rounds = 0
    while rounds < MAX_VERIFY_ROUNDS and any(not c["verified"] for c in cands):
        missing = [i for i, c in enumerate(cands) if not c["verified"]]
        rejected += [cands[i]["name"] for i in missing]
        rounds += 1
        used = [c["name"] for c in cands if c["verified"]]
        prompt = (
            _draft_prompt(state, exclude=rejected + used)
            + "\n\n## 요청\n아래 슬롯의 장소가 지도에서 확인되지 않았습니다. 각 슬롯에 **같은 역할(카테고리)** 의, 지도 앱에 확실히 등록된 유명한 장소를 제안하세요.\n"
            + "\n".join(
                f"- 슬롯 {i}: Day {cands[i]['day']} {cands[i]['order']}번째, 역할 {cands[i]['category']}, 원래 제안 '{cands[i]['name']}'"
                + (" (다른 장소들과 너무 멀어 제외 → 도보 15분 안쪽으로)" if cands[i].get("too_far") else "")
                + (" (같은 종류가 이미 코스에 있음 → 다른 종류의 장소로)" if cands[i].get("must_dup") else "")
                for i in missing
            )
            + (f"\n\n## 사용자 수정 요청 (새 장소는 이 요청을 만족해야 함)\n{state['instruction']}" if slot and state.get("instruction") else "")
        )
        try:
            reps: Replacements = chat(0.5).with_structured_output(Replacements).invoke([("system", DRAFT_SYSTEM), ("human", prompt)])
        except Exception as e:  # noqa: BLE001
            log.warning("대체 후보 요청 실패: %s", e)
            break
        by_slot = {r.slot: r.place for r in reps.items if r.slot in missing}
        todo = [i for i in missing if i in by_slot]
        for i in todo:
            cands[i] = {**cands[i], **by_slot[i].model_dump(), "verified": False}
        if not todo:
            break
        with ThreadPoolExecutor(max_workers=8) as ex:
            res = list(ex.map(lambda i: _verify_one(cands[i], center, radius, hint), todo))
        for i, r in zip(todo, res, strict=True):
            cands[i] = r
        drop_duplicates()
        drop_unwanted()
        drop_walk_outliers()
        fill_from_spares()

    # 그래도 빈 자리는 이미 실존이 확인된 후보(주변 식당·카페, 좌표가 있는 큐레이션 장소 문서)로 채운다 → 장소 수가 줄지 않게
    known_used = 0
    if not slot:
        rain = bool((state.get("weather") or {}).get("rain"))
        for i, c in enumerate(cands):
            if c["verified"] or c.get("too_far_orig") or c.get("category") == "숙소":
                continue
            in_use = {x.get("kakao_place_id") for x in cands if x["verified"]} | {x["name"] for x in cands if x["verified"]}
            same_day = [x for x in cands if x["verified"] and x["day"] == c["day"]]
            hub = _centroid(same_day) if same_day else ((center["lat"], center["lng"]) if center else None)
            if hub is None:
                continue
            if c.get("category") in ("식당", "카페"):
                pool = [
                    {"name": h["name"], "lat": h["lat"], "lng": h["lng"], "address": h.get("address", ""), "kakao_place_id": h.get("kakao_place_id", ""),
                     "place_url": h.get("place_url", ""), "phone": h.get("phone", ""), "kakao_category": h.get("category_full", "")}
                    for h in state.get("poi_docs", [])
                    # 역할은 카카오 업종으로 (제과·베이커리·디저트 음식점은 카페 자리 후보)
                    if _kakao_food_role(h) == c["category"] and h.get("kakao_place_id") not in in_use
                    and (allow_chain or not _is_chain(h["name"])) and not (must_done() and satisfies(h))
                ]
            else:
                pool = [
                    {"name": d["title"], "lat": float(d["lat"]), "lng": float(d["lng"]), "address": d.get("addr") or "", "kakao_place_id": "",
                     "reason": d.get("one_line") or c.get("reason", ""), "image": d.get("image") or ""}
                    for d in _attraction_docs(state.get("rag_docs", []))
                    if d.get("title") not in in_use
                    and not (rain and _is_outdoor({"category": "관광지", "name": d["title"]}))
                ]
            pool = [h for h in pool if not taken(h)]  # 띄어쓰기·지점명만 다른 같은 가게도 이미 쓴 것으로 본다
            if walk:
                pool = [h for h in pool if haversine_m(hub[0], hub[1], h["lat"], h["lng"]) <= WALK_OUTLIER_M]
            if not pool:
                continue
            h = min(pool, key=lambda x: haversine_m(hub[0], hub[1], x["lat"], x["lng"]))
            # 실패한 원래 후보의 추천 이유·태그를 물려받으면 엉뚱한 설명이 붙는다(터미널 카페에 "호수 전망") → 담백한 문구로 바꾼다
            neutral = {"reason": h.get("reason") or f"{req['region']} 동선에서 가까운 {c.get('category') or '장소'}", "tags": [], "review_summary": ""}
            cands[i] = {**c, **h, **neutral, "source": "rag", "verified": True}
            known_used += 1

    # 볼거리가 하나도 없는 날(카페·식당만 이어지는 코스)은 남는 카페/식당 한 자리를 큐레이션 장소(좌표 있는 관광지 문서)로 바꾼다
    play_added = 0
    if not slot:
        rain = bool((state.get("weather") or {}).get("rain"))
        for day in sorted({c["day"] for c in cands if c["verified"]}):
            idxs = [i for i, c in enumerate(cands) if c["verified"] and c["day"] == day and c.get("category") != "숙소"]
            if len(idxs) < 3 or any(cands[i].get("category") in PLAY_CATEGORIES for i in idxs):
                continue
            cafes = [i for i in idxs if cands[i].get("category") == "카페"]
            eats = [i for i in idxs if cands[i].get("category") == "식당"]
            victim = cafes[-1] if len(cafes) >= 2 else (eats[-1] if len(eats) >= 2 else None)
            if victim is None:
                continue
            in_use = {x["name"] for x in cands if x["verified"]}
            hub = _centroid([cands[i] for i in idxs])
            # 쓸 수 있는(가깝고 아직 안 쓴) 큐레이션 볼거리가 없으면 지도 볼거리 검색으로 넘어간다
            # (큐레이션 문서가 있어도 전부 멀면 예전에는 검색을 건너뛰어 볼거리 0곳으로 남았다)
            pool = _usable_attractions(_attraction_docs(state.get("rag_docs", [])), in_use, taken, hub, walk) or _usable_attractions(
                _find_attractions(req, hub, rain), in_use, taken, hub, walk
            )
            indoor = [d for d in pool if not _is_outdoor({"category": "관광지", "name": d["title"]})]
            pool = (indoor or pool) if rain else pool  # 비 예보면 실내 우선, 없으면 야외라도 한 곳은 넣는다
            if not pool:
                continue
            d = min(pool, key=lambda x: haversine_m(hub[0], hub[1], float(x["lat"]), float(x["lng"])))
            old = cands[victim]
            cands[victim] = {
                "name": d["title"], "category": "관광지", "reason": f"이 지역에서 들러 볼 만한 곳 ({d['one_line']})" if d.get("one_line") else "이 지역에서 들러 볼 만한 곳", "stay_min": 90,
                "indoor": not _is_outdoor({"category": "관광지", "name": d["title"]}), "tags": [], "source": "rag", "est_cost": 0,
                "day": day, "order": old["order"], "verified": True, "lat": float(d["lat"]), "lng": float(d["lng"]),
                "address": d.get("addr") or "", "kakao_place_id": d.get("kakao_place_id", ""), "place_url": d.get("place_url", ""),
                "image": d.get("image") or "",
            }
            play_added += 1

    # 한 날에 식당·카페가 3곳 이상이면 넘치는 자리를 볼거리로 바꾸고, 식당이 연달아 나오면 시간대 순서로 다시 줄 세운다
    meals_fixed = 0
    if not slot:
        rain = bool((state.get("weather") or {}).get("rain"))
        for day in sorted({c["day"] for c in cands if c["verified"]}):
            day_idx = [i for i, c in enumerate(cands) if c["verified"] and c["day"] == day and c.get("category") != "숙소"]
            if len(day_idx) < 3:
                continue
            hub = _centroid([cands[i] for i in day_idx])
            pool: list[dict[str, Any]] | None = None
            searched = False  # 이 날 지도 볼거리 검색을 했는지 (한 번만)
            for role in ("식당", "카페"):
                same = [i for i in day_idx if cands[i].get("category") == role]
                movable = [i for i in same if not satisfies(cands[i])]  # 사용자가 꼭 넣어 달라고 한 곳은 건드리지 않는다
                while len(same) > 2 and movable:
                    if pool is None:
                        pool = _attraction_docs(state.get("rag_docs", []))
                        searched = not pool
                        if searched:
                            pool = list(_find_attractions(req, hub, rain))
                    in_use = {x["name"] for x in cands if x["verified"]}
                    ok = _usable_attractions(pool, in_use, taken, hub, walk, no_outdoor=rain)
                    if not ok and not searched:  # 큐레이션 볼거리가 전부 멀거나 이미 쓰였으면 지도 볼거리 검색으로 한 번 더
                        searched = True
                        pool = pool + list(_find_attractions(req, hub, rain))
                        ok = _usable_attractions(pool, in_use, taken, hub, walk, no_outdoor=rain)
                    if not ok:
                        break
                    d = min(ok, key=lambda x: haversine_m(hub[0], hub[1], float(x["lat"]), float(x["lng"])))
                    victim = movable.pop()
                    same.remove(victim)
                    cands[victim] = {
                        "name": d["title"], "category": "관광지",
                        "reason": f"이 지역에서 들러 볼 만한 곳 ({d['one_line']})" if d.get("one_line") else "이 지역에서 들러 볼 만한 곳",
                        "stay_min": 90, "indoor": True, "tags": [], "source": "rag", "est_cost": 0, "day": day, "order": cands[victim]["order"],
                        "verified": True, "lat": float(d["lat"]), "lng": float(d["lng"]), "address": d.get("addr") or "",
                        "kakao_place_id": d.get("kakao_place_id", ""), "place_url": d.get("place_url", ""), "image": d.get("image") or "",
                    }
                    meals_fixed += 1
            cats = [cands[i].get("category") for i in day_idx]
            if any(a == b == "식당" for a, b in itertools.pairwise(cats)):  # 식당 → 식당 으로 이어지면 점심·저녁으로 떼어 놓는다
                seq = _day_sequence([cands[i] for i in day_idx])
                for n, (i, pl) in enumerate(zip(day_idx, seq, strict=True)):
                    cands[i] = {**pl, "order": n + 1, "fixed_order": True}
                meals_fixed += 1

    warnings = list(state.get("warnings", []))
    extra: dict[str, Any] = {}
    for i, c in enumerate(cands):
        if not c["verified"] and c.get("too_far_orig") and not (slot and slot["index"] == i):
            cands[i] = c["too_far_orig"]  # 대신할 곳을 못 찾았으면 지우지 않고 원래 장소를 두되 알린다
            warnings.append(f"'{cands[i]['name']}' 은(는) 다른 장소들과 조금 떨어져 있어요 (도보 20분 이상)")

    # 하루 카페·식당 최소 1곳: 장소 3곳 이상인 날에 카페(식당)가 0곳이면, 남는 자리 하나를 이미 받아 둔 카카오 주변 카페(식당)로 바꾼다.
    # 바꿀 자리: 볼거리가 2곳 이상이면 볼거리 → (카페가 없을 때) 식당이 2곳 이상이고 종료 18:00 이하면 식당 / (식당이 없을 때) 카페가 2곳 이상이면 카페.
    # 꼭 넣을 곳·숙소는 바꾸지 않고, 새 검색·LLM 호출 없이 poi_docs 만 쓴다. 못 바꾸면 그대로 두고 경고 한 줄.
    role_fixed = 0
    if not slot:
        end_by_18 = _hhmm_to_min(req.get("end_time", "20:00")) <= 18 * 60
        day_prefix = (lambda d: f"Day {d} ") if _trip_days(req) > 1 else (lambda d: "")
        for day in sorted({c["day"] for c in cands if c["verified"]}):
            for need in ("카페", "식당"):
                idx = [i for i, c in enumerate(cands) if c["verified"] and c["day"] == day and c.get("category") != "숙소"]
                if len(idx) < 3 or any(cands[i].get("category") == need for i in idx):
                    continue
                plays = [i for i in idx if cands[i].get("category") in PLAY_CATEGORIES]
                eats = [i for i in idx if cands[i].get("category") == "식당"]
                cafes = [i for i in idx if cands[i].get("category") == "카페"]
                # 꼭 넣을 곳은 바꾸지 않는다 (숙소는 idx 에서 이미 빠짐)
                free_plays, free_eats, free_cafes = ([i for i in g if not satisfies(cands[i])] for g in (plays, eats, cafes))
                victim = None
                if len(plays) >= 2 and free_plays:
                    victim = free_plays[-1]
                elif need == "카페" and end_by_18 and len(eats) >= 2 and free_eats:
                    victim = free_eats[-1]
                elif need == "식당" and len(cafes) >= 2 and free_cafes:
                    victim = free_cafes[-1]
                hub = _centroid([cands[i] for i in idx])
                pool = [
                    h for h in state.get("poi_docs", [])
                    if _kakao_food_role(h) == need and (allow_chain or not _is_chain(h["name"]))  # 제과점은 카페 후보
                    and not taken(h) and not (must_done() and satisfies(h))
                    and not (walk and haversine_m(hub[0], hub[1], h["lat"], h["lng"]) > WALK_OUTLIER_M)
                ]
                if victim is None or not pool:
                    obj = "를" if need == "카페" else "을"
                    warnings.append(f"{day_prefix(day)}{need}{obj} 넣을 자리나 근처 {need} 후보를 찾지 못해 {need} 없이 구성했어요")
                    continue
                h = min(pool, key=lambda x: haversine_m(hub[0], hub[1], x["lat"], x["lng"]))
                old = cands[victim]
                cands[victim] = {
                    "name": h["name"], "category": need, "reason": f"{req['region']} 동선에서 가까운 {need}", "stay_min": 60, "indoor": True,
                    "tags": [], "source": "rag", "est_cost": 0, "day": day, "order": old["order"], "verified": True,
                    "lat": h["lat"], "lng": h["lng"], "address": h.get("address", ""), "kakao_place_id": h.get("kakao_place_id", ""),
                    "place_url": h.get("place_url", ""), "phone": h.get("phone", ""), "kakao_category": h.get("category_full", ""),
                    **({"fixed_order": True} if old.get("fixed_order") else {}),
                }
                rejected.append(old["name"])
                role_fixed += 1

    # 수정 흐름: 교체 장소를 끝내 확인하지 못했거나(또는 이미 코스에 있는 곳이면) 자리를 비우지 않고 원래 장소를 유지한다.
    # 안내 문구는 처음 고른 후보가 아니라 실제로 들어간 장소 기준으로 다시 쓴다.
    if slot:
        idx, old = slot["index"], slot["old"]
        cur = cands[idx]
        dup = cur["verified"] and any(
            j != idx and c["verified"] and c.get("kakao_place_id") and c.get("kakao_place_id") == cur.get("kakao_place_id")
            for j, c in enumerate(cands)
        )
        if not cur["verified"] or dup:
            cands[idx] = {**old, "verified": True}
            extra["edit_note"] = f"요청에 맞는 장소를 지도에서 확인하지 못해 '{old['name']}' 을(를) 그대로 뒀어요"
            warnings.append(extra["edit_note"])
        else:
            note = f"{old['name']} → {cur['name']}"
            planned = slot.get("planned") or ""
            if planned and search_place.name_similarity(search_place._norm_name(planned), search_place._norm_name(cur["name"])) < search_place.MATCH_THRESHOLD:
                note += f" (처음 고른 '{planned}' 은(는) 지도에서 확인되지 않아 다른 곳으로 골랐어요)"
            extra["edit_note"] = note

    # 자유 조건으로 꼭 넣어 달라고 한 곳(예: 반지공방): 초안이 빠뜨렸으면 지도에서 찾아 둔 실존 후보를 볼거리 자리 하나와 바꿔 넣는다
    must_added = ""
    if must:
        live = [c for c in cands if c["verified"]]
        if live and not any(satisfies(c) for c in live):
            taken = {c.get("kakao_place_id") for c in live}
            pool = [m for m in must if m.get("kakao_place_id") not in taken]
            if pool:
                first_day = min(c["day"] for c in live)
                hub = _centroid([c for c in live if c["day"] == first_day])
                m = min(pool, key=lambda h: haversine_m(hub[0], hub[1], h["lat"], h["lng"]))
                role = {"FD6": "식당", "CE7": "카페"}.get(m.get("category_group", ""), "놀거리")
                new = {
                    "name": m["name"], "category": role, "reason": f"요청하신 '{m['keyword']}' — 추가 조건에 맞춰 넣은 곳", "stay_min": 60 if role != "놀거리" else 90,
                    "indoor": True, "tags": [], "source": "rag", "est_cost": 0, "verified": True, "lat": m["lat"], "lng": m["lng"],
                    "address": m.get("address", ""), "kakao_place_id": m.get("kakao_place_id", ""), "place_url": m.get("place_url", ""),
                    "phone": m.get("phone", ""), "kakao_category": m.get("category_full", ""),
                }
                same_role = PLAY_CATEGORIES if role == "놀거리" else {role}
                victims = [i for i, c in enumerate(cands) if c["verified"] and c["day"] == first_day and c.get("category") in same_role]
                if victims:
                    i = victims[-1] if role == "놀거리" else victims[0]  # 식당이면 점심 자리와 바꾼다
                    cands[i] = {**new, "day": cands[i]["day"], "order": cands[i]["order"]}
                else:
                    cands.append({**new, "day": first_day, "order": 50})
                must_added = m["name"]

    # 여행 모드: (1) 가까운 장소끼리 같은 날로 묶고 (2) 마지막 날을 뺀 각 Day 를 숙소로 끝낸다.
    # 숙소는 사용자가 적은 곳 > 초안이 고른 곳 > 모든 날의 중심에서 가까운 실존 숙소 순.
    stays_added = 0
    regrouped = False
    days = _trip_days(req)
    if days > 1 and not slot:
        user_stay = state.get("user_stay")
        live = [c for c in cands if c["verified"]]
        if user_stay:
            live = [c for c in live if c.get("category") != "숙소"]
        grouped = _regroup_days(live, days)
        regrouped = any(c.get("fixed_order") for c in grouped)
        if regrouped and not user_stay:  # 날짜 배정이 바뀌었으면 초안이 고른 숙소는 위치가 안 맞을 수 있어 다시 고른다
            grouped = [c for c in grouped if c.get("category") != "숙소"]
        cands = grouped + [c for c in cands if not c["verified"]]
        need = [d for d in range(1, days) if any(c["verified"] and c["day"] == d for c in cands) and not any(c["verified"] and c["day"] == d and c.get("category") == "숙소" for c in cands)]
        if need:
            pick = user_stay
            if not pick:
                taken = {c.get("kakao_place_id") for c in cands if c["verified"]}
                pool = [s for s in (state.get("stay_docs") or _find_stays(req, center)) if s.get("kakao_place_id") not in taken]
                hubs = [_centroid(ps) for d in range(1, days + 1) if (ps := [c for c in cands if c["verified"] and c["day"] == d])]
                if pool and hubs:  # 매일 이 숙소에서 나갔다 돌아오므로 모든 날의 중심에서 고르게 가까운 곳
                    pick = min(pool, key=lambda h: sum(haversine_m(c[0], c[1], h["lat"], h["lng"]) for c in hubs))
            if pick:
                reason = "직접 정하신 숙소" if user_stay else "하루를 마치고 쉬어 가는 숙소 (각 날의 동선에서 고르게 가까운 곳)"
                for d in need:
                    cands.append(_stay_place(pick, d, reason))
                    stays_added += 1
            else:
                warnings.append("숙소를 찾지 못했어요. 숙소는 따로 예약해 주세요")

    # 1인 예상 비용 합계가 예산을 넘으면 알린다 (추정치, 숙박비 제외)
    budget = int(req.get("budget") or 0)
    est_total = sum(int(c.get("est_cost") or 0) for c in cands if c["verified"] and c.get("category") != "숙소")
    if budget and est_total > budget:
        warnings.append(f"1인 예상 비용이 약 {est_total:,}원으로 예산 {budget:,}원을 넘어요 (추정치, 숙박비 제외)")

    # 미검증 제거 + 같은 장소 중복 제거 (안전망: 앞 단계에서 못 잡은 같은 가게를 합친다. 여기서는 더 채울 경로가 없어 장소 수가 준다)
    verified: list[dict[str, Any]] = []
    for c in cands:
        if not c["verified"]:
            continue
        key = c.get("kakao_place_id") or c["name"]
        if c.get("category") == "숙소":
            # 숙소는 같은 날 같은 숙소만 중복 (날마다 같은 숙소는 의도)
            dup = next((k for k, v in enumerate(verified) if v.get("category") == "숙소" and v["day"] == c["day"] and (v.get("kakao_place_id") or v["name"]) == key), None)
        else:
            dup = next((k for k, v in enumerate(verified) if _same_shop(v, c) or (v.get("kakao_place_id") or v["name"]) == key), None)
        if dup is None:
            verified.append(c)
            continue
        verified[dup] = _merge_same_shop(verified[dup], c, satisfies(verified[dup]) or satisfies(c))
    dropped = len(cands) - len(verified)
    if dropped:
        warnings.append(f"지도에서 확인되지 않았거나 중복된 장소 {dropped}곳을 제외했어요")
    detail = f"{len(verified)}/{len(cands)} 확인 (예비 {spares_used}개 사용, LLM 보충 {rounds}회)"
    if stays_added:
        detail += f", 숙소 {stays_added}곳 보충"
    if known_used:
        detail += f", 확인된 후보로 {known_used}곳 채움"
    if play_added:
        detail += f", 볼거리 {play_added}곳 추가"
    if meals_fixed:
        detail += ", 식당·카페 수와 순서 조정"
    if role_fixed:
        detail += f", 카페·식당 없는 날 {role_fixed}곳 보충"
    if regrouped:
        detail += ", 가까운 곳끼리 날짜 재배정"
    if must_added:
        detail += f", 요청 장소 '{must_added}' 추가"
    return {
        **extra,
        "verified": verified,
        "rejected": rejected,
        "retry_count": rounds,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "verify_places", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


# ---------- 식사 시각 (묶음 2) ----------
# M1: 식당이 2곳 이상인 날은 식사 순서 틀을 쓰되, 직선 동선이 이만큼 이상 늘고(비율) 늘어난 거리도 한도를 넘으면 쓰지 않는다.
# 비율 1.3 은 _best_order 가 '의미 있는 차이'로 보는 25% 와 비슷한 크기, 거리 한도는 기존 상수(도보 20분 거리·자차 동네 반경)를 쓴다
MEAL_ORDER_MAX_GROWTH = 1.3
MEAL_ORDER_MAX_ADDED_M = {"walk": WALK_OUTLIER_M, "car": RAG_RADIUS_M["car_local"]}
LUNCH_RULE_START_MAX = "10:30"  # 점심 규칙(M3): 그날 출발이 이 시각 이하
FIRST_MEAL_NOT_BEFORE = "11:00"  # M3: 첫 식당 도착이 이보다 이르면 볼거리·카페 하나를 앞으로
DINNER_RULE_START_MAX = "15:00"  # 저녁 규칙(M2·M4): 출발 ≤ 15:00 이고
DINNER_RULE_END_MIN = "19:00"  # 종료 ≥ 19:00 인 날만
DINNER_AT = "17:30"  # M2·M4: 저녁 식당 도착을 이 시각 이후로 맞춘다
DINNER_WINDOW = ("17:00", "20:30")  # M4: 이 사이에 도착하는 식당이 없으면 저녁 식당을 덧붙일지 본다
STAY_STRETCH_MAX = 30  # M2: 저녁 앞 카페·볼거리 체류를 장소당 이만큼까지 늘린다
FREE_TIME_NOTE_MIN = 10  # 저녁 전 자유 시간이 이 이상일 때만 안내 문구를 붙인다 (몇 분 차이는 문구 없이)


def _path_m(seq: list[dict[str, Any]], start: dict[str, Any] | None = None) -> int:
    """직선거리 합 (전날 숙소에서 출발하면 그 구간 포함). _best_order 와 같은 계산."""
    pts = ([start] if start else []) + seq
    return sum(haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) for a, b in itertools.pairwise(pts))


def _est_leg_min(a: dict[str, Any], b: dict[str, Any], transport: str) -> int:
    """직선거리로 어림한 이동 시간 (길찾기 호출 없음). 뚜벅이 먼 구간은 get_route 처럼 대중교통으로 본다."""
    d = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
    mode = "transit" if transport == "walk" and d > get_route.WALK_MAX_M else transport
    return estimate_minutes(d, mode)


def _est_arrivals(seq: list[dict[str, Any]], start_min: int, transport: str) -> list[int]:
    """직선거리 어림으로 본 장소별 도착 시각(분). 순서를 정하는 판단에만 쓰고, 화면 시각은 실제 구간으로 다시 계산한다."""
    t, out = start_min, []
    for i, p in enumerate(seq):
        out.append(t)
        t += int(p.get("stay_min", 60))
        if i + 1 < len(seq):
            t += _est_leg_min(p, seq[i + 1], transport)
    return out


def _lunch_not_too_early(ordered: list[dict[str, Any]], start_min: int, transport: str) -> list[dict[str, Any]]:
    """M3: 첫 식당 도착이 11:00 보다 이르면 그 뒤의 볼거리·카페 하나를 식당 앞으로 (식당끼리 순서·숙소 끝 자리는 그대로)."""
    body = [p for p in ordered if p.get("category") != "숙소"]
    stays = [p for p in ordered if p.get("category") == "숙소"]
    eat = next((i for i, p in enumerate(body) if p.get("category") == "식당"), None)
    if eat is None or _est_arrivals(body, start_min, transport)[eat] >= _hhmm_to_min(FIRST_MEAL_NOT_BEFORE):
        return ordered
    mover = next((j for j in range(eat + 1, len(body)) if body[j].get("category") != "식당"), None)
    if mover is None:
        return ordered
    body.insert(eat, body.pop(mover))
    return body + stays


def _timeline(
    seq: list[dict[str, Any]], seq_legs: list[dict[str, Any]], start_min: int,
    stay_of: dict[int, int] | None = None, not_before: dict[int, int] | None = None,
) -> tuple[list[int], int]:
    """분 단위(자정 넘김 없음) 도착 시각들과, 숙소를 뺀 마지막 장소가 끝나는 시각.
    stay_of: 늘린 체류(id(장소) → 분), not_before: 이 시각 전에는 도착하지 않음(먼저 닿으면 그 사이는 자유 시간)."""
    stay_of, not_before = stay_of or {}, not_before or {}
    t = start_min
    arrives, body_end = [], t
    for i, p in enumerate(seq):
        t = max(t, not_before.get(id(p), t))
        arrives.append(t)
        t += stay_of.get(id(p), int(p.get("stay_min", 60)))
        if p.get("category") != "숙소":
            body_end = t
        if i < len(seq_legs):
            t += seq_legs[i]["duration_min"]
    return arrives, body_end


def _push_dinner(
    ordered: list[dict[str, Any]], arrives: list[int], stay_of: dict[int, int], not_before: dict[int, int]
) -> int | None:
    """M2: 숙소를 뺀 마지막 장소가 식당이고(그날 식당 2곳+) 17:30 전에 닿으면, 바로 앞에 이어진 카페·볼거리 체류를
    각 최대 +30분 늘리고(가까운 것부터), 남는 시간은 저녁 전 자유 시간으로 둔다. stay_of·not_before 를 채우고 자유 시간(분)을 돌려준다.
    대상이 아니면 None. 종료 시각 검사는 부르는 쪽에서 한다."""
    body = [i for i, p in enumerate(ordered) if p.get("category") != "숙소"]
    if sum(ordered[i].get("category") == "식당" for i in body) < 2 or ordered[body[-1]].get("category") != "식당":
        return None
    last = body[-1]
    gap = _hhmm_to_min(DINNER_AT) - arrives[last]
    if gap <= 0:
        return None
    for i in reversed(body[:-1]):
        if ordered[i].get("category") == "식당" or gap <= 0:  # 점심 식당을 넘어가면 점심 시각까지 밀리므로 거기서 멈춘다
            break
        add = min(STAY_STRETCH_MAX, gap)
        stay_of[id(ordered[i])] = int(ordered[i].get("stay_min", 60)) + add
        gap -= add
    not_before[id(ordered[last])] = _hhmm_to_min(DINNER_AT)
    return gap


def _dinner_to_add(
    ordered: list[dict[str, Any]], start_min: int, limit: int, transport: str, state: dict[str, Any], taken: list[dict[str, Any]], day: int
) -> tuple[dict[str, Any] | None, bool]:
    """M4: 저녁 규칙 날에 17:00~20:30 도착 식당이 없고 식당이 2곳 미만이며, 마지막 장소 뒤로 이동 + 60분이 종료 시각 안에
    들어가면(직선 어림) 이미 받아 둔 카카오 주변 식당(poi_docs) 중 마지막 장소에서 가장 가까운 곳을 고른다. 새 검색·LLM 호출 없음.
    돌려주는 값: (덧붙일 장소 또는 None, 시간은 되는데 후보가 없었는지)."""
    req = state["request"]
    body = [p for p in ordered if p.get("category") != "숙소"]
    if not body or sum(p.get("category") == "식당" for p in body) >= 2:
        return None, False
    arr = _est_arrivals(body, start_min, transport)
    lo, hi = (_hhmm_to_min(x) for x in DINNER_WINDOW)
    if any(lo <= a <= hi for a, p in zip(arr, body, strict=True) if p.get("category") == "식당"):
        return None, False
    dinner, stay = _hhmm_to_min(DINNER_AT), 60
    end_est = arr[-1] + int(body[-1].get("stay_min", 60))
    if max(end_est, dinner) + stay > limit:
        return None, False
    hub = _centroid(body)
    radius = WALK_OUTLIER_M if transport == "walk" else RAG_RADIUS_M["car_local"]
    allow_chain = _chains_allowed(req)
    pool = [
        h for h in state.get("poi_docs", [])
        if _kakao_food_role(h) == "식당" and (allow_chain or not _is_chain(h["name"]))  # 제과·베이커리는 카페 역할이라 빠진다
        and haversine_m(hub[0], hub[1], h["lat"], h["lng"]) <= radius
        and not any(_same_shop({**h, "category": "식당"}, t) for t in taken)
    ]
    if not pool:
        return None, True
    last = body[-1]
    h = min(pool, key=lambda x: haversine_m(last["lat"], last["lng"], x["lat"], x["lng"]))
    if max(end_est + _est_leg_min(last, h, transport), dinner) + stay > limit:
        return None, False
    return {
        "name": h["name"], "category": "식당", "reason": f"{req['region']} 동선에서 가까운 식당", "stay_min": stay, "indoor": True,
        "tags": [], "source": "rag", "est_cost": 0, "day": day, "order": len(ordered) + 1, "verified": True,
        "lat": h["lat"], "lng": h["lng"], "address": h.get("address", ""), "kakao_place_id": h.get("kakao_place_id", ""),
        "place_url": h.get("place_url", ""), "phone": h.get("phone", ""), "kakao_category": h.get("category_full", ""),
    }, False


def _best_order(places: list[dict[str, Any]], start: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """LLM 순서를 기본으로 하되, 순열 전수로 총거리가 25% 이상 줄면 그 순서를 쓴다 (n ≤ 6).

    숙소는 항상 그날의 맨 끝에 두고, 거리 계산에는 출발점(start: 전날 숙소)과 도착점(그날 숙소)까지의 구간도 넣는다.
    """
    stays = [p for p in places if p.get("category") == "숙소"]
    rest = [p for p in places if p.get("category") != "숙소"]
    end = stays[0] if stays else None
    if any(p.get("fixed_order") for p in rest):  # 시간대 틀로 이미 정한 순서
        return rest + stays
    if len(rest) < 2 or (len(rest) == 2 and not start and not end):
        return rest + stays

    def total(order: list[dict[str, Any]]) -> int:
        seq = ([start] if start else []) + order + ([end] if end else [])
        return sum(haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) for a, b in itertools.pairwise(seq))

    base = total(rest)
    best, best_d = rest, base
    if len(rest) <= MAX_PLACES_PER_DAY:
        for perm in itertools.permutations(rest):
            d = total(list(perm))
            if d < best_d:
                best, best_d = list(perm), d
    return (best if best_d < base * 0.75 else rest) + stays


def _hhmm_add(hhmm: str, minutes: int) -> str:
    t = datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _min_to_hhmm(minutes: int) -> str:
    """분 → 'HH:MM'. 자정을 넘기면 24:30 처럼 이어서 표기 (0시로 되돌리지 않는다)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def optimize_route(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    req = state["request"]
    transport = req.get("transport", "walk")
    by_day: dict[int, list[dict[str, Any]]] = {}
    for p in state.get("verified", []):
        by_day.setdefault(p.get("day", 1), []).append(p)

    places: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    warnings = list(state.get("warnings", []))
    prev_stay: dict[str, Any] | None = None  # 둘째 날부터는 전날 숙소에서 출발하는 동선으로 순서를 잡는다
    # 수정 흐름(장소 하나 바꾸기·시작 시각 변경)에서는 사용자가 이미 본 순서를 다시 짜거나 장소를 덧붙이지 않는다 (M1·M3·M4)
    editing = bool(state.get("instruction"))
    notes: list[str] = []
    added_dinners: list[dict[str, Any]] = []  # M4 로 덧붙인 식당 (다른 날 같은 가게를 또 넣지 않게)
    for day in sorted(by_day):
        ordered = _best_order(by_day[day], start=prev_stay)
        # 거리만 보고 순서를 잡으면 식당 → 식당 처럼 식사가 붙을 수 있다 → 시간대 틀(볼거리 → 점심 → 카페 → … → 저녁)로 다시 줄 세운다
        body = [p for p in ordered if p.get("category") != "숙소"]
        stays = [p for p in ordered if p.get("category") == "숙소"]
        if len(body) >= 3 and any(a.get("category") == b.get("category") == "식당" for a, b in itertools.pairwise(body)):
            ordered = _day_sequence(body) + stays
        elif (
            len(body) >= 3 and sum(p.get("category") == "식당" for p in body) >= 2
            and not editing and not any(p.get("fixed_order") for p in body)  # fixed_order: 이미 시간대 틀로 정한 순서
        ):
            # M1: 식당이 2곳 이상이면 떨어져 있어도 틀을 쓴다 (둘째 식당이 저녁 자리로). 직선 동선이 크게 늘면 쓰지 않는다
            templ = _day_sequence(body) + stays
            before, after = _path_m(ordered, prev_stay), _path_m(templ, prev_stay)
            if after > before * MEAL_ORDER_MAX_GROWTH and after - before > MEAL_ORDER_MAX_ADDED_M.get(transport, WALK_OUTLIER_M):
                notes.append(f"Day {day} 식사 순서 틀 미적용(직선 동선 {before}m → {after}m)")
            else:
                ordered = templ
        starts = req.get("day_starts") or {}
        start_hhmm = starts.get(day) or starts.get(str(day)) or req.get("start_time", "11:00")
        end_hhmm = req.get("end_time", "23:59")
        if not editing and _hhmm_to_min(start_hhmm) <= _hhmm_to_min(LUNCH_RULE_START_MAX):
            ordered = _lunch_not_too_early(ordered, _hhmm_to_min(start_hhmm), transport)  # M3
        prev_stay = next((p for p in ordered if p.get("category") == "숙소"), prev_stay)
        offset = len(places)
        route_cache: dict[tuple[int, int], dict[str, Any]] = {}

        def fetch_legs(
            seq: list[dict[str, Any]], route_cache: dict[tuple[int, int], dict[str, Any]] = route_cache
        ) -> list[dict[str, Any]]:
            todo = [(a, b) for a, b in itertools.pairwise(seq) if (id(a), id(b)) not in route_cache]
            with ThreadPoolExecutor(max_workers=6) as ex:
                got = list(ex.map(lambda ab: get_route.route(ab[0]["lat"], ab[0]["lng"], ab[1]["lat"], ab[1]["lng"], transport), todo))
            for (a, b), leg in zip(todo, got):
                route_cache[(id(a), id(b))] = leg
            return [route_cache[(id(a), id(b))] for a, b in itertools.pairwise(seq)]

        start_min, limit = _hhmm_to_min(start_hhmm), _hhmm_to_min(end_hhmm)
        stay_of: dict[int, int] = {}  # M2: 늘린 체류 (id(장소) → 분)
        not_before: dict[int, int] = {}  # M2·M4: 이 시각 전에는 도착하지 않는다 (남는 시간은 자유 시간)

        def timeline(
            seq: list[dict[str, Any]], seq_legs: list[dict[str, Any]], start_min: int = start_min,
            stay_of: dict[int, int] = stay_of, not_before: dict[int, int] = not_before,
        ) -> tuple[list[int], int]:
            return _timeline(seq, seq_legs, start_min, stay_of, not_before)

        dinner_rule = start_min <= _hhmm_to_min(DINNER_RULE_START_MAX) and limit >= _hhmm_to_min(DINNER_RULE_END_MIN)
        day_label = f"Day {day} " if len(by_day) > 1 else ""
        added: dict[str, Any] | None = None
        if dinner_rule and not editing:  # M4: 저녁 식당 덧붙이기 (숙소 앞, 구간·시각은 아래 기존 흐름이 계산)
            added, no_cand = _dinner_to_add(ordered, start_min, limit, transport, state, list(state.get("verified", [])) + added_dinners, day)
            if added:
                ordered = [p for p in ordered if p.get("category") != "숙소"] + [added] + [p for p in ordered if p.get("category") == "숙소"]
                not_before[id(added)] = _hhmm_to_min(DINNER_AT)
            elif no_cand:
                warnings.append(f"{day_label}저녁 식당 후보를 찾지 못했어요")
        day_legs = fetch_legs(ordered)
        arrives, body_end = timeline(ordered, day_legs)
        if added is not None:
            i = next(k for k, p in enumerate(ordered) if p is added)
            if body_end > limit:  # 실제 구간으로는 종료 시각을 넘긴다 → 덧붙이지 않는다 (기존 장소는 건드리지 않음)
                ordered = [p for p in ordered if p is not added]
                not_before.pop(id(added))
                day_legs = fetch_legs(ordered)
                arrives, body_end = timeline(ordered, day_legs)
                notes.append(f"Day {day} 저녁 식당 미추가(실제 이동으로 {end_hhmm} 초과)")
            else:
                added_dinners.append(added)
                notes.append(f"Day {day} 저녁 식당 추가({added['name']})")
                prev = ordered[i - 1]
                free = arrives[i] - (arrives[i - 1] + int(prev.get("stay_min", 60)) + day_legs[i - 1]["duration_min"])
                if free >= FREE_TIME_NOTE_MIN:
                    warnings.append(f"{day_label}저녁 식사 전 자유 시간 {free}분이 있어요")
        if dinner_rule:
            free = _push_dinner(ordered, arrives, stay_of, not_before)  # M2
            if free is not None:
                new_arrives, new_end = timeline(ordered, day_legs)
                if new_end > limit:  # 종료 시각을 넘기면 하지 않는다
                    stay_of.clear()
                    not_before.clear()
                else:
                    arrives, body_end = new_arrives, new_end
                    if free >= FREE_TIME_NOTE_MIN:
                        warnings.append(f"{day_label}저녁 식사 전 자유 시간 {free}분이 있어요")
        dropped: list[str] = []
        # 종료 시각을 넘기면 숙소를 뺀 마지막 장소부터 덜어낸다 (최소 2곳은 남긴다)
        while body_end > limit and sum(1 for p in ordered if p.get("category") != "숙소") > 2:
            idx = max(i for i, p in enumerate(ordered) if p.get("category") != "숙소")
            dropped.append(ordered[idx]["name"])
            ordered = ordered[:idx] + ordered[idx + 1:]
            day_legs = fetch_legs(ordered)
            arrives, body_end = timeline(ordered, day_legs)
        if dropped:
            warnings.append(f"Day {day} 일정이 종료 시각({end_hhmm})을 넘어 {', '.join(dropped)}을(를) 뺐어요")
        if body_end > limit:
            warnings.append(f"Day {day} 일정이 종료 시각({end_hhmm})을 넘겨요 ({_min_to_hhmm(body_end)} 끝). 체류 시간을 줄여보세요")
        for i, p in enumerate(ordered):
            stretched = {"stay_min": stay_of[id(p)]} if id(p) in stay_of else {}
            places.append({**p, **stretched, "order": i + 1, "day": day, "arrive": _min_to_hhmm(arrives[i])})
            if i < len(day_legs):
                leg = day_legs[i]
                legs.append({"from_idx": offset + i, "to_idx": offset + i + 1, **{k: leg[k] for k in ("transport", "duration_min", "distance_m", "polyline", "estimated")}})
                if leg["estimated"] and leg["transport"] != "transit":
                    warnings.append(f"Day {day} {i + 1}→{i + 2} 구간은 길찾기 실패로 직선거리 추정")
    total_min = sum(leg["duration_min"] for leg in legs)
    detail = f"{len(places)}곳 {len(legs)}구간, 이동 총 {total_min}분" + (f" / {'; '.join(notes)}" if notes else "")
    return {
        "places": places,
        "legs": legs,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "optimize_route", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def _nearest_parking(p: dict[str, Any]) -> str:
    """장소에서 400m 안의 가장 가까운 주차장 (카카오 지도). 없거나 실패하면 빈 문자열."""
    try:
        hits = [h for h in search_place.search("주차장", p["lat"], p["lng"], 400, size=5) if h.get("category_group") == "PK6" and h.get("distance_m") is not None]
    except Exception as e:  # noqa: BLE001
        log.debug("주차장 검색 실패: %s", e)
        return ""
    if not hits:
        return ""
    h = min(hits, key=lambda x: x["distance_m"])
    return f"{h['name']} (약 {max(10, round(h['distance_m'], -1))}m)"


def _rag_review(name: str, region: str) -> str:
    """수집한 블로그 글 중 제목이 그 장소를 언급하는 글의 한 줄 요약. 없으면 빈 문자열."""
    head = search_place._norm_name(name.split()[0]) if name.split() else ""
    if len(head) < 3 or head.endswith(("맛집", "카페", "식당")):  # '송도맛집' 같은 일반 명사형 상호는 아무 글에나 걸린다
        return ""
    try:
        for d in rag.search(f"{region} {name}", region=region, k=4, doc_type="blog"):
            if d.get("one_line") and summarize_reviews.mentions(name, d.get("title") or ""):
                return str(d["one_line"])
    except Exception as e:  # noqa: BLE001
        log.debug("rag 리뷰 실패: %s", e)
    return ""


def enrich(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    req = state["request"]
    places = list(state.get("places", []))
    cond = ", ".join(req.get("moods") or []) + (f", {req['free_text']}" if req.get("free_text") else "")
    if req.get("transport") == "car":
        todo = [i for i, p in enumerate(places) if "parking" not in p and p.get("category") != "숙소"]
        if todo:
            with ThreadPoolExecutor(max_workers=min(6, len(todo))) as ex:
                found_parking = list(ex.map(lambda i: _nearest_parking(places[i]), todo))
            for i, text in zip(todo, found_parking, strict=True):
                places[i] = {**places[i], "parking": text}
    need = [i for i, p in enumerate(places) if not p.get("review_summary")]
    if need:
        summaries = summarize_reviews.summarize_many(
            [
                {"name": places[i]["name"], "region": req["region"],
                 "category": (places[i].get("kakao_category") or "").split(" > ")[-1] or places[i].get("category", "")}
                for i in need
            ],
            cond,
        )
        # 웹 리뷰가 비면 큐레이션 문서(RAG)의 한 줄 요약으로 대신한다 (제목에 그 장소명이 들어간 문서만)
        norm = search_place._norm_name
        one_lines = {
            norm(d.get("title") or ""): d["one_line"]
            for d in state.get("rag_docs", [])
            if d.get("doc_type") == "place" and d.get("one_line")  # 블로그 글의 한 줄은 다른 가게 얘기일 수 있어 쓰지 않는다
        }
        for i, s in zip(need, summaries, strict=True):
            s = "" if (not s or "부족" in s) else s
            if not s:
                s = one_lines.get(norm(places[i]["name"]), "")
            places[i] = {**places[i], "review_summary": s}
        # 그래도 비면 수집해 둔 블로그 글 중 제목이 그 장소를 언급하는 글의 한 줄 요약을 쓴다
        empty = [i for i in need if not places[i]["review_summary"]]
        if empty:
            with ThreadPoolExecutor(max_workers=min(6, len(empty))) as ex:
                found = list(ex.map(lambda i: _rag_review(places[i]["name"], req["region"]), empty))
            for i, s in zip(empty, found, strict=True):
                places[i] = {**places[i], "review_summary": s}
    n_ok = sum(1 for p in places if p.get("review_summary"))
    return {
        "places": places,
        "trace": state["trace"] + [{"node": "enrich", "status": "done", "ms": _now_ms() - t0, "detail": f"리뷰 요약 {n_ok}/{len(places)}"}],
    }


COMPOSE_SYSTEM = """당신은 Odiro. 확정된 코스를 사용자에게 친근하고 간결한 한국어 마크다운으로 안내합니다.

형식 (반드시 지킬 것)
- 첫 줄은 정확히 `**Odiro:**` 로 시작하고 코스를 한두 문장으로 소개.
- Day 가 여러 개일 때만 `### Day 1` 식 소제목. 하루 코스면 소제목 없음.
- 장소는 번호 목록. 각 항목: `**장소명** (도착 HH:MM · 체류 N분) — 추천 이유.` 1인 예상 비용이 주어졌으면 괄호 안 끝에 ` · 약 N원`, 근처 주차장이 주어졌으면 항목 끝에 ` 🅿 주차장명 (약 Nm)` 을 붙인다 (따로 줄을 만들지 않는다). 리뷰가 있으면 뒤에 ` 💬 리뷰 한 줄` (리뷰가 '-' 이거나 없으면 💬 부분 생략).
  다음 장소까지 이동은 들여쓴 줄 `↳ 🚶 도보 12분 (900m)` / `🚌 대중교통 약 25분` / `🚗 자차 19분 (10.9km)`.
- 마지막에 `**팁**` 한두 줄: 날씨·일몰·예산·웨이팅 중 조건과 관련된 것만.
- 예상 비용·근처 주차장은 주어진 값이 있을 때만, 주어진 그대로 쓴다. 합계는 직접 계산하지 말고 "1인 예상 비용 합계" 로 주어진 값을 쓴다. 팁에는 그 합계를 예산과 비교해 한 줄, "휴무일·영업시간은 방문 전 지도에서 확인" 을 한 줄 넣는다.
- 추천 이유는 주어진 "이유" 를 문장만 다듬어 쓴다. 주어지지 않은 전망·분위기·주변 명소 묘사를 덧붙이지 않는다.
- 주어진 정보 밖의 사실(영업시간, 휴무일, 웨이팅 시간, 정확한 가격 등)을 지어내지 않는다. 장소명은 주어진 그대로 쓴다."""


def _fallback_answer(state: dict[str, Any]) -> str:
    req = state["request"]
    lines = [f"**Odiro:** {req['region']} 코스를 준비했어요."]
    cur_day = None
    legs = {leg["from_idx"]: leg for leg in state.get("legs", [])}
    for i, p in enumerate(state.get("places", [])):
        if p["day"] != cur_day:
            cur_day = p["day"]
            if req.get("mode") == "trip":
                lines.append(f"\n### Day {cur_day}")
        line = f"{p['order']}. **{p['name']}** ({p.get('arrive', '')} · {p.get('stay_min', 60)}분) — {p.get('reason', '')}"
        if p.get("review_summary"):
            line += f" 💬 {p['review_summary']}"
        lines.append(line)
        if i in legs:
            leg = legs[i]
            icon = {"walk": "🚶 도보", "transit": "🚌 대중교통", "car": "🚗 자차"}[leg["transport"]]
            lines.append(f"   ↳ {icon} {'약 ' if leg['estimated'] else ''}{leg['duration_min']}분 ({leg['distance_m'] / 1000:.1f}km)")
    if state.get("warnings"):
        lines.append("\n**참고** " + " / ".join(state["warnings"]))
    return "\n".join(lines)


def compose_answer(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    if not state.get("places"):
        return {
            "final_answer": "**Odiro:** 조건에 맞는 장소를 지도에서 확인하지 못했어요. 지역을 조금 넓히거나 분위기 태그를 줄여서 다시 시도해 주세요.",
            "trace": state["trace"] + [{"node": "compose_answer", "status": "skip", "ms": 0, "detail": "장소 없음"}],
        }
    req = state["request"]
    legs = {leg["from_idx"]: leg for leg in state.get("legs", [])}
    rows = []
    for i, p in enumerate(state["places"]):
        row = f"Day{p['day']} #{p['order']} {p['name']} | {p.get('category')} | 도착 {p.get('arrive')} 체류 {p.get('stay_min')}분 | 이유: {p.get('reason')} | 리뷰: {p.get('review_summary') or '-'} | 태그: {', '.join(p.get('tags') or [])}"
        if p.get("est_cost"):
            row += f" | 1인 예상 비용: 약 {int(p['est_cost']):,}원"
        if p.get("parking"):
            row += f" | 근처 주차장: {p['parking']}"
        if i in legs:
            leg = legs[i]
            row += f" | 다음까지: {leg['transport']} {leg['duration_min']}분 {leg['distance_m']}m{' (추정)' if leg['estimated'] else ''}"
        rows.append(row)
    wx, sun = state.get("weather") or {}, state.get("sun_times") or {}
    ctx = (
        f"## 조건\n{state['conditions']}\n\n## 코스 제목\n{state.get('title', '')}\n\n## 확정 코스\n" + "\n".join(rows)
        + f"\n\n## 날씨\n{wx if wx.get('available') else '예보 없음'}\n## 일출/일몰\n{sun.get('sunrise')} / {sun.get('sunset')}"
        + f"\n## 1인 예상 비용 합계 (추정, 숙박비 제외)\n약 {sum(int(p.get('est_cost') or 0) for p in state['places'] if p.get('category') != '숙소'):,}원 / 예산 {int(req.get('budget') or 0):,}원"
        + ("\n## 참고사항\n" + "\n".join(state["warnings"]) if state.get("warnings") else "")
    )
    try:
        out = chat(0.5).invoke([("system", COMPOSE_SYSTEM), ("human", ctx)])
        text = str(out.content).strip()
        if not text.startswith("**Odiro:**"):
            text = "**Odiro:** " + text
        if req.get("mode") != "trip":  # 나들이는 Day 소제목 불필요
            text = "\n".join(ln for ln in text.splitlines() if not ln.strip().lower().startswith("### day"))
    except Exception as e:  # noqa: BLE001
        log.warning("compose 실패 → 템플릿: %s", e)
        text = _fallback_answer(state)
    return {
        "final_answer": text,
        "trace": state["trace"] + [{"node": "compose_answer", "status": "done", "ms": _now_ms() - t0, "detail": f"{len(text)}자"}],
    }


# ---------- 수정 플라이휠 ----------

MODIFY_SYSTEM = DRAFT_SYSTEM + """

지금은 **기존 코스의 한 장소만 교체**하는 단계입니다. 사용자의 수정 요청을 읽고 어느 장소(인덱스)를 무엇으로 바꿀지 정하세요.
- target_number 는 '현재 코스' 목록에 적힌 번호 그대로입니다 (1부터). "N번째" 는 N번, "마지막" 은 맨 끝 번호.
- 비 예보가 있으면 교체 장소는 실내로 고릅니다.
- alternates 에는 place 가 지도에 없을 때를 대비해 같은 요청을 만족하는 다른 실존 장소 2~3개를 넣습니다.
- keywords 에는 새 장소의 업종을 지도 앱 검색어로 2~3개 넣습니다 (예: 실내 놀이공간 → "키즈카페", "실내놀이터"). 이름을 못 찾으면 이 검색어로 근처 실존 장소를 찾습니다.
- 프랜차이즈(메가커피·스타벅스 등)는 사용자가 요청하지 않는 한 고르지 않습니다. reason 은 근거 없이 전망·분위기를 지어내지 않습니다.
- "다른 곳으로 바꿔줘" 처럼 조건이 없으면 같은 역할(카테고리)의 다른 장소로 바꿉니다.
- 교체 장소는 같은 지역·같은 역할에서 요청한 성격(더 조용한, 실내, 저렴한 등)을 만족하는 **실존 장소**. 기존 코스의 다른 장소와 가까울수록 좋습니다.
- name 은 지도에 등록된 상호 그대로만 ("성수동 애견동반카페 따우전드" ✗ → "따우전드 성수" ✓). 수식어·지역명을 붙이지 않습니다.
- 코스 전체를 다시 짜달라는 요청이면 target_number=0, place=null.
- "첫째날 9시에 시작", "둘째날은 10시부터" 처럼 **시작 시각만** 바꾸는 요청이면 schedule_only=true, time_changes 에 날짜별 시각(HH:MM), target_number=0, place=null. 장소는 바꾸지 않는다."""


_CLOCK_RE = re.compile(r"\d{1,2}\s*시|\d{1,2}\s*:\s*\d{2}|(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|열한|열두)\s*시|정오|자정")


def _mentions_clock_time(text: str) -> bool:
    """수정 요청에 '9시', '09:30', '열 시' 같은 시각 표현이 있는지."""
    return bool(_CLOCK_RE.search(text or ""))


def modify(state: dict[str, Any]) -> dict[str, Any]:
    """edit 흐름의 첫 노드. state 에 places/legs(기존 코스), instruction, target_index 가 들어온다."""
    t0 = _now_ms()
    places = list(state.get("places", []))
    instruction = state.get("instruction", "")
    target = state.get("target_index")
    if target is None:
        target = _parse_target(instruction, places)  # "3번째", "마지막" 은 LLM 에 맡기지 않고 확정
    wx = state.get("weather") or {}
    listing = "\n".join(f"- {i + 1}번: Day{p['day']} {p['name']} ({p.get('category')}) — {p.get('reason', '')}" for i, p in enumerate(places))
    # 수정 요청의 분위기("조용한 카페로")를 태그로 바꿔, 처음 코스를 짤 때와 같은 태그 필터로 참고 문서를 새로 찾는다
    ref_docs = list(state.get("rag_docs", []))
    req0 = state.get("request") or {}
    edit_moods = [] if _mentions_clock_time(instruction) else _extract_moods(instruction)
    if edit_moods and req0.get("region"):
        try:
            seen = {d["doc_id"] for d in ref_docs}
            q = f"{req0['region']} {instruction} {' '.join(edit_moods)}"
            found = rag.search(q, moods=edit_moods, region=req0["region"], k=5, doc_type="blog") + rag.search(
                q, moods=edit_moods, region=req0["region"], k=3, doc_type="place"
            )
            ref_docs = [d for d in found if d["doc_id"] not in seen] + ref_docs
        except Exception as e:  # noqa: BLE001
            log.warning("수정용 rag 실패: %s", e)
    prompt = (
        f"## 조건\n{state['conditions']}"
        + (f"\n날씨: 비 예보 (강수확률 {int((wx.get('pop') or 0) * 100)}%)" if wx.get("rain") else "")
        + f"\n\n## 현재 코스\n{listing}\n\n## 수정 요청\n{instruction}"
        + (f"\n(바꿀 대상은 {target + 1}번으로 확정)" if target is not None else "")
        + (f"\n(요청의 분위기 태그: {', '.join(edit_moods)} — 아래 참고 문서 중 이 태그가 붙은 곳을 우선해서 고르세요)" if edit_moods else "")
        + f"\n\n## 참고 문서\n{_fmt_rag_docs(ref_docs, 8)}"
    )
    try:
        plan: EditPlan = chat(0.5).with_structured_output(EditPlan).invoke([("system", MODIFY_SYSTEM), ("human", prompt)])
    except Exception as e:  # noqa: BLE001
        return {
            "candidates": places,
            "spares": [],
            "edit_note": f"수정 요청을 이해하지 못했어요 ({str(e)[:40]})",
            "trace": state.get("trace", []) + [{"node": "modify", "status": "error", "ms": _now_ms() - t0, "detail": str(e)[:80]}],
        }
    # 시작 시각 변경: 요청(request)에 날짜별 시작 시각을 남겨, 이후 수정·다시 만들기에서도 유지되게 한다
    new_req = state["request"]
    changed = []
    # LLM 이 장소 교체 요청에도 time_changes 를 임의로(예: Day 1 09:00) 채우는 일이 있어, 요청 문장에 시각 표현이 있을 때만 쓴다
    for tc in plan.time_changes if _mentions_clock_time(instruction) else []:
        if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", tc.start_time) and 1 <= tc.day <= _trip_days(state["request"]):
            changed.append(tc)
    if changed:
        new_req = {**new_req, "day_starts": {**(new_req.get("day_starts") or {}), **{tc.day: tc.start_time for tc in changed}}}
    req_update: dict[str, Any] = {"request": new_req} if changed else {}
    if plan.schedule_only:
        note = ", ".join(f"Day {tc.day} 시작을 {tc.start_time}으로" for tc in changed)
        return {
            **req_update,
            "verified": places,
            "time_only": True,
            "edit_note": f"{note} 바꿨어요" if changed else "시작 시각을 알아듣지 못했어요. 예) 첫째날 9시에 시작",
            "trace": state.get("trace", []) + [{"node": "modify", "status": "done", "ms": _now_ms() - t0, "detail": note or "시각 변경 없음"}],
        }
    idx = target if target is not None else plan.target_number - 1
    if plan.place is None or idx < 0 or idx >= len(places):
        return {
            **req_update,
            "candidates": [],
            "spares": [],
            "rejected": [p["name"] for p in places],
            "edit_note": plan.note or "코스를 새로 구성합니다",
            "full_redraft": True,
            "trace": state.get("trace", []) + [{"node": "modify", "status": "done", "ms": _now_ms() - t0, "detail": "전체 재구성"}],
        }
    old = places[idx]
    new = {**plan.place.model_dump(), "day": old["day"], "order": old["order"], "verified": False}
    cands = [{**p} for p in places]
    cands[idx] = new
    spares = [{**a.model_dump(), "day": old["day"], "order": 0, "verified": False} for a in plan.alternates[:3]]
    # LLM 이 고른 이름이 전부 지도에 없을 때를 대비해, 같은 업종의 실존 장소를 원래 자리 근처에서 찾아 마지막 예비로 둔다
    n_nearby = 0
    keywords = [k.strip() for k in plan.keywords if k.strip()][:3]
    rest = [p for i, p in enumerate(places) if i != idx and p["day"] == old["day"] and p.get("lat")] or [old]
    near = {"lat": sum(p["lat"] for p in rest) / len(rest), "lng": sum(p["lng"] for p in rest) / len(rest)}
    if keywords and near["lat"]:
        try:
            radius = WALK_OUTLIER_M if state["request"].get("transport") == "walk" else 8000
            taken = {p.get("kakao_place_id") for p in places}
            found: list[tuple[str, dict[str, Any]]] = []
            for kw in keywords:
                for h in search_place.search(kw, near["lat"], near["lng"], radius, size=10):
                    if h.get("kakao_place_id") not in taken:
                        taken.add(h.get("kakao_place_id"))
                        found.append((kw, h))
                if len(found) >= 3:
                    break
            for kw, h in found[:3]:
                spares.append({
                    **plan.place.model_dump(), "name": h["name"], "reason": f"요청하신 조건({kw})으로 근처에서 찾은 곳",
                    "source": "rag", "day": old["day"], "order": 0, "verified": True, "lat": h["lat"], "lng": h["lng"],
                    "address": h.get("address", ""), "kakao_place_id": h.get("kakao_place_id", ""), "place_url": h.get("place_url", ""),
                    "phone": h.get("phone", ""), "kakao_category": h.get("category_full", ""),
                })
                n_nearby += 1
        except Exception as e:  # noqa: BLE001
            log.warning("수정 후보 주변 검색 실패: %s", e)
    # 마지막 안전망: 같은 역할의 실존 장소를 동선 근처에서 찾아 둔다 → "바꿔줘" 가 "그대로 뒀어요" 로 끝나지 않게
    try:
        role = plan.place.category
        taken = {p.get("kakao_place_id") for p in places} | {s.get("kakao_place_id") for s in spares}
        names = {p["name"] for p in places}
        radius = WALK_OUTLIER_M if state["request"].get("transport") == "walk" else 8000
        allow = _chains_allowed(state["request"])
        if role in ("식당", "카페"):
            word = "맛집" if role == "식당" else "카페"
            hits = [
                h for h in search_place.search(f"{state['request']['region']} {word}", near["lat"], near["lng"], radius, size=15)
                # 역할은 카카오 업종으로 (제과·베이커리·디저트 음식점은 카페로 본다)
                if _kakao_food_role(h) == role and h.get("kakao_place_id") not in taken and (allow or not _is_chain(h["name"]))
            ]
        else:
            docs = _find_attractions(state["request"], (near["lat"], near["lng"]), bool(wx.get("rain")))
            hits = [
                {"name": d["title"], "lat": d["lat"], "lng": d["lng"], "address": d.get("addr", ""), "kakao_place_id": d.get("kakao_place_id", ""),
                 "place_url": d.get("place_url", ""), "category_full": d.get("one_line", "")}
                for d in docs if d.get("kakao_place_id") not in taken and d["title"] not in names
            ]
        hits.sort(key=lambda h: haversine_m(near["lat"], near["lng"], h["lat"], h["lng"]))
        for h in hits[:3]:
            spares.append({
                **plan.place.model_dump(), "name": h["name"], "reason": f"{state['request']['region']} 동선에서 가까운 {role}", "tags": [],
                "source": "rag", "day": old["day"], "order": 0, "verified": True, "lat": h["lat"], "lng": h["lng"],
                "address": h.get("address", ""), "kakao_place_id": h.get("kakao_place_id", ""), "place_url": h.get("place_url", ""),
                "phone": h.get("phone", ""), "kakao_category": h.get("category_full", ""),
            })
            n_nearby += 1
    except Exception as e:  # noqa: BLE001
        log.warning("수정 대체 후보 검색 실패: %s", e)
    return {
        **req_update,
        "candidates": cands,
        "spares": spares,
        "rejected": list(state.get("rejected", [])) + [old["name"]],
        "edit_slot": {"index": idx, "old": old, "planned": new["name"]},
        "edit_note": f"{old['name']} → {new['name']}",  # verify_places 가 실제로 들어간 장소 기준으로 다시 쓴다
        "trace": state.get("trace", [])
        + [{"node": "modify", "status": "done", "ms": _now_ms() - t0, "detail": f"{idx + 1}번 {old['name']} 교체 후보: {new['name']} (+대안 {len(spares) - n_nearby}, 주변 검색 {n_nearby})"}],
    }
