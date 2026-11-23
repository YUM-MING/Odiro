"""코스 품질 평가: 시나리오 10개를 실제로 돌려 지표를 표로 만든다 (품질 작업의 전후 비교용).

지표
- 미확인: 지도 확인이 안 된 장소 수 (verified 아님 · 좌표 없음. 카카오 장소 ID 는 보지 않는다: TourAPI 큐레이션 장소는 ID 없이 들어가도 된다). 항상 0 이어야 한다
- 반경밖: 지역 중심에서 파이프라인이 쓰는 반경(뚜벅이 1.5km · 자차 동네 8km · 자차 시군구 30km)을 넘은 장소 비율
- 구성: 날짜별 식당·카페·볼거리(관광지·놀거리·산책·쇼핑·기타) 수. 식당·카페가 하루에 하나라도 없으면 '구성 미흡'
- 시간: 코스 생성에 걸린 시간(초). 항상 캐시 없이 새로 만든다
- 예산: 1인 예상 비용 합계가 예산을 넘었는지
- 종료초과: 날짜별로 숙소를 뺀 마지막 장소가 끝나는 시각(도착+체류)이 end_time 을 넘은 분(分). 항상 0 이어야 한다
- 중복의심: 코스 전체에서 같은 가게로 보이는 장소 쌍 수 (same_place 기준. 날짜마다 같은 숙소는 의도이므로 제외). 항상 0 이어야 한다
- 분류의심: 이름은 카페·식당인데 카테고리가 다른 장소 수 (이름 단어 기준의 대략적인 지표)
- 결과 JSON 에는 경고 문구(warnings_text)·중복 의심 쌍·분류 의심 장소도 저장한다

실행 (LLM·지도 API 를 실제로 호출하므로 시나리오 1개당 약 30~60초, 비용이 든다):
    python scripts/eval_courses.py                       # 전체, 결과 저장
    python scripts/eval_courses.py --only seongsu_walk gapyeong_trip
    python scripts/eval_courses.py --date 2026-11-20     # 날짜 지정 (기본: 오늘+2일. 예보는 5일 안쪽만 잡힌다)
    python scripts/eval_courses.py --compare cache/eval/20261118-1000.json   # 이전 결과와 비교 (시나리오 이름으로 짝지음)
    python scripts/eval_courses.py --summarize "cache/eval/baseline/*.json"   # 여러 결과 파일을 시나리오별로 합쳐 보기 (실행 안 함)
결과는 cache/eval/<시각(초)>_<시나리오>.json 에 저장되고(같은 이름이 있으면 -2, -3 …), 표(markdown)는 같은 이름의 .md 로도 저장된다.
날씨는 날짜에 따라 정해지므로 '비' 시나리오는 실내 분위기를 고르고, 실제 예보는 '날씨' 열로 확인한다.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from odiro.api.schemas import CourseRequest, CourseResponse
from odiro.config import settings
from odiro.tools._util import haversine_m
from odiro.tools.search_place import _norm_name, name_similarity

EAT, CAFE, STAY = "식당", "카페", "숙소"

SCENARIOS: dict[str, dict[str, Any]] = {
    # 도보 · 수도권
    "seongsu_walk": {
        "region": "성수동", "start_time": "13:00", "end_time": "21:00", "moods": ["감성/조용한", "사진맛집"],
        "party": "연인", "free_text": "사람 적고 분위기 있는 곳",
    },
    "hongdae_rain": {
        "region": "홍대", "start_time": "12:00", "end_time": "20:00", "moods": ["실내(비오는날)", "힙한/트렌디"],
        "party": "친구", "free_text": "비 오는 날 실내 위주로",
    },
    "ikseon_retro": {
        "region": "종로 익선동", "start_time": "11:00", "end_time": "19:00", "moods": ["레트로", "사진맛집"], "budget": 70_000,
    },
    "suwon_walk": {
        "region": "수원 행궁동", "start_time": "11:00", "end_time": "19:00", "moods": ["자연/산책", "감성/조용한"], "party": "친구",
    },
    # 자차 · 수도권
    "songdo_family": {
        "region": "인천 송도", "transport": "car", "start_time": "10:00", "end_time": "18:00", "budget": 150_000,
        "moods": ["아이동반", "실내(비오는날)"], "party": "가족(아이 2명)", "headcount": 4,
        "free_text": "비 오면 실내 대안, 아이 동반 가능한 식당",
    },
    "gapyeong_trip": {
        "mode": "trip", "transport": "car", "region": "가평", "days": 2, "start_time": "10:00", "end_time": "21:00",
        "budget": 200_000, "moods": ["뷰맛집/일몰", "자연/산책"], "party": "연인", "free_text": "일출 명소와 주차 편한 맛집",
    },
    # 수도권 밖
    "gangneung_trip": {
        "mode": "trip", "transport": "car", "region": "강릉", "days": 2, "start_time": "09:00", "end_time": "20:00",
        "budget": 250_000, "moods": ["뷰맛집/일몰", "감성/조용한"], "party": "연인", "free_text": "바다가 보이는 카페 꼭 포함",
    },
    "busan_walk": {
        "region": "부산 해운대", "start_time": "11:00", "end_time": "20:00", "moods": ["뷰맛집/일몰", "액티비티"], "party": "친구",
    },
    # 자유 조건
    "seongsu_must": {
        "region": "성수동", "start_time": "12:00", "end_time": "20:00", "moods": ["감성/조용한"], "party": "연인",
        "free_text": "반지공방 체험 꼭 넣어줘",
    },
    "jeonju_vegan": {
        "mode": "trip", "region": "전주 한옥마을", "days": 2, "start_time": "10:00", "end_time": "20:00", "budget": 150_000,
        "moods": ["레트로", "사진맛집"], "free_text": "비건 메뉴 있는 식당 포함, 웨이팅 적게",
    },
    # 사이트 프리셋 "# 가평 1박 2일" 을 다른 값 없이 눌렀을 때 서버가 받는 요청과 같게 (날짜만 --date).
    # frontend: request.ts defaultRequest() 위에 PRESETS 의 patch 를 applyPreset 으로 덮음 → Plan.tsx 가 day_starts 를 뺀 뒤 그대로 POST
    "gapyeong_preset": {
        "mode": "trip", "transport": "car", "region": "가평", "days": 2, "start_time": "11:00", "end_time": "20:00",
        "budget": 100_000, "moods": ["자연/산책", "뷰맛집/일몰"], "free_text": "", "party": "연인", "headcount": 1, "lodging": "",
    },
}


# ---------- 지표 (순수 함수: 네트워크 없이 테스트 가능) ----------


def is_unverified(p: Any) -> bool:
    # 카카오 ID 는 보지 않는다. 빈 자리를 채우는 TourAPI 큐레이션 장소는 공식 데이터라 ID·카카오 확인 없이 verified=True 로 들어간다
    return not (p.verified and p.lat and p.lng)


def composition(places: list[Any]) -> dict[int, dict[str, int]]:
    """날짜별 {'식당': n, '카페': n, '볼거리': n}. 숙소는 센다고 해도 구성 판단에는 넣지 않는다."""
    days: dict[int, dict[str, int]] = {}
    for p in places:
        if p.category == STAY:
            continue
        c = days.setdefault(p.day, {EAT: 0, CAFE: 0, "볼거리": 0})
        c[p.category if p.category in (EAT, CAFE) else "볼거리"] += 1
    return days


def _to_min(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def overtime(places: list[Any], end_time: str) -> dict[int, int]:
    """날짜별 종료 시각 초과 분. 숙소는 제외하고 그날 마지막 장소가 끝나는 시각(도착+체류)으로 잰다. 초과한 날만 담는다."""
    limit = _to_min(end_time)
    if limit is None:
        return {}
    ends: dict[int, int] = {}
    for p in places:
        arrive = _to_min(p.arrive) if p.category != STAY else None
        if arrive is not None:
            ends[p.day] = max(ends.get(p.day, 0), arrive + p.stay_min)
    return {d: e - limit for d, e in sorted(ends.items()) if e > limit}


# ---------- 같은 가게 판정 (묶음 1 Q3 에서 앱의 중복 제거도 이 기준을 그대로 쓴다) ----------

SAME_NAME_RADIUS_M = 150  # 정규화한 이름이 완전히 같으면 이 거리 안까지 같은 가게
SIMILAR_NAME_MIN = 0.85  # 이름 유사도가 이 이상이면
SIMILAR_NAME_RADIUS_M = 50  # 이 거리 안에서만 같은 가게 (같은 브랜드의 다른 지점과 구분)


def same_place(name_a: str, lat_a: float, lng_a: float, name_b: str, lat_b: float, lng_b: float) -> tuple[bool, int]:
    """두 장소가 같은 가게인지와 직선거리(m).

    같은 가게 = (정규화 이름 일치 & 거리 ≤ 150m) 또는 (이름 유사도 ≥ 0.85 & 거리 ≤ 50m). 좌표만으로는 판정하지 않는다.
    정규화·유사도·거리는 앱 함수를 그대로 쓴다: search_place._norm_name, search_place.name_similarity, _util.haversine_m
    """
    dist = haversine_m(lat_a, lng_a, lat_b, lng_b)
    a, b = _norm_name(name_a or ""), _norm_name(name_b or "")
    if not a or not b:
        return False, dist
    if a == b and dist <= SAME_NAME_RADIUS_M:
        return True, dist
    return name_similarity(a, b) >= SIMILAR_NAME_MIN and dist <= SIMILAR_NAME_RADIUS_M, dist


def duplicate_pairs(places: list[Any]) -> list[dict[str, Any]]:
    """코스 전체(날짜 무관)에서 같은 가게로 보이는 장소 쌍. 둘 다 숙소면 제외 (여행은 날마다 같은 숙소를 넣는 게 의도)."""
    pairs = []
    for x, y in combinations(places, 2):
        if x.category == STAY and y.category == STAY:
            continue
        same, dist = same_place(x.name, x.lat, x.lng, y.name, y.lat, y.lng)
        if same:
            pairs.append({"a": x.name, "a_category": x.category, "a_day": x.day, "b": y.name, "b_category": y.category, "b_day": y.day, "dist_m": dist})
    return pairs


# ---------- 분류 의심 (응답에 카카오 업종이 없어 이름 단어로 대략 본다. 짧고 보수적인 목록) ----------

CAFE_WORDS = ("카페", "커피", "베이커리", "제과", "디저트")
EAT_WORDS = ("식당", "국수", "수제비", "갈비", "국밥", "찌개", "샤브", "냉면", "곰탕", "횟집")
# 이 말이 들어간 이름은 가게가 아니라 거리·마을·전시일 가능성이 커서 의심하지 않는다 (예: 성수동카페거리, 닭갈비골목, 커피박물관)
NOT_A_SHOP_WORDS = ("거리", "골목", "마을", "타운", "박물관", "전시관", "체험관")


def mislabeled(places: list[Any]) -> list[dict[str, Any]]:
    """이름은 카페인데 카테고리가 카페가 아님 / 이름은 식당인데 카테고리가 관광지·카페인 장소. 숙소는 보지 않는다."""
    out = []
    for p in places:
        name = p.name.replace(" ", "")
        if p.category == STAY or any(w in name for w in NOT_A_SHOP_WORDS):
            continue
        if any(w in name for w in CAFE_WORDS) and p.category != CAFE:
            out.append({"name": p.name, "category": p.category, "looks_like": CAFE, "day": p.day})
        elif any(w in name for w in EAT_WORDS) and p.category in ("관광지", CAFE):
            out.append({"name": p.name, "category": p.category, "looks_like": EAT, "day": p.day})
    return out


def evaluate(resp: CourseResponse, center: dict[str, Any] | None, radius_m: int) -> dict[str, Any]:
    places = resp.places
    unverified = [p.name for p in places if is_unverified(p)]
    outside = []
    if center:
        outside = [
            p.name for p in places
            if haversine_m(center["lat"], center["lng"], p.lat, p.lng) > radius_m
        ]
    comp = composition(places)
    lacking = [d for d, c in comp.items() if c[EAT] == 0 or c[CAFE] == 0]
    budget_total = resp.request.budget
    over = overtime(places, resp.request.end_time)
    dups = duplicate_pairs(places)
    mislabels = mislabeled(places)
    return {
        "places": len(places),
        "unverified": len(unverified),
        "unverified_names": unverified,
        "outside": len(outside),
        "outside_names": outside,
        "outside_ratio": round(len(outside) / len(places), 3) if places else 0.0,
        "comp": {str(d): c for d, c in sorted(comp.items())},
        "comp_ok": bool(comp) and not lacking,
        "days_lacking": lacking,
        "overtime": {str(d): m for d, m in over.items()},
        "overtime_max_min": max(over.values(), default=0),
        "est_cost": resp.meta.est_cost_total,
        "over_budget": resp.meta.est_cost_total > budget_total,
        "weather": ("비" if resp.meta.weather.rain else resp.meta.weather.summary or "예보없음"),
        "warnings": len(resp.meta.warnings),
        "warnings_text": list(resp.meta.warnings),
        "dup_suspects": len(dups),
        "dup_pairs": dups,
        "mislabels": len(mislabels),
        "mislabel_places": mislabels,
        "elapsed_s": round(resp.meta.elapsed_ms / 1000, 1),
    }


def comp_text(comp: dict[str, dict[str, int]]) -> str:
    return " / ".join(f"D{d} 식{c[EAT]}·카{c[CAFE]}·볼{c['볼거리']}" for d, c in comp.items())


def _sum_known(ms: list[dict[str, Any]], key: str) -> str:
    """새로 추가된 지표는 옛 결과 파일에 없을 수 있다 → 값이 있는 것만 더하고, 하나도 없으면 '-'."""
    vals = [m[key] for m in ms if key in m]
    return str(sum(vals)) if vals else "-"


def render_table(results: dict[str, dict[str, Any]]) -> str:
    head = (
        "| 시나리오 | 장소 | 미확인 | 반경밖 | 구성(식당·카페·볼거리) | 예산 | 종료초과 | 중복의심 | 분류의심 | 날씨 | 경고 | 시간(초) |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for key, m in results.items():
        if m.get("error"):
            rows.append(f"| {key} | 실패: {m['error'][:60]} | | | | | | | | | | {m.get('elapsed_s', '')} |")
            continue
        comp = comp_text(m["comp"]) + ("" if m["comp_ok"] else " ⚠구성 미흡")
        out = f"{m['outside']}/{m['places']} ({m['outside_ratio']:.0%})"
        budget = "초과" if m["over_budget"] else "ok"
        late = "ok" if not m.get("overtime_max_min") else ", ".join(f"D{d} +{v}분" for d, v in m["overtime"].items())
        rows.append(
            f"| {key} | {m['places']} | {m['unverified']} | {out} | {comp} | {budget} | {late} | "
            f"{m.get('dup_suspects', '-')} | {m.get('mislabels', '-')} | {m['weather']} | {m['warnings']} | {m['elapsed_s']} |"
        )
    ok = [m for m in results.values() if not m.get("error")]
    if ok:
        n_places = sum(m["places"] for m in ok)
        n_out = sum(m["outside"] for m in ok)
        times = sorted(m["elapsed_s"] for m in ok)
        rows.append(
            f"| **합계/평균** ({len(ok)}/{len(results)} 성공) | {n_places} | **{sum(m['unverified'] for m in ok)}** | "
            f"{n_out}/{n_places} ({(n_out / n_places if n_places else 0):.0%}) | 구성 미흡 {sum(not m['comp_ok'] for m in ok)}건 | "
            f"초과 {sum(m['over_budget'] for m in ok)}건 | {sum(bool(m.get('overtime_max_min')) for m in ok)}건 | "
            f"{_sum_known(ok, 'dup_suspects')} | {_sum_known(ok, 'mislabels')} | | {sum(m['warnings'] for m in ok)} | "
            f"평균 {sum(times) / len(times):.1f} · 최대 {times[-1]} |"
        )
    return head + "\n".join(rows)


def render_compare(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> str:
    """같은 시나리오(이름 기준)끼리 핵심 지표를 전 → 후로 나란히. 옛 파일에 없는 지표는 '-'."""
    lines = [
        "| 시나리오 | 미확인 | 반경밖 비율 | 구성 미흡 | 예산 초과 | 종료초과(분) | 중복의심 | 분류의심 | 경고 | 시간(초) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def arrow(a: Any, b: Any, fmt: str = "{}") -> str:
        fa = fmt.format(a) if a != "-" else "-"
        fb = fmt.format(b) if b != "-" else "-"
        return fa if a == b else f"{fa} → {fb}"

    for key, n in new.items():
        o = old.get(key)
        if not o or o.get("error") or n.get("error"):
            lines.append(f"| {key} | (비교 불가) | | | | | | | | |")
            continue
        lines.append(
            f"| {key} | {arrow(o['unverified'], n['unverified'])} | {arrow(o['outside_ratio'], n['outside_ratio'], '{:.0%}')} | "
            f"{arrow(not o['comp_ok'], not n['comp_ok'])} | {arrow(o['over_budget'], n['over_budget'])} | "
            f"{arrow(o.get('overtime_max_min', '-'), n.get('overtime_max_min', 0))} | "
            f"{arrow(o.get('dup_suspects', '-'), n.get('dup_suspects', '-'))} | {arrow(o.get('mislabels', '-'), n.get('mislabels', '-'))} | "
            f"{arrow(o.get('warnings', '-'), n.get('warnings', '-'))} | {arrow(o['elapsed_s'], n['elapsed_s'])} |"
        )
    return "\n".join(lines)


# ---------- 여러 결과 파일을 시나리오별로 합치기 (반복 실행의 전후 비교용) ----------


def expand_paths(patterns: list[str]) -> list[Path]:
    """경로·와일드카드 목록 → 실제 파일 (PowerShell 은 외부 명령에 와일드카드를 펼쳐 주지 않으므로 여기서 펼친다). 중복 제거, 이름순."""
    files: set[Path] = set()
    for pat in patterns:
        hits = glob.glob(pat)
        files.update(Path(h) for h in (hits or ([pat] if Path(pat).exists() else [])))
    return sorted(files)


def summarize(files: list[Path]) -> str:
    """결과 파일들을 시나리오별로 모아 실행 횟수와 지표 합계·평균을 표로. 실패한 실행은 '실패' 로만 센다."""
    runs: dict[str, list[dict[str, Any]]] = {}
    dates: set[str] = set()
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        dates.add(str(data.get("date", "?")))
        for key, m in data.get("results", {}).items():
            runs.setdefault(key, []).append(m)
    lines = [
        f"## 결과 요약 ({len(files)}개 파일, 출발일 {', '.join(sorted(dates))})"
        + ("\n\n⚠ 출발일이 서로 다른 파일이 섞여 있다 — 날씨가 달라 비교가 부정확할 수 있다" if len(dates) > 1 else ""),
        "",
        "| 시나리오 | 실행 | 실패 | 미확인 합 | 반경밖 | 구성 미흡 | 카페 0곳인 날 | 예산 초과 | 종료초과 | 중복의심 합 | 분류의심 합 | 경고 합 | 시간 평균·최대(초) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key in sorted(runs):
        ms = runs[key]
        ok = [m for m in ms if not m.get("error")]
        if not ok:
            lines.append(f"| {key} | {len(ms)} | {len(ms)} | | | | | | | | | | |")
            continue
        n_places = sum(m["places"] for m in ok)
        no_cafe = sum(1 for m in ok for c in m["comp"].values() if c.get(CAFE, 0) == 0)
        times = [m["elapsed_s"] for m in ok]
        lines.append(
            f"| {key} | {len(ms)} | {len(ms) - len(ok)} | {sum(m['unverified'] for m in ok)} | "
            f"{sum(m['outside'] for m in ok)}/{n_places} | {sum(not m['comp_ok'] for m in ok)}/{len(ok)}회 | {no_cafe} | "
            f"{sum(m['over_budget'] for m in ok)}/{len(ok)}회 | {sum(bool(m.get('overtime_max_min')) for m in ok)}/{len(ok)}회 | "
            f"{_sum_known(ok, 'dup_suspects')} | {_sum_known(ok, 'mislabels')} | {sum(m['warnings'] for m in ok)} | "
            f"{sum(times) / len(times):.1f} · {max(times)} |"
        )
    return "\n".join(lines)


# ---------- 결과 저장 (짧은 간격으로 여러 번 돌려도 덮어쓰지 않는다) ----------


def result_path(out_dir: Path, keys: list[str], now: datetime | None = None) -> Path:
    """cache/eval/<YYYYMMDD-HHMMSS>_<시나리오>.json. 같은 이름이 있으면 -2, -3 … 을 붙인다 (.md 는 같은 이름)."""
    now = now or datetime.now()
    label = "all" if set(keys) == set(SCENARIOS) else "+".join(keys)
    stem = f"{now:%Y%m%d-%H%M%S}_{label[:80]}"
    path, n = out_dir / f"{stem}.json", 1
    while path.exists() or path.with_suffix(".md").exists():
        n += 1
        path = out_dir / f"{stem}-{n}.json"
    return path


def save_results(out_dir: Path, keys: list[str], day: str, results: dict[str, dict[str, Any]], table_md: str, now: datetime | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = result_path(out_dir, keys, now)
    path.write_text(json.dumps({"date": day, "scenarios": keys, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    path.with_suffix(".md").write_text(table_md, encoding="utf-8")
    return path


# ---------- 실행 ----------


def run_scenario(key: str, day: str) -> dict[str, Any]:
    from odiro.agent import nodes
    from odiro.agent.run import run_course
    from odiro.tools import search_place

    req = CourseRequest(date=day, **SCENARIOS[key])
    t0 = time.time()
    try:
        resp = run_course(req, use_cache=False)
    except Exception as e:  # noqa: BLE001  한 시나리오가 죽어도 나머지는 계속
        return {"error": f"{type(e).__name__}: {e}", "elapsed_s": round(time.time() - t0, 1)}
    center = None
    try:
        center = search_place.geocode_region(req.region)
    except Exception as e:  # noqa: BLE001
        print(f"    중심 좌표 조회 실패(반경 지표 생략): {e}")
    radius = nodes.VERIFY_RADIUS.get(req.transport, 5000)
    if nodes._radius_key(req.model_dump()) == "car_local":
        radius = nodes.RAG_RADIUS_M["car_local"]
    m = evaluate(resp, center, radius)
    if not resp.places:
        m["error"] = "장소 0곳"
    m["radius_m"] = radius
    m["titles"] = [f"D{p.day}-{p.order} {p.name}[{p.category}]" for p in resp.places]
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=list(SCENARIOS), default=list(SCENARIOS))
    ap.add_argument("--date", default=(date.today() + timedelta(days=2)).isoformat(), help="출발일 YYYY-MM-DD (기본 오늘+2일)")
    ap.add_argument("--compare", help="이전 결과 JSON 경로. 같은 시나리오끼리 전후 비교표를 덧붙인다")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument(
        "--summarize", nargs="+", metavar="FILE",
        help="결과 JSON 파일·와일드카드 여러 개를 시나리오별로 합친 표만 출력하고 끝낸다 (코스를 만들지 않음, 비용 없음)",
    )
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    if args.summarize:
        files = expand_paths(args.summarize)
        if not files:
            sys.exit(f"결과 파일을 찾지 못했다: {args.summarize}")
        print(summarize(files))
        return

    results: dict[str, dict[str, Any]] = {}
    for i, key in enumerate(args.only, 1):
        print(f"[{i}/{len(args.only)}] {key} ...", flush=True)
        results[key] = run_scenario(key, args.date)
        m = results[key]
        print("   ", f"실패 {m['error']}" if m.get("error") else f"{m['places']}곳 {m['elapsed_s']}s 미확인 {m['unverified']} 반경밖 {m['outside']} 종료초과 {m['overtime_max_min']}분", flush=True)

    table = render_table(results)
    out = f"## 코스 평가 ({datetime.now():%Y-%m-%d %H:%M}, 출발일 {args.date}, {len(results)}개)\n\n{table}\n"
    if args.compare:
        old = json.loads(Path(args.compare).read_text(encoding="utf-8")).get("results", {})
        out += f"\n### 비교 (이전 {args.compare} → 이번)\n\n{render_compare(old, results)}\n"
    bad = [(k, m) for k, m in results.items() if m.get("unverified")]
    for k, m in bad:
        out += f"\n⚠ {k}: 확인 안 된 장소 {m['unverified_names']}\n"
    print("\n" + out)

    if not args.no_save:
        path = save_results(settings.cache_dir / "eval", list(args.only), args.date, results, out)
        print(f"저장: {path}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
