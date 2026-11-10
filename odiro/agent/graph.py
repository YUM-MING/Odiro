"""LangGraph 그래프 조립.

생성:  parse_intent → retrieve → draft_course → verify_places → optimize_route → enrich → compose_answer → END
수정:  modify → (전체 재구성이면 draft_course 로) / verify_places → optimize_route → enrich → compose_answer → END

verify_places 안에서 LLM 보충 루프(최대 2회)를 돌기 때문에 그래프 차원의 되돌아가기 엣지는 하나(수정→초안)만 있다.
`python -m odiro.agent.graph` 로 Mermaid 다이어그램 출력 (발표 자료용).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from odiro.agent import nodes
from odiro.agent.state import CourseState

MAIN_SEQUENCE = ("parse_intent", "retrieve", "draft_course", "verify_places", "optimize_route", "enrich", "compose_answer")
EDIT_SEQUENCE = ("modify", "verify_places", "optimize_route", "enrich", "compose_answer")


def build_graph():
    g = StateGraph(CourseState)
    g.add_node("parse_intent", nodes.parse_intent)
    g.add_node("retrieve", nodes.retrieve)
    g.add_node("draft_course", nodes.draft_course)
    g.add_node("verify_places", nodes.verify_places)
    g.add_node("optimize_route", nodes.optimize_route)
    g.add_node("enrich", nodes.enrich)
    g.add_node("compose_answer", nodes.compose_answer)

    g.set_entry_point("parse_intent")
    g.add_edge("parse_intent", "retrieve")
    g.add_edge("retrieve", "draft_course")
    g.add_edge("draft_course", "verify_places")
    g.add_edge("verify_places", "optimize_route")
    g.add_edge("optimize_route", "enrich")
    g.add_edge("enrich", "compose_answer")
    g.add_edge("compose_answer", END)
    return g.compile()


def build_edit_graph():
    g = StateGraph(CourseState)
    g.add_node("modify", nodes.modify)
    g.add_node("draft_course", nodes.draft_course)
    g.add_node("verify_places", nodes.verify_places)
    g.add_node("optimize_route", nodes.optimize_route)
    g.add_node("enrich", nodes.enrich)
    g.add_node("compose_answer", nodes.compose_answer)

    g.set_entry_point("modify")
    g.add_conditional_edges(
        "modify",
        lambda s: "draft_course" if s.get("full_redraft") else "verify_places",
        {"draft_course": "draft_course", "verify_places": "verify_places"},
    )
    g.add_edge("draft_course", "verify_places")
    g.add_edge("verify_places", "optimize_route")
    g.add_edge("optimize_route", "enrich")
    g.add_edge("enrich", "compose_answer")
    g.add_edge("compose_answer", END)
    return g.compile()


if __name__ == "__main__":
    print(build_graph().get_graph().draw_mermaid())
    print()
    print(build_edit_graph().get_graph().draw_mermaid())
