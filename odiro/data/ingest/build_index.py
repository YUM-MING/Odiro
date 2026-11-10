"""라벨링된 문서를 Chroma 에 적재 (OpenAI 임베딩).

- 컬렉션 `odiro_docs`, 경로 `settings.vectorstore_dir` (= data/vectorstore, git 제외)
- 문서 텍스트 = "제목\\n본문". 장소 overview 는 500자 청크로 나누고, 블로그 글(짧음)은 1청크.
- 메타데이터(Chroma 는 스칼라만 허용):
    doc_id, doc_type, title, url, sido_code, sigungu_code, sigungu, is_ad, one_line, tags("|" 로 join),
    각 태그별 bool 플래그 `t_<slug>` (필터용, 아래 TAG_KEYS), place 는 content_id/content_type/lat/lng/addr/image
- 광고(is_ad) 문서는 기본 제외 (`--keep-ads` 로 포함).
- 재실행 시 이미 들어간 chunk id 는 건너뛴다.

실행 예:
    python -m odiro.data.ingest.build_index --area 11
    python -m odiro.data.ingest.build_index              # 수도권
    python -m odiro.data.ingest.build_index --stats      # 적재 현황만
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from odiro.config import settings
from odiro.data.ingest import regions
from odiro.data.ingest.common import LABELED_DIR, log, read_jsonl, setup_logging

COLLECTION = "odiro_docs"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 60
EMBED_BATCH = 200

# 태그 → 메타데이터 키 (한글·특수문자 키 대신 ascii)
TAG_KEYS: dict[str, str] = {
    "감성/조용한": "t_calm",
    "힙한/트렌디": "t_hip",
    "뷰맛집/일몰": "t_view",
    "레트로": "t_retro",
    "자연/산책": "t_nature",
    "실내(비오는날)": "t_indoor",
    "액티비티": "t_activity",
    "사진맛집": "t_photo",
    "웨이팅적은": "t_nowait",
    "아이동반": "t_kids",
    "반려동물": "t_pet",
}


def get_embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)


def get_vectorstore(persist_dir: Path | None = None):
    """langchain_chroma.Chroma 인스턴스 (rag_search 도 이걸 쓴다)."""
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_dir or settings.vectorstore_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )


# ---------- 문서 → 청크 ----------


def doc_metadata(d: dict[str, Any]) -> dict[str, Any]:
    md: dict[str, Any] = {
        "doc_id": d["doc_id"],
        "doc_type": d["doc_type"],
        "title": d["title"],
        "url": d.get("url") or "",
        "sido_code": d.get("sido_code") or "",
        "sigungu_code": d.get("sigungu_code") or "",
        "sigungu": d.get("sigungu") or "",
        "is_ad": bool(d.get("is_ad", False)),
        "one_line": d.get("one_line") or "",
        "tags": "|".join(d.get("tags", [])),
    }
    for tag, key in TAG_KEYS.items():
        md[key] = tag in d.get("tags", [])
    if d["doc_type"] == "place":
        md.update(
            {
                "content_id": d.get("content_id") or "",
                "content_type": d.get("content_type") or "",
                "addr": d.get("addr") or "",
                "image": d.get("image") or "",
                "lat": float(d["lat"]) if d.get("lat") is not None else 0.0,
                "lng": float(d["lng"]) if d.get("lng") is not None else 0.0,
            }
        )
    else:
        md["postdate"] = d.get("postdate") or ""
    return md


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """문장 경계를 우선으로 size 안팎으로 자른다 (외부 라이브러리 없이)."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind(". ", start, end), text.rfind("다. ", start, end), text.rfind("\n", start, end))
            if cut > start + size // 2:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def to_chunks(d: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(chunk_id, text, metadata) 목록."""
    md = doc_metadata(d)
    body = d["text"]
    pieces = split_text(body) if d["doc_type"] == "place" else [body.strip()]
    out = []
    for i, piece in enumerate(pieces):
        text = f"{d['title']}\n{piece}"
        if d.get("one_line"):
            text += f"\n({d['one_line']})"
        out.append((f"{d['doc_id']}#{i}", text, {**md, "chunk": i}))
    return out


# ---------- 적재 ----------


def index_area(vs, sido_code: str, keep_ads: bool) -> int:
    path = LABELED_DIR / f"area_{sido_code}.jsonl"
    if not path.exists():
        log.warning("라벨 파일 없음: %s (labeling.py 먼저)", path)
        return 0
    chunks: list[tuple[str, str, dict[str, Any]]] = []
    skipped_ads = 0
    for d in read_jsonl(path):
        if d.get("is_ad") and not keep_ads:
            skipped_ads += 1
            continue
        chunks.extend(to_chunks(d))
    log.info("%s: 청크 %d개 (광고 제외 %d문서)", regions.sido_name(sido_code), len(chunks), skipped_ads)

    col = vs._collection  # 기존 id 확인용 (langchain_chroma 가 공개 API 로 노출하지 않음)
    added = 0
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        ids = [c[0] for c in batch]
        existing = set(col.get(ids=ids, include=[])["ids"])
        new = [c for c in batch if c[0] not in existing]
        if not new:
            continue
        vs.add_texts(texts=[c[1] for c in new], metadatas=[c[2] for c in new], ids=[c[0] for c in new])
        added += len(new)
        log.info("  …%d/%d (신규 %d)", min(i + EMBED_BATCH, len(chunks)), len(chunks), added)
    log.info("%s 적재 완료: 신규 %d청크, 컬렉션 총 %d", regions.sido_name(sido_code), added, col.count())
    return added


def stats(vs) -> None:
    col = vs._collection
    total = col.count()
    print(f"컬렉션 {COLLECTION}: {total} 청크 @ {settings.vectorstore_dir}")
    if total == 0:
        return
    def count(where: dict[str, Any]) -> int:
        return len(col.get(where=where, include=[])["ids"])

    print("  doc_type:", {t: count({"doc_type": t}) for t in ("place", "blog")})
    print("  sido:", {regions.sido_name(c): count({"sido_code": c}) for c in regions.SIDO if count({"sido_code": c})})
    print("  tags:", {t: count({k: True}) for t, k in TAG_KEYS.items()})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", nargs="*", help="법정동 시도코드 (기본: 수도권)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--keep-ads", action="store_true", help="광고 판정 문서도 적재")
    ap.add_argument("--stats", action="store_true", help="적재 현황만 출력")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY 가 필요합니다 (임베딩)")
    vs = get_vectorstore()
    if args.stats:
        stats(vs)
        return
    for code in regions.parse_area_args(args.area, args.all):
        index_area(vs, code, args.keep_ads)
    stats(vs)


if __name__ == "__main__":
    main()
