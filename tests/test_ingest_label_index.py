"""labeling / build_index / rag_search 의 순수 함수 테스트 (LLM·Chroma 호출 없음)."""

from odiro.data.ingest.build_index import TAG_KEYS, doc_metadata, split_text, to_chunks
from odiro.data.ingest.labeling import BatchLabels, DocLabel, apply_labels, format_batch
from odiro.data.ingest.regions import MOOD_TAGS
from odiro.tools.rag_search import build_filter

PLACE = {
    "doc_id": "place:126508",
    "doc_type": "place",
    "title": "경복궁",
    "text": "조선의 법궁. " * 60,  # 약 480자
    "url": "https://royal.khs.go.kr/",
    "sido_code": "11",
    "sigungu_code": "110",
    "sigungu": "",
    "content_id": "126508",
    "content_type": "관광지",
    "addr": "서울특별시 종로구 사직로 161",
    "lat": 37.5788,
    "lng": 126.977,
    "image": "",
}
BLOG = {
    "doc_id": "blog:https://blog.naver.com/a/1",
    "doc_type": "blog",
    "title": "성수동 조용한 카페",
    "text": "주말 오후에 다녀왔는데 사람이 적고 분위기가 차분했어요. 협찬 아니고 내돈내산.",
    "url": "https://blog.naver.com/a/1",
    "sido_code": "11",
    "sigungu_code": "200",
    "sigungu": "성동구",
    "postdate": "20261001",
    "themes": ["감성/조용한"],
    "ad_suspect": True,  # 1차 필터는 '협찬' 단어 때문에 의심 표시
}


def test_tag_keys_cover_all_mood_tags_except_ad():
    assert set(TAG_KEYS) == set(MOOD_TAGS) - {"광고성(제외용)"}


def test_format_batch_numbers_docs():
    s = format_batch([PLACE, BLOG])
    assert s.startswith("[0] (장소) 경복궁")
    assert "[1] (블로그) 성수동 조용한 카페 (검색 테마: 감성/조용한)" in s


def test_apply_labels_merges_and_fills_missing():
    result = BatchLabels(
        labels=[
            DocLabel(idx=1, tags=["감성/조용한", "웨이팅적은", "감성/조용한"], is_ad=False, one_line="차분한 동네 카페"),
            DocLabel(idx=7, tags=[], is_ad=False, one_line="범위 밖"),
        ]
    )
    rows = apply_labels([PLACE, BLOG], result)
    assert rows[0]["labeled"] is False and rows[0]["tags"] == []
    assert rows[1]["labeled"] is True
    assert rows[1]["tags"] == ["감성/조용한", "웨이팅적은"]  # 중복 제거
    # LLM 이 광고 아니라고 해도 1차 의심 플래그는 보존 (보수적으로)
    assert rows[1]["is_ad"] is True


def test_split_text_respects_size_and_sentences():
    text = ("문장입니다. " * 200).strip()
    chunks = split_text(text, size=300, overlap=30)
    assert len(chunks) > 1
    assert all(len(c) <= 320 for c in chunks)
    assert chunks[0].endswith(".")


def test_split_text_short_is_single_chunk():
    assert split_text("짧은 글") == ["짧은 글"]
    assert split_text("   ") == []


def test_doc_metadata_place_and_tag_flags():
    md = doc_metadata({**PLACE, "tags": ["레트로", "사진맛집"], "is_ad": False, "one_line": "고궁"})
    assert md["t_retro"] is True and md["t_photo"] is True and md["t_calm"] is False
    assert md["tags"] == "레트로|사진맛집"
    assert md["lat"] == 37.5788 and md["content_type"] == "관광지"
    assert all(isinstance(v, (str, int, float, bool)) for v in md.values())


def test_to_chunks_blog_single_place_multi():
    b = to_chunks({**BLOG, "tags": [], "is_ad": False, "one_line": "조용"})
    assert len(b) == 1 and b[0][0].endswith("#0") and b[0][1].startswith("성수동 조용한 카페\n")
    p = to_chunks({**PLACE, "text": "가나다. " * 400, "tags": [], "is_ad": False, "one_line": ""})
    assert len(p) >= 3 and p[1][2]["chunk"] == 1


def test_build_filter_region_only():
    assert build_filter(None, "서울") == {"sido_code": "11"}
    assert build_filter([], "경기도 어딘가") == {"sido_code": "41"}


def test_build_filter_moods_and_region():
    f = build_filter(["감성/조용한", "뷰맛집/일몰"], "인천")
    assert f == {"$and": [{"sido_code": "28"}, {"$or": [{"t_calm": True}, {"t_view": True}]}]}


def test_build_filter_unknown_region_and_tag():
    assert build_filter(["없는태그"], None) is None  # 모르는 태그는 무시
    assert build_filter(None, None) is None
