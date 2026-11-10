"""수집 → 라벨링 → 인덱스 파이프라인 (Phase 1). 전부 `python -m odiro.data.ingest.<모듈>` 로 실행, 재실행 안전.

- regions.py     : 법정동 시도코드·콘텐츠타입·태그 체계 상수, --area/--all 해석
- common.py      : JSONL 입출력, 재시도 HTTP(get_json), 일일 한도 카운터(DailyQuota), 로깅
- tour_api.py    : TourAPI 4.0 메타(areaBasedList2) + 상세(detailCommon2) 수집 → data/raw/tour/
- naver_blog.py  : 네이버 블로그 검색(NCP API HUB) 시군구 × 테마 수집 → data/raw/blog/
- labeling.py    : gpt-4o-mini Structured Output 분위기 태그 라벨링 → data/raw/labeled/
- build_index.py : Chroma 적재 (OpenAI 임베딩) → data/vectorstore/   (검색은 odiro/tools/rag_search.py)
"""
