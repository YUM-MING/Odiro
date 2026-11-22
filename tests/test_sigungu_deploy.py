"""배포 서버 조건(cache/ingest_state 없음)에서 git 추적 시군구 파일(data/sigungu)만으로 지역 해석이 되는지."""

from __future__ import annotations

import pytest

from odiro.agent import nodes
from odiro.tools import rag_search


@pytest.fixture
def deploy_like(monkeypatch, tmp_path):
    """STATE_DIR 을 빈 폴더로 바꿔 배포 서버처럼 만든다. data/sigungu 는 실제 저장소 파일을 쓴다."""
    monkeypatch.setattr(rag_search, "STATE_DIR", tmp_path)
    rag_search._sigungu_table.cache_clear()
    yield
    rag_search._sigungu_table.cache_clear()  # 캐시를 비워 두면 monkeypatch 원복 뒤 다음 호출이 실제 경로로 다시 읽는다


def test_sigungu_files_tracked_for_capital_area():
    for code in ("11", "28", "41"):
        assert (rag_search.SIGUNGU_DIR / f"sigungu_{code}.json").exists()


def test_gapyeong_resolves_without_state_dir(deploy_like):
    assert rag_search.resolve_region("가평") == {"sido_code": "41", "sigungu_code": "820"}  # 가평군


def test_suwon_hwaseong_resolves_to_suwon(deploy_like):
    assert rag_search.resolve_region("수원 화성") == {"sido_code": "41", "sigungu_code": "110"}  # 수원시


def test_existing_behavior_kept(deploy_like):
    assert rag_search.resolve_region("인천 송도") == {"sido_code": "28"}
    assert rag_search.resolve_region("성수동") == {}


def test_car_radius_is_wide_for_gapyeong(deploy_like):
    assert nodes._radius_key({"transport": "car", "region": "가평"}) == "car_wide"


def test_state_dir_only_fills_missing(monkeypatch, tmp_path):
    """data/sigungu 가 우선이고, STATE_DIR 은 빠진 (시도, 시군구) 만 보탠다."""
    tracked, state = tmp_path / "tracked", tmp_path / "state"
    tracked.mkdir()
    state.mkdir()
    (tracked / "sigungu_41.json").write_text('[{"code": "820", "name": "가평군"}]', encoding="utf-8")
    (state / "sigungu_41.json").write_text(
        '[{"code": "820", "name": "다른이름"}, {"code": "830", "name": "양평군"}]', encoding="utf-8"
    )
    monkeypatch.setattr(rag_search, "SIGUNGU_DIR", tracked)
    monkeypatch.setattr(rag_search, "STATE_DIR", state)
    rag_search._sigungu_table.cache_clear()
    try:
        assert rag_search._sigungu_table() == [("41", "820", "가평군"), ("41", "830", "양평군")]
    finally:
        rag_search._sigungu_table.cache_clear()
