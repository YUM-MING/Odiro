# Odiro 프론트엔드

React 19 + TypeScript + Vite. 백엔드 계약은 [../docs/API_SCHEMA.md](../docs/API_SCHEMA.md), 타입은 `src/api.ts` (백엔드 `odiro/api/schemas.py` 와 1:1).

## 실행

```bash
npm install
npm run dev        # http://localhost:5173 — /api 는 localhost:8000(백엔드)으로 프록시
npm run lint       # oxlint
npm run build      # tsc + vite build → dist/
```

- 백엔드 없이 화면만 보려면 `VITE_MOCK=1 npm run dev` (PowerShell: `$env:VITE_MOCK="1"; npm run dev`). 예시 코스로 동작한다.
- 배포 빌드는 `VITE_API_URL` 로 Cloud Run 주소를 넣는다. 진행 상태(SSE)가 Hosting rewrite 를 거치면 버퍼링되기 때문에 프론트가 백엔드를 직접 호출한다. `main` 에 push 하면 GitHub Actions 가 빌드해 Firebase Hosting 에 올린다.
- 카카오 지도 JS 키는 프론트에 두지 않고 백엔드 `/api/public-config` 에서 받는다. 카카오 디벨로퍼스의 **JavaScript SDK 도메인**에 접속 도메인이 등록돼 있어야 지도가 뜬다.

## 구조 (`src/`)

| 파일 | 역할 |
|---|---|
| `App.tsx` · `HeroScene.tsx` | 랜딩 (검색 카드) |
| `Builder.tsx` | 조건 입력: 나들이/여행, 지역, 날짜·일수, 숙소(여행), 이동수단, 시간, 동행, 1인 예산, 분위기, 자유 조건 |
| `Plan.tsx` | `/plan` 플래너: 조건 요약, 진행 표시, 채팅(답변 + 장소 카드), 빠른 수정, 공유 |
| `Progress.tsx` | 노드별 진행 표시. 완성되면 한 줄로 접히고 "과정 보기" 로 펼친다 |
| `MapView.tsx` | 카카오맵: 번호 핀(종류별 색), 동선(Day 별 색), 선택 장소 팝업 |
| `mapUtil.ts` | 색 규칙(밥집 주황 · 카페 갈색 · 놀거리 초록 · 숙소 파랑), 카카오맵 링크(리뷰·길찾기·하루 전체 경로) |
| `markdown.ts` | 답변용 작은 마크다운 렌더러 (HTML 은 전부 이스케이프) |
| `api.ts` · `request.ts` | API 호출·SSE 구독, 요청 기본값·프리셋·세션 저장 |
| `mock.ts` · `steps.ts` | 예시 모드 데이터, 진행 단계 이름 |

## 알아둘 것

- 장소 카드는 `<button>` 이라 안에 `<a>` 를 넣지 않고 `role="link"` + `window.open` 으로 링크를 연다 (리뷰 보기, 길찾기).
- 번호 목록은 항목 사이에 이동 안내(`↳`) 줄이 끼어 목록이 끊기므로, 렌더러가 원문 번호를 `<li value>` 로 그대로 쓴다.
- "내비로 전체 경로 열기" 는 카카오맵 `https://map.kakao.com/link/by/car/이름,위도,경도/…` 링크다 (도보는 `by/walk`). 출발·도착 포함 7곳까지 넣는다.
- 새로고침해도 `/plan` 이 유지되도록 요청과 코스를 `sessionStorage` 에 둔다.
