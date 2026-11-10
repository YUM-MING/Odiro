"""Phase 0: 모든 API 키가 실제로 동작하는지 1회씩 호출해 점검한다.

실행: python scripts/check_apis.py
키가 비어 있으면 SKIP, 호출 실패하면 FAIL, 성공하면 OK 를 출력한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from odiro.config import settings  # noqa: E402

TIMEOUT = 10
# 테스트 좌표: 성수역 -> 서울숲
ORIGIN = (127.0559, 37.5445)  # (lng, lat)
DEST = (127.0374, 37.5444)


def _report(name: str, ok: bool | None, detail: str = "") -> None:
    tag = "SKIP" if ok is None else ("OK  " if ok else "FAIL")
    print(f"[{tag}] {name:<22} {detail}")


def check_kakao_local() -> None:
    if not settings.kakao_rest_api_key:
        return _report("Kakao Local", None, "KAKAO_REST_API_KEY 없음")
    try:
        r = httpx.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": "성수동 카페", "size": 3},
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        docs = r.json().get("documents", [])
        _report("Kakao Local", bool(docs), f"{len(docs)}건, 첫 결과: {docs[0]['place_name'] if docs else '-'}")
    except Exception as e:  # noqa: BLE001
        _report("Kakao Local", False, str(e)[:120])


def check_kakao_mobility() -> None:
    if not settings.kakao_mobility_api_key:
        return _report("Kakao Mobility (자차)", None, "KAKAO_MOBILITY_API_KEY 없음")
    try:
        r = httpx.get(
            "https://apis-navi.kakaomobility.com/v1/directions",
            params={
                "origin": f"{ORIGIN[0]},{ORIGIN[1]}",
                "destination": f"{DEST[0]},{DEST[1]}",
            },
            headers={"Authorization": f"KakaoAK {settings.kakao_mobility_api_key}"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        summary = r.json()["routes"][0]["summary"]
        _report(
            "Kakao Mobility (자차)",
            True,
            f"{summary['distance']}m, {summary['duration'] // 60}분",
        )
    except Exception as e:  # noqa: BLE001
        _report("Kakao Mobility (자차)", False, str(e)[:120])


def check_tmap_pedestrian() -> None:
    if not settings.tmap_app_key:
        return _report("Tmap 보행자", None, "TMAP_APP_KEY 없음")
    try:
        r = httpx.post(
            "https://apis.openapi.sk.com/tmap/routes/pedestrian",
            params={"version": 1},
            headers={"appKey": settings.tmap_app_key, "Content-Type": "application/json"},
            json={
                "startX": ORIGIN[0],
                "startY": ORIGIN[1],
                "endX": DEST[0],
                "endY": DEST[1],
                "startName": "start",
                "endName": "end",
                "reqCoordType": "WGS84GEO",
                "resCoordType": "WGS84GEO",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        props = r.json()["features"][0]["properties"]
        _report(
            "Tmap 보행자",
            True,
            f"{props['totalDistance']}m, {props['totalTime'] // 60}분",
        )
    except Exception as e:  # noqa: BLE001
        _report("Tmap 보행자", False, str(e)[:120])


def check_tour_api() -> None:
    if not settings.tour_api_key:
        return _report("TourAPI 4.0", None, "TOUR_API_KEY 없음")
    try:
        r = httpx.get(
            "https://apis.data.go.kr/B551011/KorService2/areaBasedList2",
            params={
                "serviceKey": settings.tour_api_key,
                "MobileOS": "ETC",
                "MobileApp": "Odiro",
                "_type": "json",
                "numOfRows": 3,
                "pageNo": 1,
                "arrange": "A",
                "contentTypeId": 12,  # 관광지
                "areaCode": 1,  # 서울
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()["response"]["body"]
        total = body.get("totalCount")
        first = body["items"]["item"][0]["title"] if body.get("items") else "-"
        _report("TourAPI 4.0", True, f"서울 관광지 totalCount={total}, 첫 결과: {first}")
    except Exception as e:  # noqa: BLE001
        _report("TourAPI 4.0", False, str(e)[:120])


def check_naver_blog() -> None:
    if not (settings.naver_client_id and settings.naver_client_secret):
        return _report("Naver Blog 검색", None, "NAVER_CLIENT_ID/SECRET 없음")
    try:
        # 2026-07-31 부터 검색 API 는 네이버 클라우드 플랫폼 "NAVER API HUB" 에서 발급·호출한다.
        # (구 developers.naver.com 키는 2027-06-30 까지만 동작)
        r = httpx.get(
            "https://naverapihub.apigw.ntruss.com/search/v1/blog",
            params={"query": "성수동 데이트 코스", "display": 3, "sort": "sim"},
            headers={
                "X-NCP-APIGW-API-KEY-ID": settings.naver_client_id,
                "X-NCP-APIGW-API-KEY": settings.naver_client_secret,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        _report("Naver Blog 검색", True, f"total={data.get('total')}")
    except Exception as e:  # noqa: BLE001
        _report("Naver Blog 검색", False, str(e)[:120])


def check_tavily() -> None:
    if not settings.tavily_api_key:
        return _report("Tavily 웹검색", None, "TAVILY_API_KEY 없음")
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": "성수동 팝업스토어 이번주",
                "max_results": 3,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        n = len(r.json().get("results", []))
        _report("Tavily 웹검색", n > 0, f"{n}건")
    except Exception as e:  # noqa: BLE001
        _report("Tavily 웹검색", False, str(e)[:120])


def check_openweather() -> None:
    if not settings.openweather_api_key:
        return _report("OpenWeather", None, "OPENWEATHER_API_KEY 없음")
    try:
        r = httpx.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "lat": ORIGIN[1],
                "lon": ORIGIN[0],
                "appid": settings.openweather_api_key,
                "units": "metric",
                "lang": "kr",
                "cnt": 1,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        item = r.json()["list"][0]
        _report("OpenWeather", True, f"{item['weather'][0]['description']}, {item['main']['temp']}°C")
    except Exception as e:  # noqa: BLE001
        _report("OpenWeather", False, str(e)[:120])


def check_llm() -> None:
    if settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key, timeout=TIMEOUT)
            out = llm.invoke("한 단어로 대답: 서울의 유명한 숲 공원은?")
            _report("LLM (OpenAI)", True, out.content[:40])
        except Exception as e:  # noqa: BLE001
            _report("LLM (OpenAI)", False, str(e)[:120])
    else:
        _report("LLM (OpenAI)", None, "OPENAI_API_KEY 없음")

    if settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic

            model = settings.llm_model if settings.llm_provider == "anthropic" else "claude-haiku-5-5"
            llm = ChatAnthropic(model=model, api_key=settings.anthropic_api_key, timeout=TIMEOUT)
            out = llm.invoke("한 단어로 대답: 서울의 유명한 숲 공원은?")
            _report("LLM (Anthropic)", True, str(out.content)[:40])
        except Exception as e:  # noqa: BLE001
            _report("LLM (Anthropic)", False, str(e)[:120])
    else:
        _report("LLM (Anthropic)", None, "ANTHROPIC_API_KEY 없음")


def check_sun_times() -> None:
    """외부 API 없이 astral 로 계산되는지 확인."""
    try:
        from datetime import date

        from astral import LocationInfo
        from astral.sun import sun

        loc = LocationInfo("Seoul", "KR", "Asia/Seoul", ORIGIN[1], ORIGIN[0])
        s = sun(loc.observer, date=date.today(), tzinfo="Asia/Seoul")
        _report("일출·일몰 (astral)", True, f"일출 {s['sunrise']:%H:%M}, 일몰 {s['sunset']:%H:%M}")
    except Exception as e:  # noqa: BLE001
        _report("일출·일몰 (astral)", False, str(e)[:120])


if __name__ == "__main__":
    print("=== Odiro API 점검 ===")
    check_llm()
    check_kakao_local()
    check_kakao_mobility()
    check_tmap_pedestrian()
    check_tour_api()
    check_naver_blog()
    check_tavily()
    check_openweather()
    check_sun_times()
    print("=== 끝 ===")
