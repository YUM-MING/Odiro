"""LangGraph 그래프 조립. Phase 2 에서 노드 구현.

parse_intent -> retrieve(RAG ∥ web) -> draft_course -> verify_places
    -> optimize_route -> enrich -> compose_answer
modify_node -> verify_places (수정 플라이휠)
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from odiro.agent.state import CourseState


def build_graph():
    g = StateGraph(CourseState)

    # TODO(Phase 2): 노드 구현 후 교체
    g.add_node("parse_intent", lambda s: s)
    g.add_node("retrieve", lambda s: s)
    g.add_node("draft_course", lambda s: s)
    g.add_node("verify_places", lambda s: s)
    g.add_node("optimize_route", lambda s: s)
    g.add_node("enrich", lambda s: s)
    g.add_node("compose_answer", lambda s: s)

    g.set_entry_point("parse_intent")
    g.add_edge("parse_intent", "retrieve")
    g.add_edge("retrieve", "draft_course")
    g.add_edge("draft_course", "verify_places")
    g.add_edge("verify_places", "optimize_route")
    g.add_edge("optimize_route", "enrich")
    g.add_edge("enrich", "compose_answer")
    g.add_edge("compose_answer", END)

    return g.compile()


if __name__ == "__main__":
    graph = build_graph()
    print(graph.get_graph().draw_mermaid())
