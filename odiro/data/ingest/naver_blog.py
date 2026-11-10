"""네이버 블로그 검색으로 "시군구 × 분위기 테마" 큐레이션 글 수집.

- API: 네이버 클라우드 플랫폼 **NAVER API HUB** (2026-07-31 이관. 구 developers.naver.com 엔드포인트 아님)
  `GET https://naverapihub.apigw.ntruss.com/search/v1/blog`
  헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY`. 일 25,000회.
- 쿼리: 시군구 이름(TourAPI `ldongCode2` 캐시) × THEMES(10개) → 수도권 66 시군구 ≈ 660 쿼리.
  쿼리당 상위 N건(기본 30) 만 받는다. 같은 글이 여러 테마에서 잡히면 `themes` 에 누적 (약한 라벨로 활용).
- 광고 1차 필터: 제목·요약에 협찬/체험단 류 표현이 있으면 `ad_suspect=True` 로 **표시만** 한다.
  최종 제외는 labeling.py 의 LLM 판정(`광고성(제외용)` 태그)이 한다.
- 검색 API 는 본문 전체가 아니라 요약(description, ~150자)만 준다. 블로그 본문 크롤링은 하지 않는다
  (약관·차단 리스크, DATA_AND_API.md 2-3). 제목+요약+테마 조합으로 RAG 문서를 만든다.

실행 예:
    python -m odiro.data.ingest.naver_blog                 # 수도권 전부
    python -m odiro.data.ingest.naver_blog --area 11       # 서울만
    python -m odiro.data.ingest.naver_blog --area 11 --limit-queries 5   # 연결 확인용
    python -m odiro.data.ingest.naver_blog --all           # 2주차: 나머지 시도
→ data/raw/blog/area_{시도코드}.jsonl (재실행 시 이미 받은 link 는 건너뜀, 쿼리 진행상태도 저장)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import httpx

from odiro.config import settings
from odiro.data.ingest import regions
from odiro.data.ingest.common import (
    BLOG_DIR,
    STATE_DIR,
    DailyQuota,
    QuotaExceeded,
    RetryableHTTPError,
    ensure_dirs,
    get_json,
    load_ids,
    log,
    polite_sleep,
    setup_logging,
    write_jsonl,
)
from odiro.data.ingest.tour_api import TourClient, clean_text

BLOG_URL = "https://naverapihub.apigw.ntruss.com/search/v1/blog"
DAILY_LIMIT = 25_000
SLEEP_BETWEEN_CALLS = 0.1

OUT_PATH = BLOG_DIR / "area_{code}.jsonl"
PROGRESS_PATH = STATE_DIR / "blog_progress_{code}.json"

# 테마 → 검색어 꼬리. 키는 라벨링 태그 체계(regions.MOOD_TAGS)와 맞춘다.
THEMES: dict[str, str] = {
    "데이트": "데이트 코스",
    "감성/조용한": "조용한 감성 카페",
    "힙한/트렌디": "핫플 요즘 뜨는",
    "뷰맛집/일몰": "일몰 뷰 맛집",
    "레트로": "레트로 감성 골목",
    "자연/산책": "산책 코스",
    "실내(비오는날)": "비오는날 실내 가볼만한곳",
    "사진맛집": "사진 찍기 좋은 곳",
    "웨이팅적은": "웨이팅 없는 맛집",
    "아이동반": "아이와 가볼만한 곳",
    "반려동물": "애견동반 카페",
}

# 광고·협찬 의심 표현 (1차 플래그용. 과하게 넓히지 않는다)
AD_PATTERNS = re.compile(
    r"협찬|원고료|체험단|소정의\s*(원고료|수수료)|제공\s*받(아|고)|지원\s*받(아|고)|서포터즈|광고\s*(입니다|포함)|"
    r"유료\s*광고|무료로\s*제공|업체로부터|#광고|\[광고\]|AD\b",
    re.IGNORECASE,
)


# 다른 시도를 가리키는 지역어. 검색 결과에 타지역 글(예: "연수구" 쿼리에 대전·부산 글)이 섞이는 것을 걸러낸다.
# 수도권(서울·인천·경기)끼리는 "서울 근교 양평" 처럼 교차 언급이 자연스러워 서로 타지역으로 치지 않는다.
OTHER_REGION_WORDS: dict[str, tuple[str, ...]] = {
    "26": ("부산", "해운대", "광안리"), "27": ("대구",), "30": ("대전",), "31": ("울산",), "36110": ("세종",),
    "51": ("강원", "강릉", "속초", "춘천", "양양", "평창"), "43": ("충북", "청주", "충주", "단양"),
    "44": ("충남", "천안", "공주", "태안", "보령"), "52": ("전북", "전주", "군산"), "12": ("전남", "광주", "여수", "순천", "목포"),
    "47": ("경북", "경주", "포항", "안동"), "48": ("경남", "창원", "통영", "거제", "김해"), "50": ("제주", "서귀포"),
}
CAPITAL_WORDS = ("서울", "인천", "경기")


def is_off_region(title: str, description: str, sido_code: str) -> bool:
    """글이 다른 시도 이야기로 보이면 True. 자기 시도(수도권) 지명이 함께 있으면 False."""
    text = f"{title} {description}"
    if any(w in text for w in CAPITAL_WORDS):
        return False
    return any(w in text for code, words in OTHER_REGION_WORDS.items() if code != sido_code for w in words)


# ---------- 순수 함수 (테스트 가능) ----------


def query_region_name(sigungu: str) -> str:
    """검색어용 지역명. '수원시'→'수원', '가평군'→'가평', '성동구'는 그대로 (중구·동구처럼 짧은 구는 '구'를 떼면 안 됨)."""
    s = sigungu.strip()
    if len(s) >= 3 and s[-1] in "시군":
        return s[:-1]
    return s


def build_queries(sido_code: str, sigungus: list[dict[str, str]]) -> list[dict[str, str]]:
    """시도 하나의 (시군구 × 테마) 쿼리 목록. 서울 구는 '서울' 을 앞에 붙여 타지역 동명 구(부산 중구 등)와 구분."""
    prefix = "서울 " if sido_code == "11" else ""
    out = []
    for sg in sigungus:
        region = query_region_name(sg["name"])
        for theme, tail in THEMES.items():
            out.append(
                {
                    "query": f"{prefix}{region} {tail}",
                    "theme": theme,
                    "sigungu_code": sg["code"],
                    "sigungu": sg["name"],
                }
            )
    return out


def is_ad_suspect(title: str, description: str) -> bool:
    return bool(AD_PATTERNS.search(f"{title} {description}"))


def normalize_post(item: dict[str, Any], q: dict[str, str], sido_code: str) -> dict[str, Any]:
    title = clean_text(item.get("title"))
    desc = clean_text(item.get("description"))
    return {
        "link": item.get("link", ""),
        "title": title,
        "description": desc,
        "blogger": item.get("bloggername", ""),
        "postdate": item.get("postdate", ""),  # YYYYMMDD
        "sido_code": sido_code,
        "sigungu_code": q["sigungu_code"],
        "sigungu": q["sigungu"],
        "themes": [q["theme"]],
        "queries": [q["query"]],
        "ad_suspect": is_ad_suspect(title, desc),
        "off_region": is_off_region(title, desc, sido_code),
        "source": "naver_blog",
    }


def merge_post(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """같은 글이 다른 테마 쿼리에서도 잡히면 테마·쿼리만 누적."""
    for key in ("themes", "queries"):
        for v in new[key]:
            if v not in existing[key]:
                existing[key].append(v)
    return existing


# ---------- 호출 ----------


class NaverBlogClient:
    def __init__(self, daily_limit: int = DAILY_LIMIT) -> None:
        if not (settings.naver_client_id and settings.naver_client_secret):
            raise SystemExit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 .env 에 없습니다 (NCP NAVER API HUB 에서 발급)")
        self.http = httpx.Client(timeout=15)
        self.headers = {
            "X-NCP-APIGW-API-KEY-ID": settings.naver_client_id,
            "X-NCP-APIGW-API-KEY": settings.naver_client_secret,
        }
        self.quota = DailyQuota("naver:blog", daily_limit)

    def search(self, query: str, display: int = 30, start: int = 1, sort: str = "sim") -> list[dict[str, Any]]:
        if self.quota.exhausted():
            raise QuotaExceeded(f"naver:blog 오늘 한도({self.quota.limit}) 소진")
        try:
            data = get_json(
                self.http,
                BLOG_URL,
                params={"query": query, "display": min(display, 100), "start": start, "sort": sort},
                headers=self.headers,
            )
        except QuotaExceeded:
            self.quota.mark_exhausted()
            raise
        self.quota.tick()
        polite_sleep(SLEEP_BETWEEN_CALLS)
        return data.get("items", [])


# ---------- 파이프라인 ----------


def _load_progress(code: str) -> set[str]:
    p = Path(str(PROGRESS_PATH).format(code=code))
    return set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()


def _save_progress(code: str, done: set[str]) -> None:
    p = Path(str(PROGRESS_PATH).format(code=code))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")


def collect_blogs(
    client: NaverBlogClient,
    sigungus: list[dict[str, str]],
    sido_code: str,
    per_query: int,
    limit_queries: int | None = None,
    start: int = 1,
) -> int:
    """start>1 이면 같은 쿼리의 뒷순위 글을 추가 수집 (예: --start 31 --per-query 70 → 31~100번째)."""
    out_path = Path(str(OUT_PATH).format(code=sido_code))
    queries = build_queries(sido_code, sigungus)
    if limit_queries:
        queries = queries[:limit_queries]
    done_q = _load_progress(sido_code)
    seen_links = load_ids(out_path, "link")
    key = (lambda q: q["query"]) if start == 1 else (lambda q: f"{q['query']}@{start}")
    todo = [q for q in queries if key(q) not in done_q]
    log.info(
        "%s 블로그: 쿼리 %d개 (완료 %d, 남음 %d), 기존 글 %d건",
        regions.sido_name(sido_code), len(queries), len(done_q), len(todo), len(seen_links),
    )

    new_posts: dict[str, dict[str, Any]] = {}
    n_calls = 0
    try:
        for q in todo:
            items = client.search(q["query"], display=per_query, start=start)
            n_calls += 1
            for it in items:
                post = normalize_post(it, q, sido_code)
                link = post["link"]
                if not link or link in seen_links:
                    continue
                if link in new_posts:
                    merge_post(new_posts[link], post)
                else:
                    new_posts[link] = post
            done_q.add(key(q))
            if n_calls % 20 == 0:
                write_jsonl(out_path, new_posts.values(), append=True)
                seen_links.update(new_posts)
                new_posts.clear()
                _save_progress(sido_code, done_q)
                log.info("  …쿼리 %d/%d, 글 %d건", n_calls, len(todo), len(seen_links))
    except (RetryableHTTPError, QuotaExceeded) as e:
        log.warning("중단: %s", e)
    finally:
        if new_posts:
            write_jsonl(out_path, new_posts.values(), append=True)
            seen_links.update(new_posts)
        _save_progress(sido_code, done_q)

    log.info("블로그 저장 %s (누적 %d건, 호출 %d회)", out_path, len(seen_links), n_calls)
    return n_calls


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", nargs="*", help="법정동 시도코드 (기본: 수도권 11 28 41)")
    ap.add_argument("--all", action="store_true", help="수도권 제외 나머지 시도 (2주차)")
    ap.add_argument("--per-query", type=int, default=30, help="쿼리당 가져올 글 수 (최대 100)")
    ap.add_argument("--limit-queries", type=int, default=None, help="시도별 쿼리 상한 (연결 확인용)")
    ap.add_argument("--start", type=int, default=1, help="검색 시작 순위 (기본 1). 추가 수집: --start 31 --per-query 70")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()
    areas = regions.parse_area_args(args.area, args.all)
    tour = TourClient()  # 시군구 목록(ldongCode2) 용. 캐시되어 있으면 호출 없음
    client = NaverBlogClient()

    for code in areas:
        sigungus = tour.fetch_sigungu(code)
        collect_blogs(client, sigungus, code, args.per_query, args.limit_queries, start=args.start)
        if client.quota.exhausted():
            log.warning("네이버 오늘 한도 소진. 내일 같은 명령으로 이어서")
            break
    log.info("오늘 네이버 호출: %d", client.quota.used)


if __name__ == "__main__":
    main()
