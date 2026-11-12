# 데이터 · API 목록

> 뭘 발급받아야 하고, 뭘 모아야 하는지 한 장에 정리. 담당 주차는 [TEAM_ROLES.md](TEAM_ROLES.md) 기준.
> 키 값은 **절대 이 문서나 git 에 쓰지 않는다.** 로컬은 `.env`, 배포는 Cloud Run 환경변수에만 넣는다.

## 1. API 키 (총 10개, 필수 9 + 선택 1)

| # | API | 용도 | 환경변수 | 발급 | 무료 한도 | 발급 난이도 | 담당 |
|---|---|---|---|---|---|---|---|
| 1 | **OpenAI** (또는 Anthropic) | LLM 코스 생성·라벨링·임베딩 | `OPENAI_API_KEY` | https://platform.openai.com/api-keys | 유료 (gpt-4o-mini 기준 코스 1건 ≈ 10~30원) | 쉬움, 카드 필요 | 1주차 |
| 2 | **Kakao Local** (REST) | 장소 검색·좌표·실존 검증 | `KAKAO_REST_API_KEY` | https://developers.kakao.com → 내 애플리케이션 → 앱 키 | 일 30만 회 | 쉬움 | 1주차 |
| 3 | **Kakao Map JS** | 프론트 지도 표시 | `KAKAO_JS_API_KEY` | 2번과 같은 앱의 JavaScript 키. **앱 설정의 "JavaScript SDK 도메인" 에 `https://odiro-where.web.app`, `http://localhost:5173` 등록 필수** (예전 메뉴 이름은 플랫폼 → Web) | 무료 | 쉬움 | 1주차 |
| 4 | **Kakao Mobility** (자차 길찾기) | 자동차 이동시간·경로 | `KAKAO_MOBILITY_API_KEY` | https://developers.kakaomobility.com → 앱 등록 (카카오디벨로퍼스와 **별도** 사이트) | 일 1만 회 | 보통 | 1주차 |
| 5 | **Tmap** (보행자 길찾기) | 뚜벅이 이동시간·경로 | `TMAP_APP_KEY` | https://openapi.sk.com → 앱 생성 → appKey | 일 1만 회 | 보통 | 1주차 |
| 6 | **TourAPI 4.0** (한국관광공사) | 전국 장소 메타데이터 대량 수집 | `TOUR_API_KEY` | https://www.data.go.kr → "한국관광공사_국문 관광정보 서비스_GW" 활용신청 → **일반 인증키(Decoding)** | **개발계정** 기능별 일 1,000건 (자동승인, 즉시). 운영계정은 **호출 이력 없으면 반려**되므로 개발계정으로 수집해 이력을 쌓은 뒤 "운영계정 전환 신청" (심의 영업일 2~7일) | 보통 (개발계정) / 느림 (운영 전환) | 1주차 발급 · 운영 전환 신청함(11/12 미승인). **키를 여러 개 쓰려면 `TOUR_API_KEYS_EXTRA=키2,키3`** (팀원이 각자 발급, 키마다 일 1,000건) |
| 7 | **네이버 검색 API** (블로그) | 큐레이션 글 수집 (RAG 원문) | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | **네이버 클라우드 플랫폼** https://console.ncloud.com → Services → Application Services → **NAVER API HUB** → Application 등록(검색 API 체크) → 인증 정보. 2026-07-31 이관으로 developers.naver.com 에서는 신규 발급 불가. 엔드포인트 `https://naverapihub.apigw.ntruss.com/search/v1/blog`, 헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY` | 일 25,000회 (한시 무료) | 쉬움 (NCP 가입·결제수단 등록 필요) | 1주차 |
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
| 배포 (Cloud Run) | Cloud Run `odiro-api` 환경변수 | `python scripts/push_env_to_cloudrun.py` 가 `.env` 의 키를 올린다 (gcloud 로그인 필요). 콘솔에서 직접 넣어도 된다. 11/11 등록 완료 |
| 프론트 (Kakao JS 키) | 백엔드 `/api/public-config` 가 내려줌 | 프론트 `.env` 에 넣지 않는다 (번들에 노출되므로 도메인 제한으로만 보호) |

### 팀원 계정 공유

- API 키는 **1명이 발급해 팀 메신저의 비공개 노트로 공유** (각자 `.env` 에 붙여넣기). git·문서·공개 채팅 금지.
- Kakao·TourAPI 처럼 콘솔에서 도메인·쿼터를 만지는 건 발급자가 담당.

## 2. 데이터 목록

### 2-1. 수집해야 하는 데이터

| # | 데이터 | 소스 | 규모 | 용도 | 산출물 경로 | 담당 |
|---|---|---|---|---|---|---|
| D1 | **수도권 장소 메타** (법정동 시도코드 서울 11 · 인천 28 · 경기 41) | TourAPI `areaBasedList2` (`lDongRegnCd`, `numOfRows=1000`) | **실측 19,424건** (서울 8,008 / 인천 1,987 / 경기 9,429), 호출 48회 | 코스 후보 풀 (최우선) | `data/raw/tour/area_{시도코드}.jsonl` | 1주차 ✅ |
| D2 | **수도권 장소 상세** (overview) | TourAPI `detailCommon2` | 키마다 일 1,000건 → 키 3개로 하루 약 3,000건. 관광지→문화시설→음식점→…→쇼핑 순. **11/13 기준 서울 6,995 / 8,008** (남은 건 전부 쇼핑), 인천·경기 0 | 장소 설명 임베딩 (상세가 있는 장소만 인덱스에 들어간다) | `data/raw/tour/detail_{시도코드}.jsonl` | 매일 `python scripts/daily_ingest.py` (2주차가 이어받음) |
| D3 | **수도권 블로그 큐레이션 글** | 네이버 블로그 검색 (NCP API HUB) | 시군구 × 테마 11 × 상위 100건 → **실측 67,172건** (서울 18,442 / 인천 9,053 / 경기 39,677), 쿼리 ~2,000회 (`--start 31 --per-query 70` 로 31~100위 추가). 타지역 글 ~930건은 `off_region` 으로 제외 | RAG 원문 (분위기) | `data/raw/blog/area_{시도코드}.jsonl` | 1주차 ✅ |
| D4 | **분위기 태그 라벨링** (D2+D3) | gpt-4o-mini Structured Output, 10건 묶음 × 8 스레드 | **실측 65,199건**, 광고 판정 ~300건, 약 5달러 | 메타데이터 필터 | `data/raw/labeled/area_{시도코드}.jsonl` | 1주차 ✅ |
| D5 | **벡터 인덱스** (D4) | text-embedding-3-small + Chroma | **11/13 로컬 69,479청크 / 741MB** (장소 7,366 + 블로그 62,113 · 서울 25,249 / 인천 8,229 / 경기 36,001). 배포본은 11/11 판 63,347청크. Cloud Run 메모리 4Gi (2Gi 는 코스 생성 중 메모리 초과) | `rag_search` Tool | `data/vectorstore/` (git 제외). 배포용 `gs://odiro-where-data/vectorstore.tgz` | 1주차 ✅ · 수집분은 매일 추가 |
| D6 | **나머지 13개 시도 장소 메타 + 상세** | TourAPI `areaBasedList2` · `detailCommon2` | 메타 4~5만 건 추정(호출 100회 미만), 상세는 하루 3,000건씩 | "전국 어디를 입력해도 동작" + 지방 볼거리 설명 | `data/raw/tour/area_{시도코드}.jsonl`, `detail_{시도코드}.jsonl` | **2주차~** (`daily_ingest.py` 가 수도권이 끝나면 자동으로 넘어간다) |
| D7 | **나머지 시도 블로그 큐레이션 글** | 네이버 블로그 검색 | 163 시군구 × 테마 11 | 전국 RAG (분위기) | `data/raw/blog/area_{시도코드}.jsonl` | **2주차** (`naver_blog --all`, 예산·메모리 보고 범위 결정) |
| D8 | **나머지 시도 라벨링 + 인덱스 확장** | LLM + Chroma | 5~10만 건, 15~30달러 → **예산 보고 샘플링** | 전국 RAG 품질 | `data/vectorstore/` | 2주차 (시간 남으면), 아니면 3주차 |
| D9 | **시연 시나리오 캐시** | 완성된 파이프라인 실행 결과 | 3개 시나리오 (성수동 / 양평·가평 / 인천 송도) | 시연 안정성 (네트워크 죽어도 동작) | `cache/demo/*.json` | 3주차 |

- **지역 순서**: 서비스 목표는 전국. 서울 → 인천 → 경기 → 나머지 13개 시도 순으로 채운다. 파일명은 시도코드 기준이라 담당자가 바뀌어도 tgz 를 풀고 이어서 받으면 된다.
- **아직 없는 데이터**: TourAPI 소개 정보(`detailIntro2`: 쉬는 날·이용요금·주차·반려동물)는 수집하지 않는다. 그래서 휴무일·입장료·반려동물 동반 여부는 추정이나 안내 문구 수준이다 (HANDOVER 5-3).
- TourAPI 상세는 **사전에 전수 수집**한다 (매일 한도만큼). 양을 줄이려면 `--types` 로 쇼핑(38)을 뺀다 — 서울은 쇼핑이 4,391건으로 절반이 넘었다.
- 수집 스크립트: `odiro/data/ingest/` (`tour_api.py`, `naver_blog.py`, `labeling.py`, `build_index.py`), 하루치 묶음 실행 `scripts/daily_ingest.py`.

### 2-2. 데이터 공유 방법 (git 에 안 올라감)

- `data/raw/`, `data/vectorstore/`, `cache/` 는 `.gitignore` 되어 있음.
- 주차가 바뀔 때 두 개로 묶어 **Google Drive 공유 폴더**에 올리고 인수인계 문서에 링크를 적는다: `tar czf odiro-data-YYYYMMDD.tgz data/raw cache/ingest_state` (원본 + 수집 진행 상태, 약 30MB), `tar czf vectorstore-YYYYMMDD.tgz -C data vectorstore` (약 500MB).
- Cloud Run 컨테이너는 상태가 없으므로 벡터 DB 는 **배포 때 GCS(`gs://odiro-where-data/vectorstore.tgz`)에서 받아 이미지에 포함**한다. 로컬 인덱스를 바꾼 뒤에는 tgz 를 다시 올리고 배포해야 반영된다 (HANDOVER 3번).

### 2-3. 하지 않는 것

- 인스타그램·캐치테이블·테이블링 **직접 크롤링 금지** (약관 위반 + 차단 → 시연 불안정).
- "웨이팅 적은" 같은 정보는 블로그 텍스트에서 LLM 태그로 추출, 예약은 링크 아웃.

## 3. 분위기 태그 체계 (라벨링 기준)

`감성/조용한` · `힙한/트렌디` · `뷰맛집/일몰` · `레트로` · `자연/산책` · `실내(비오는날)` · `액티비티` · `사진맛집` · `웨이팅적은` · `아이동반` · `반려동물` · `광고성(제외용)`
