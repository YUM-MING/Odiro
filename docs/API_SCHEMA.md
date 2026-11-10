# API 스키마 (프론트 ↔ 백엔드 계약)

> 타입의 원본은 `odiro/api/schemas.py`. 바꾸면 이 문서와 `frontend/src/api.ts` 도 같이 바꾼다.
> 모든 응답은 JSON, 한글은 그대로(UTF-8). 시각은 `HH:MM`, 날짜는 `YYYY-MM-DD`, 좌표는 `lat`(위도)·`lng`(경도) 숫자.

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/health` | 헬스체크 `{status, version}` |
| GET | `/api/public-config` | `{kakao_js_api_key}` — 프론트 지도 SDK 로드용 |
| GET | `/api/moods` | 분위기 태그 목록 `{moods: string[]}` |
| POST | `/api/course` | **동기** 코스 생성. 본문 `CourseRequest` → `CourseResponse` (최대 ~40초) |
| POST | `/api/course/start` | **비동기** 시작. 본문 `CourseRequest` → `{job_id, stream_url}` |
| GET | `/api/course/stream/{job_id}` | SSE. `progress` 이벤트(노드 진행) 여러 번 → `result` 1번 (또는 `error`) |
| POST | `/api/course/edit` | 수정 플라이휠. 본문 `EditRequest` → `CourseResponse` (바뀐 장소만 재검증·재동선) |
| POST | `/api/course/edit/start` | 수정의 비동기 버전 → `{job_id, stream_url}` |

프론트는 기본적으로 `start` + `stream` 을 쓴다 (사이드바 진행 표시). `POST /api/course` 는 CLI·테스트·캐시 워밍용.

## CourseRequest

```json
{
  "mode": "outing",            // "outing" 나들이(1일) | "trip" 여행(n일)
  "transport": "walk",         // "walk" 뚜벅이 | "car" 자차
  "region": "성수동",           // 자유 텍스트 (시도/시군구/동/랜드마크)
  "date": "2026-11-15",
  "start_time": "11:00",
  "end_time": "20:00",
  "days": 1,                   // trip 이면 1~3
  "budget": 100000,            // 1인 예산(원)
  "moods": ["감성/조용한", "사진맛집"],
  "free_text": "비건 메뉴 있는 식당 하나는 꼭",
  "party": "연인"
}
```

## CourseResponse

```json
{
  "course_id": "c_8f3a…",
  "request": { …CourseRequest… },
  "title": "성수동 골목 감성 데이트",
  "places": [
    {
      "order": 1, "day": 1,
      "name": "서울숲", "category": "관광지",
      "lat": 37.5444, "lng": 127.0374,
      "address": "서울 성동구 뚝섬로 273",
      "kakao_place_id": "8128830", "place_url": "http://place.map.kakao.com/8128830",
      "phone": "02-460-2905",
      "reason": "오후 햇살 아래 은행나무길 산책으로 시작",
      "tags": ["자연/산책", "사진맛집"],
      "review_summary": "평일 오후엔 한산하고 가을 단풍이 예쁘다는 평",
      "arrive": "11:00", "stay_min": 70,
      "image": "https://…", "verified": true, "source": "rag"
    }
  ],
  "legs": [
    { "from_idx": 0, "to_idx": 1, "transport": "walk", "duration_min": 12, "distance_m": 900,
      "polyline": [[37.5444,127.0374],[37.5448,127.0401]], "estimated": false }
  ],
  "answer_md": "**Odiro:** 성수동에서 조용히 걷는 하루를 짜봤어요…\n\n1. **서울숲** (11:00, 70분) …",
  "meta": {
    "sun": { "sunrise": "07:10", "sunset": "17:22" },
    "weather": { "available": true, "summary": "맑음", "temp_c": 9.5, "pop": 0.1, "rain": false, "note": "" },
    "rag_docs": 8, "web_docs": 3,
    "warnings": ["3→4 구간은 길찾기 실패로 직선거리 추정"],
    "trace": [ { "node": "parse_intent", "status": "done", "ms": 1200, "detail": "" }, … ],
    "cached": false, "elapsed_ms": 23400
  }
}
```

규칙
- `places` 는 `day` → `order` 순으로 정렬되어 있다. `legs` 의 `from_idx/to_idx` 는 `places` 배열 인덱스이며 같은 day 안에서만 이어진다.
- `verified == false` 인 장소는 응답에 포함하지 않는다 (백엔드가 보장). 프론트는 그래도 `verified` 를 확인하고 지도에 올린다.
- `legs[].transport`: 뚜벅이 모드에서 도보 2.5km 초과 구간은 `transit` 로 표시되고 시간은 추정값(`estimated: true`).
- `meta.weather.rain == true` 면 프론트는 "비 예보 → 실내 위주로 구성" 배지를 보여준다. 코스 자체는 이미 실내 가중치로 생성됨.
- `answer_md` 의 첫 줄은 항상 `**Odiro:**` 로 시작.

## EditRequest

```json
{
  "course": { …직전 CourseResponse 그대로… },
  "instruction": "두 번째 카페를 조용한 곳으로 바꿔줘",
  "target_order": 2,          // 빠른 수정 버튼이면 지정, 자유 채팅이면 null
  "target_day": 1
}
```

응답은 `CourseResponse`. `course_id` 는 새로 발급, `meta.trace` 는 `modify → verify_places → optimize_route → enrich → compose_answer` 만 포함.

## SSE (`GET /api/course/stream/{job_id}`)

```
event: progress
data: {"node":"parse_intent","status":"start","ms":0,"detail":""}

event: progress
data: {"node":"parse_intent","status":"done","ms":1180,"detail":"성수동 → 서울 성동구"}

…

event: result
data: { …CourseResponse… }
```

- 노드 순서: `parse_intent → retrieve → draft_course → verify_places → optimize_route → enrich → compose_answer`
- `error` 이벤트: `{"message": "…"}` 후 스트림 종료. job 은 10분 뒤 폐기.
- 서버는 15초마다 `: keep-alive` 주석을 보낸다.

## 오류

- 400: 요청 스키마 오류 (FastAPI 기본 422 도 동일 취급)
- 404: 없는 job_id
- 503: LLM/필수 API 전부 실패 (`{"detail": "..."}`). 프론트는 "잠시 후 다시" 안내.
