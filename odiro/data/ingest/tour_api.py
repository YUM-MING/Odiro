"""TourAPI 4.0 (한국관광공사 KorService2) 장소 수집.

두 단계로 나뉜다.

1. **메타 수집** `areaBasedList2` — 시도(법정동코드) × 콘텐츠타입별로 1,000건씩 페이지네이션.
   수도권 전체(약 1.9만 건)가 30회 미만 호출로 끝난다.  → `data/raw/tour/area_{시도코드}.jsonl`
2. **상세 수집** `detailCommon2` — 장소마다 1회 호출해 `overview`(설명)·`homepage` 를 붙인다.
   개발계정은 기능별 일 1,000건이라 `DETAIL_PRIORITY` 순서로 하루 한도만큼 돌리고, 다음 날 이어서 돌린다.
   → `data/raw/tour/detail_{시도코드}.jsonl` (이미 받은 contentid 는 건너뜀)

실행 예:
    python -m odiro.data.ingest.tour_api                      # 수도권(11·28·41) 메타 + 상세(한도까지)
    python -m odiro.data.ingest.tour_api --area 11            # 서울만
    python -m odiro.data.ingest.tour_api --all                # 2주차: 수도권 제외 나머지 시도
    python -m odiro.data.ingest.tour_api --no-detail          # 메타만
    python -m odiro.data.ingest.tour_api --detail-limit 300   # 오늘 상세는 300건만
    python -m odiro.data.ingest.tour_api --types 12 14 39     # 관광지·문화시설·음식점만

주의: data.go.kr 인증키는 **Decoding 키** 를 쓴다 (Encoding 키를 넣으면 SERVICE_KEY_IS_NOT_REGISTERED).
"""

from __future__ import annotations

import argparse
import html
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from odiro.config import settings
from odiro.data.ingest import regions
from odiro.data.ingest.common import (
    STATE_DIR,
    TOUR_DIR,
    DailyQuota,
    QuotaExceeded,
    RetryableHTTPError,
    ensure_dirs,
    get_json,
    load_ids,
    log,
    polite_sleep,
    read_jsonl,
    setup_logging,
    write_jsonl,
)

BASE_URL = "https://apis.data.go.kr/B551011/KorService2"
PAGE_SIZE = 1000
DEV_DAILY_LIMIT = 1000  # 개발계정 기능별 일일 한도. 운영계정 승인되면 --daily-limit 로 올린다.
SLEEP_BETWEEN_CALLS = 0.2

META_PATH = TOUR_DIR / "area_{code}.jsonl"
DETAIL_PATH = TOUR_DIR / "detail_{code}.jsonl"
SIGUNGU_CACHE = STATE_DIR / "sigungu_{code}.json"


class TourApiError(Exception):
    pass


# ---------- 응답 파싱 (네트워크 없이 테스트 가능) ----------


def parse_body(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """data.go.kr 응답에서 (items, totalCount). 결과 0건이면 items 가 빈 문자열로 온다."""
    if "OpenAPI_ServiceResponse" in payload:  # 인증 오류 등은 이 모양으로 온다
        hdr = payload["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
        msg = hdr.get("returnAuthMsg") or hdr.get("errMsg") or str(hdr)
        if hdr.get("returnReasonCode") in {"22", "23"}:  # 한도 초과
            raise QuotaExceeded(f"TourAPI 한도 초과: {msg}")
        raise TourApiError(f"TourAPI 오류: {msg}")
    resp = payload.get("response", {})
    header = resp.get("header", {})
    if header.get("resultCode") not in (None, "0000"):
        raise TourApiError(f"TourAPI 오류 {header.get('resultCode')}: {header.get('resultMsg')}")
    body = resp.get("body", {})
    items = body.get("items") or {}
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):  # 1건일 때 dict 로 오는 경우 방어
        rows = [rows]
    return rows, int(body.get("totalCount") or 0)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: str | None) -> str:
    """overview/homepage 에 섞인 HTML 태그·개행 정리."""
    if not s:
        return ""
    s = html.unescape(_TAG_RE.sub(" ", s)).replace(" ", " ")
    return _WS_RE.sub(" ", s).strip()


def normalize_place(raw: dict[str, Any]) -> dict[str, Any]:
    """areaBasedList2 한 행 → 우리 스키마. 좌표는 float, 코드는 str 로 통일."""

    def f(key: str) -> float | None:
        v = raw.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    ctype = int(raw.get("contenttypeid") or 0)
    return {
        "content_id": str(raw.get("contentid", "")),
        "title": (raw.get("title") or "").strip(),
        "content_type_id": ctype,
        "content_type": regions.CONTENT_TYPES.get(ctype, str(ctype)),
        "sido_code": str(raw.get("lDongRegnCd") or ""),
        "sigungu_code": str(raw.get("lDongSignguCd") or ""),
        "addr": " ".join(x for x in (raw.get("addr1"), raw.get("addr2")) if x).strip(),
        "zipcode": raw.get("zipcode") or "",
        "tel": raw.get("tel") or "",
        "lng": f("mapx"),
        "lat": f("mapy"),
        "image": raw.get("firstimage") or "",
        "image_thumb": raw.get("firstimage2") or "",
        "cat1": raw.get("cat1") or "",
        "cat2": raw.get("cat2") or "",
        "cat3": raw.get("cat3") or "",
        "lcls1": raw.get("lclsSystm1") or "",
        "lcls2": raw.get("lclsSystm2") or "",
        "lcls3": raw.get("lclsSystm3") or "",
        "modified": raw.get("modifiedtime") or "",
        "source": "tourapi",
    }


def normalize_detail(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_id": str(raw.get("contentid", "")),
        "overview": clean_text(raw.get("overview")),
        "homepage": clean_text(raw.get("homepage")),
        "tel_name": raw.get("telname") or "",
        "source": "tourapi",
    }


# ---------- 호출 ----------


class TourClient:
    def __init__(self, service_key: str | None = None, daily_limit: int = DEV_DAILY_LIMIT) -> None:
        self.key = service_key or settings.tour_api_key
        if not self.key:
            raise SystemExit("TOUR_API_KEY 가 .env 에 없습니다")
        if "%" in self.key:
            raise SystemExit("TOUR_API_KEY 가 Encoding 키로 보입니다. data.go.kr 의 Decoding 키를 넣으세요")
        self.http = httpx.Client(timeout=30)
        self.quota_list = DailyQuota("tour:areaBasedList2", daily_limit)
        self.quota_detail = DailyQuota("tour:detailCommon2", daily_limit)
        self.quota_code = DailyQuota("tour:ldongCode2", daily_limit)

    def _call(self, op: str, quota: DailyQuota, **params: Any) -> tuple[list[dict[str, Any]], int]:
        if quota.exhausted():
            raise QuotaExceeded(f"{quota.name} 오늘 한도({quota.limit}) 소진. 내일 다시 실행")
        base = {
            "serviceKey": self.key,
            "MobileOS": "ETC",
            "MobileApp": "Odiro",
            "_type": "json",
        }
        try:
            payload = get_json(self.http, f"{BASE_URL}/{op}", params={**base, **params})
        except QuotaExceeded:
            quota.mark_exhausted()
            raise
        quota.tick()
        polite_sleep(SLEEP_BETWEEN_CALLS)
        return parse_body(payload)

    # --- 코드표 ---

    def fetch_sigungu(self, sido_code: str) -> list[dict[str, str]]:
        """시도 안의 시군구 (법정동) 목록. 파일 캐시."""
        import json

        cache = Path(str(SIGUNGU_CACHE).format(code=sido_code))
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        rows, _ = self._call("ldongCode2", self.quota_code, lDongRegnCd=sido_code, numOfRows=200)
        out = [{"code": str(r["code"]), "name": r["name"]} for r in rows]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out

    # --- 메타 ---

    def iter_area(self, sido_code: str, content_type: int) -> Iterator[dict[str, Any]]:
        page = 1
        seen = 0
        while True:
            rows, total = self._call(
                "areaBasedList2",
                self.quota_list,
                lDongRegnCd=sido_code,
                contentTypeId=content_type,
                numOfRows=PAGE_SIZE,
                pageNo=page,
                arrange="C",  # 수정일순 → 최근 갱신된 장소가 앞에
            )
            for r in rows:
                yield normalize_place(r)
            seen += len(rows)
            if not rows or seen >= total:
                return
            page += 1

    # --- 상세 ---

    def fetch_detail(self, content_id: str) -> dict[str, Any] | None:
        rows, _ = self._call("detailCommon2", self.quota_detail, contentId=content_id)
        return normalize_detail(rows[0]) if rows else None


# ---------- 파이프라인 ----------


def collect_meta(client: TourClient, sido_code: str, types: list[int]) -> Path:
    """시도 하나의 메타를 전부 받아 area_{code}.jsonl 로 저장 (덮어쓰기, contentid 중복 제거)."""
    path = Path(str(META_PATH).format(code=sido_code))
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for ct in types:
        n_before = len(rows)
        for place in client.iter_area(sido_code, ct):
            if place["content_id"] in seen or not place["title"]:
                continue
            seen.add(place["content_id"])
            rows.append(place)
        log.info("  %s %s: %d건", regions.sido_name(sido_code), regions.CONTENT_TYPES.get(ct, ct), len(rows) - n_before)
    write_jsonl(path, rows)
    log.info("메타 저장 %s (%d건)", path, len(rows))
    return path


def collect_detail(client: TourClient, sido_code: str, limit: int | None, types: list[int]) -> int:
    """상세(overview)를 우선순위 순으로, 오늘 한도(또는 --detail-limit)까지 받아 detail_{code}.jsonl 에 추가."""
    meta_path = Path(str(META_PATH).format(code=sido_code))
    detail_path = Path(str(DETAIL_PATH).format(code=sido_code))
    if not meta_path.exists():
        log.warning("메타 파일이 없어 상세를 건너뜀: %s", meta_path)
        return 0
    done = load_ids(detail_path, "content_id")
    order = {ct: i for i, ct in enumerate(regions.DETAIL_PRIORITY)}
    todo = [
        p
        for p in read_jsonl(meta_path)
        if p["content_id"] not in done and p["content_type_id"] in types
    ]
    # 타입 우선순위 → 같은 타입 안에서는 최근 수정된(=살아 있을 확률 높은) 장소부터
    todo.sort(key=lambda p: p.get("modified", ""), reverse=True)
    todo.sort(key=lambda p: order.get(p["content_type_id"], 99))
    budget = client.quota_detail.remaining if limit is None else min(limit, client.quota_detail.remaining)
    log.info(
        "%s 상세: 완료 %d / 남은 %d / 오늘 예산 %d",
        regions.sido_name(sido_code), len(done), len(todo), budget,
    )
    n = 0
    batch: list[dict[str, Any]] = []
    try:
        for p in todo[:budget]:
            d = client.fetch_detail(p["content_id"])
            if d:
                batch.append(d)
                n += 1
            if len(batch) >= 50:
                write_jsonl(detail_path, batch, append=True)
                batch.clear()
                log.info("  …%d건", n)
    except (RetryableHTTPError, QuotaExceeded) as e:
        log.warning("중단: %s", e)
    finally:
        if batch:
            write_jsonl(detail_path, batch, append=True)
    log.info("상세 저장 %s (+%d건, 누적 %d)", detail_path, n, len(done) + n)
    return n


def merge_meta_detail(sido_code: str) -> Iterator[dict[str, Any]]:
    """다음 단계(라벨링·인덱싱)용: 메타 + 상세를 content_id 로 합쳐 돌려준다."""
    details = {d["content_id"]: d for d in read_jsonl(Path(str(DETAIL_PATH).format(code=sido_code)))}
    for p in read_jsonl(Path(str(META_PATH).format(code=sido_code))):
        d = details.get(p["content_id"], {})
        yield {**p, "overview": d.get("overview", ""), "homepage": d.get("homepage", "")}


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", nargs="*", help="법정동 시도코드 (기본: 수도권 11 28 41)")
    ap.add_argument("--all", action="store_true", help="수도권 제외 나머지 시도 전부 (2주차용). --area 와 같이 주면 전국")
    ap.add_argument("--types", nargs="*", type=int, default=list(regions.CONTENT_TYPES), help="콘텐츠타입 (기본: 전부)")
    ap.add_argument("--no-meta", action="store_true", help="메타 수집 건너뛰기 (상세만)")
    ap.add_argument("--no-detail", action="store_true", help="상세 수집 건너뛰기 (메타만)")
    ap.add_argument("--detail-limit", type=int, default=None, help="오늘 상세 호출 상한 (기본: 남은 일일 한도)")
    ap.add_argument("--daily-limit", type=int, default=DEV_DAILY_LIMIT, help="기능별 일일 한도 (운영계정이면 올릴 것)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()
    areas = regions.parse_area_args(args.area, args.all)
    client = TourClient(daily_limit=args.daily_limit)
    log.info("대상 시도: %s | 타입: %s", ", ".join(f"{a}({regions.sido_name(a)})" for a in areas), args.types)

    for code in areas:
        if not args.no_meta:
            try:
                collect_meta(client, code, args.types)
            except (RetryableHTTPError, QuotaExceeded) as e:
                log.error("%s 메타 수집 중단: %s", regions.sido_name(code), e)
                break
        if not args.no_detail:
            collect_detail(client, code, args.detail_limit, args.types)
            if client.quota_detail.exhausted():
                log.warning("detailCommon2 오늘 한도 소진. 나머지 시도 상세는 내일 `--no-meta` 로 이어서")
                args.no_detail = True

    log.info(
        "오늘 호출: areaBasedList2 %d / detailCommon2 %d / ldongCode2 %d",
        client.quota_list.used, client.quota_detail.used, client.quota_code.used,
    )


if __name__ == "__main__":
    main()
