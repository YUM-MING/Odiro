"""Phase 0 스모크 테스트: 패키지 import 와 그래프 컴파일만 확인."""


def test_import():
    import odiro

    assert odiro.__version__


def test_graph_compiles():
    from odiro.agent.graph import build_graph

    graph = build_graph()
    assert graph is not None


def test_state_models():
    from odiro.agent.state import Leg, Place

    p = Place(name="서울숲", category="관광지", lat=37.5444, lng=127.0374)
    assert p.verified is False
    leg = Leg(from_idx=0, to_idx=1, transport="walk", duration_min=12, distance_m=900)
    assert leg.estimated is False
