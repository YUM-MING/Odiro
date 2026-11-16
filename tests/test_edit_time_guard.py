"""수정 요청의 시각 표현 판별 (LLM 이 시작 시각을 임의로 채우는 것을 막는 가드)."""

import pytest

from odiro.agent.nodes import _mentions_clock_time


@pytest.mark.parametrize("text", ["첫째날 9시에 시작", "둘째날은 10시부터", "09:30 출발", "첫째날 아홉 시 시작", "열시로", "정오에 시작"])
def test_mentions_clock_time(text):
    assert _mentions_clock_time(text)


@pytest.mark.parametrize("text", ["3번째 카페 바꿔줘", "더 조용한 곳으로", "마지막 장소를 실내로", "", "시작은 그대로 두고 식당만 바꿔줘"])
def test_no_clock_time(text):
    assert not _mentions_clock_time(text)
