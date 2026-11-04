# 데이터 · API 목록

> 뭘 발급받아야 하고, 뭘 모아야 하는지 한 장에 정리. 담당 주차는 [TEAM_ROLES.md](TEAM_ROLES.md) 기준.
> 키 값은 **절대 이 문서나 git 에 쓰지 않는다.** 로컬은 `.env`, 배포는 Cloud Run 환경변수에만 넣는다.

## 1. API 키 (총 10개, 필수 9 + 선택 1)

| # | API | 용도 | 환경변수 | 발급 | 무료 한도 | 발급 난이도 | 담당 |
|---|---|---|---|---|---|---|---|
| 1 | **OpenAI** (또는 Anthropic) | LLM 코스 생성·라벨링·임베딩 | `OPENAI_API_KEY` | https://platform.openai.com/api-keys | 유료 (gpt-4o-mini 기준 코스 1건 ≈ 10~30원) | 쉬움, 카드 필요 | 1주차 |
| 2 | **Kakao Local** (REST) | 장소 검색·좌표·실존 검증 | `KAKAO_REST_API_KEY` | https://developers.kakao.com → 내 애플리케이션 → 앱 키 | 일 30만 회 | 쉬움 | 1주차 |
| 3 | **Kakao Map JS** | 프론트 지도 표시 | `KAKAO_JS_API_KEY` | 2번과 같은 앱의 JavaScript 키. **플랫폼 → Web → 사이트 도메인에 `https://odiro-where.web.app`, `http://localhost:5173` 등록 필수** | 무료 | 쉬움 | 1주차 |
| 4 | **Kakao Mobility** (자차 길찾기) | 자동차 이동시간·경로 | `KAKAO_MOBILITY_API_KEY` | https://developers.kakaomobility.com → 앱 등록 (카카오디벨로퍼스와 **별도** 사이트) | 일 1만 회 | 보통 | 1주차 |
| 5 | **Tmap** (보행자 길찾기) | 뚜벅이 이동시간·경로 | `TMAP_APP_KEY` | https://openapi.sk.com → 앱 생성 → appKey | 일 1만 회 | 보통 | 1주차 |
| 6 | **TourAPI 4.0** (한국관광공사) | 전국 장소 메타데이터 대량 수집 | `TOUR_API_KEY` | https://www.data.go.kr → "한국관광공사_국문 관광정보 서비스_GW" 활용신청 → **일반 인증키(Decoding)** | 개발계정 일 1,000건 → **운영계정 증량 신청 필수** (승인 1~3일) | 느림 ⚠️ **가장 먼저 신청** | 1주차 |
| 7 | **네이버 검색 API** (블로그) | 큐레이션 글 수집 (RAG 원문) | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | https://developers.naver.com → 애플리케이션 등록 → 검색 API 체크 | 일 25,000회 | 쉬움 | 1주차 |
| 8 | **Tavily** | 실시간 웹검색 (팝업·휴무·핫플) | `TAVILY_API_KEY` | https://tavily.com | 월 1,000회 | 쉬움 | 2주차 |
| 9 | **OpenWeather** | 날씨·강수확률 → 실내 전환 | `OPENWEATHER_API_KEY` | https://openweathermap.org/api → Current + 5 day forecast | 분 60회 / 일 100만 | 쉬움 (활성화까지 ~2시간) | 2주차 |
| 10 | 기상청 단기예보 (선택) | OpenWeather 대체 | `KMA_API_KEY` | data.go.kr "기상청_단기예보 조회서비스" | 일 10,000건 | 보통 | 생략 가능 |

- 일출·일몰은 `astral` 라이브러리로 오프라인 계산 → 키 불필요.
- 점검 방법: `.env` 채우고 `python scripts/check_apis.py` → 키마다 `OK / FAIL / SKIP` 출력.
- **발급 순서 추천**: 6(TourAPI, 승인 대기) → 2·3·4(Kakao) → 7(네이버) → 1(OpenAI) → 5(Tmap) → 8·9.

### 키를 넣는 곳

| 환경 | 위치 | 방법 |
|---|---|---|
| 로컬 개발 | 프로젝트 루트 `.env` | `.env.example` 복사해서 채움 (git 제외됨) |
| 배포 (Cloud Run) | GCP 콘솔 → Cloud Run → `odiro-api` → **수정 및 새 버전 배포** → 변수 및 보안 비밀 | 변수 이름은 `.env.example` 과 동일. 저장하면 새 버전 자동 배포 |
| 프론트 (Kakao JS 키) | 백엔드 `/api/public-config` 가 내려줌 | 프론트 `.env` 에 넣지 않는다 (번들에 노출되므로 도메인 제한으로만 보호) |

### 팀원 계정 공유

- API 키는 **1명이 발급해 팀 메신저의 비공개 노트로 공유** (각자 `.env` 에 붙여넣기). git·문서·공개 채팅 금지.
- Kakao·TourAPI 처럼 콘솔에서 도메인·쿼터를 만지는 건 발급자가 담당.

## 2. 데이터 목록

### 2-1. 수집해야 하는 데이터

| # | 데이터 | 소스 | 규모 | 용도 | 산출물 경로 | 담당 |
|---|---|---|---|---|---|---|
| D1 | **시연 지역 3곳 장소 메타** (성수·강릉·전주) | TourAPI `areaBasedList2` | 약 3,000건 | 코스 후보 풀 (최우선) | `data/raw/tour/{지역}.jsonl` | 1주차 |
| D2 | **시연 지역 3곳 장소 상세** (overview) | TourAPI `detailCommon2` | 약 3,000회 호출 | 장소 설명 임베딩 | `data/raw/tour/{지역}_detail.jsonl` | 1주차 |
| D3 | **시연 지역 블로그 큐레이션 글** | 네이버 블로그 검색 | 3지역 × 테마 10 × 100건 ≈ 3,000건 | RAG 원문 (분위기) | `data/raw/blog/{지역}.jsonl` | 1주차 |
| D4 | **분위기 태그 라벨링** (D2+D3) | LLM (gpt-4o-mini) | ≈ 6,000건, 약 2~3달러 | 메타데이터 필터 | `data/raw/labeled/{지역}.jsonl` | 1주차 |
| D5 | **벡터 인덱스** (D4) | OpenAI embedding + Chroma | 1~2만 청크 | `rag_search` Tool | `data/vectorstore/` (git 제외, 압축본 공유) | 1주차 |
| D6 | **전국 장소 메타** (17개 시도) | TourAPI `areaBasedList2` | 5~6만 건, 호출 100회 미만 | "전국 어디를 입력해도 동작" 보장 | `data/raw/tour/all_{시도}.jsonl` | **2주차** |
| D7 | **전국 블로그 큐레이션 글** | 네이버 블로그 검색 | 229 시군구 × 테마 10 ≈ 2,300 쿼리 | 전국 RAG | `data/raw/blog/all/` | **2주차** (스크립트 돌려두고 다른 작업) |
| D8 | **전국 라벨링 + 인덱스 확장** | LLM + Chroma | 10~20만 건, 20~40달러 → **예산 보고 샘플링** | 전국 RAG 품질 | `data/vectorstore/` | 2주차 (시간 남으면), 아니면 3주차 |
| D9 | **시연 시나리오 캐시** | 완성된 파이프라인 실행 결과 | 3개 시나리오 | 시연 안정성 (네트워크 죽어도 동작) | `cache/demo/*.json` | 3주차 |

- D1~D5 가 끝나면 Phase 1 완료 (= 1주차 목표). D6~D8 은 양이 커서 **2주차가 수집 스크립트를 백그라운드로 돌리면서** 에이전트 작업을 병행한다.
- TourAPI 상세(D2·D6 상세)는 전수 호출이 비싸므로 **코스 생성 시 후보 장소만 지연 호출 + diskcache** 전략을 기본으로 하고, 사전 수집은 시연 지역만.
- 수집 스크립트 위치: `odiro/data/ingest/` (`tour_api.py`, `naver_blog.py`, `labeling.py`, `build_index.py` — 1주차가 만든다).

### 2-2. 데이터 공유 방법 (git 에 안 올라감)

- `data/raw/`, `data/vectorstore/`, `cache/` 는 `.gitignore` 되어 있음.
- 주차가 바뀔 때 `tar czf odiro-data-YYYYMMDD.tgz data/raw data/vectorstore` 로 묶어 **Google Drive 공유 폴더**에 올리고, 인수인계 문서에 링크를 적는다.
- Cloud Run 컨테이너는 상태가 없으므로 벡터 DB 는 **이미지에 포함**시키거나(수백 MB 이하면 OK) GCS 버킷에서 기동 시 내려받는다 → 3주차가 결정.

### 2-3. 하지 않는 것

- 인스타그램·캐치테이블·테이블링 **직접 크롤링 금지** (약관 위반 + 차단 → 시연 불안정).
- "웨이팅 적은" 같은 정보는 블로그 텍스트에서 LLM 태그로 추출, 예약은 링크 아웃.

## 3. 분위기 태그 체계 (라벨링 기준)

`감성/조용한` · `힙한/트렌디` · `뷰맛집/일몰` · `레트로` · `자연/산책` · `실내(비오는날)` · `액티비티` · `사진맛집` · `웨이팅적은` · `아이동반` · `반려동물` · `광고성(제외용)`
