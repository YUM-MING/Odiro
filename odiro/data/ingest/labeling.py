"""LLM 분위기 태그 라벨링 (gpt-4o-mini, Structured Output).

입력
- TourAPI 장소: `area_{code}.jsonl` + `detail_{code}.jsonl` 을 합쳐 overview 가 있는 것만
- 블로그 글: `blog/area_{code}.jsonl` (제목 + 요약)

출력 `data/raw/labeled/area_{code}.jsonl` — RAG 문서 1건 = 1행
    doc_id, doc_type(place|blog), title, text, tags[], is_ad, one_line, url,
    sido_code, sigungu_code, sigungu, (place 만) content_type, lat, lng, content_id

- 한 번에 BATCH 개 문서를 묶어 보내고 Pydantic 스키마로 출력을 강제한다 (파싱 실패 시 tenacity 재시도).
- 재실행하면 이미 라벨링된 doc_id 는 건너뛴다.
- 비용: 문서 ≈ 300 토큰, 10개 묶음 ≈ 3.5k 토큰 → 2만 건 ≈ 7M 토큰 ≈ gpt-4o-mini 기준 1~2달러.

실행 예:
    python -m odiro.data.ingest.labeling --area 11 --limit 30     # 연결·품질 확인
    python -m odiro.data.ingest.labeling                           # 수도권 전부
    python -m odiro.data.ingest.labeling --only blog               # 블로그만
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from odiro.config import settings
from odiro.data.ingest import regions
from odiro.data.ingest.common import (
    BLOG_DIR,
    LABELED_DIR,
    ensure_dirs,
    load_ids,
    log,
    read_jsonl,
    setup_logging,
    write_jsonl,
)
from odiro.data.ingest.tour_api import merge_meta_detail

BATCH = 10
WORKERS = 4
MIN_TEXT_LEN = 30  # 이보다 짧은 텍스트는 분위기를 판단할 수 없어 라벨링하지 않는다
OUT_PATH = LABELED_DIR / "area_{code}.jsonl"

MoodTag = Literal[
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
]


class DocLabel(BaseModel):
    idx: int = Field(description="입력 문서 번호 (0부터)")
    tags: list[MoodTag] = Field(default_factory=list, description="해당하는 분위기 태그. 근거 없으면 비움. 최대 4개")
    is_ad: bool = Field(description="협찬·체험단·광고성 글이면 true")
    one_line: str = Field(description="장소/글의 분위기를 한국어 한 문장(40자 이내)으로")


class BatchLabels(BaseModel):
    labels: list[DocLabel]


SYSTEM_PROMPT = """당신은 국내 여행·데이트 코스 큐레이터입니다. 아래 문서들을 읽고 각 문서에 분위기 태그를 붙입니다.

태그 정의:
- 감성/조용한: 차분하고 아늑한, 사람 적은, 혼자·둘이 조용히
- 힙한/트렌디: 요즘 뜨는, 핫플, 감각적인 인테리어, MZ
- 뷰맛집/일몰: 전망·야경·일몰·한강뷰·오션뷰
- 레트로: 옛 감성, 골목, 한옥·근대 건축, 빈티지
- 자연/산책: 공원·숲·강변·둘레길, 걷기 좋은
- 실내(비오는날): 전시·박물관·대형 카페·쇼핑몰 등 날씨 무관
- 액티비티: 체험·스포츠·공방·놀이
- 사진맛집: 포토스팟, 인생샷
- 웨이팅적은: 한산하다, 웨이팅 없다는 언급이 있을 때만
- 아이동반: 유아·어린이와 가기 좋다는 근거가 있을 때만
- 반려동물: 애견동반 가능 언급이 있을 때만

규칙: 텍스트에 근거가 있는 태그만 붙입니다. 추측하지 않습니다. 광고·협찬·체험단·원고료 표현이 있으면 is_ad=true.
모든 문서(idx 0..N-1)에 대해 정확히 하나씩 결과를 냅니다."""


# ---------- 문서 만들기 ----------


def place_docs(sido_code: str) -> Iterator[dict[str, Any]]:
    for p in merge_meta_detail(sido_code):
        text = p.get("overview", "")
        if len(text) < MIN_TEXT_LEN:
            continue
        yield {
            "doc_id": f"place:{p['content_id']}",
            "doc_type": "place",
            "title": p["title"],
            "text": text,
            "url": p.get("homepage", ""),
            "sido_code": p["sido_code"],
            "sigungu_code": p["sigungu_code"],
            "sigungu": "",
            "content_id": p["content_id"],
            "content_type": p["content_type"],
            "addr": p["addr"],
            "lat": p["lat"],
            "lng": p["lng"],
            "image": p["image"],
        }


def blog_docs(sido_code: str) -> Iterator[dict[str, Any]]:
    for b in read_jsonl(BLOG_DIR / f"area_{sido_code}.jsonl"):
        text = b["description"]
        if len(text) < MIN_TEXT_LEN:
            continue
        yield {
            "doc_id": f"blog:{b['link']}",
            "doc_type": "blog",
            "title": b["title"],
            "text": text,
            "url": b["link"],
            "sido_code": b["sido_code"],
            "sigungu_code": b["sigungu_code"],
            "sigungu": b["sigungu"],
            "postdate": b.get("postdate", ""),
            "themes": b.get("themes", []),
            "ad_suspect": b.get("ad_suspect", False),
        }


def format_batch(docs: list[dict[str, Any]]) -> str:
    parts = []
    for i, d in enumerate(docs):
        kind = "장소" if d["doc_type"] == "place" else "블로그"
        hint = f" (검색 테마: {', '.join(d['themes'])})" if d.get("themes") else ""
        parts.append(f"[{i}] ({kind}) {d['title']}{hint}\n{d['text'][:1200]}")
    return "\n\n".join(parts)


def apply_labels(docs: list[dict[str, Any]], result: BatchLabels) -> list[dict[str, Any]]:
    """LLM 결과를 문서에 합친다. 누락된 idx 는 태그 없이 저장 (재실행 시 다시 안 돌도록)."""
    by_idx = {lab.idx: lab for lab in result.labels if 0 <= lab.idx < len(docs)}
    out = []
    for i, d in enumerate(docs):
        lab = by_idx.get(i)
        out.append(
            {
                **d,
                "tags": list(dict.fromkeys(lab.tags))[:4] if lab else [],
                "is_ad": bool(lab.is_ad or d.get("ad_suspect", False)) if lab else d.get("ad_suspect", False),
                "one_line": lab.one_line.strip() if lab else "",
                "labeled": lab is not None,
            }
        )
    return out


# ---------- LLM ----------


def make_labeler():
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(model=settings.llm_model, api_key=settings.anthropic_api_key, temperature=0, timeout=60)
    else:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, temperature=0, timeout=60)
    return llm.with_structured_output(BatchLabels)


@retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(4), reraise=True)
def label_batch(labeler, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: BatchLabels = labeler.invoke(
        [("system", SYSTEM_PROMPT), ("human", f"문서 {len(docs)}개:\n\n{format_batch(docs)}")]
    )
    return apply_labels(docs, result)


# ---------- 파이프라인 ----------


def run_area(sido_code: str, only: str | None, limit: int | None, labeler) -> int:
    out_path = Path(str(OUT_PATH).format(code=sido_code))
    done = load_ids(out_path, "doc_id")
    docs: list[dict[str, Any]] = []
    if only in (None, "place"):
        docs += [d for d in place_docs(sido_code) if d["doc_id"] not in done]
    if only in (None, "blog"):
        docs += [d for d in blog_docs(sido_code) if d["doc_id"] not in done]
    if limit:
        docs = docs[:limit]
    log.info("%s 라벨링: 완료 %d, 이번 %d건 (%d 배치)", regions.sido_name(sido_code), len(done), len(docs), -(-len(docs) // BATCH))
    if not docs:
        return 0

    batches = [docs[i : i + BATCH] for i in range(0, len(docs), BATCH)]
    n = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(label_batch, labeler, b): b for b in batches}
        for k, fut in enumerate(as_completed(futures), 1):
            try:
                rows = fut.result()
            except Exception as e:  # noqa: BLE001 — 한 배치 실패는 건너뛰고 계속 (재실행 때 다시 시도됨)
                log.warning("배치 실패(%d건): %s", len(futures[fut]), str(e)[:200])
                continue
            write_jsonl(out_path, rows, append=True)
            n += len(rows)
            if k % 20 == 0:
                log.info("  …%d/%d 배치", k, len(batches))
    log.info("라벨 저장 %s (+%d건)", out_path, n)
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", nargs="*", help="법정동 시도코드 (기본: 수도권)")
    ap.add_argument("--all", action="store_true", help="수도권 제외 나머지 시도 (2주차)")
    ap.add_argument("--only", choices=["place", "blog"], default=None)
    ap.add_argument("--limit", type=int, default=None, help="시도별 문서 상한 (테스트용)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()
    if not (settings.openai_api_key or settings.anthropic_api_key):
        raise SystemExit("OPENAI_API_KEY (또는 ANTHROPIC_API_KEY) 가 필요합니다")
    labeler = make_labeler()
    for code in regions.parse_area_args(args.area, args.all):
        run_area(code, args.only, args.limit, labeler)


if __name__ == "__main__":
    main()
