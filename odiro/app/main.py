"""Odiro Streamlit 진입점. 실행: streamlit run odiro/app/main.py

Phase 0: 환경 점검 화면만. Phase 3 에서 조건 빌더 + 채팅 + 지도 스플릿 뷰로 교체.
"""

import streamlit as st

from odiro.config import settings

st.set_page_config(page_title="Odiro - 어디로 갈까요?", page_icon="🗺️", layout="wide")

st.title("🗺️ Odiro")
st.caption("어디로 갈까요? 묻기만 하세요. 길까지 Odiro가 짭니다.")

missing = settings.missing_keys()
if missing:
    st.warning("아직 비어 있는 API 키: " + ", ".join(missing))
else:
    st.success("모든 API 키가 설정되어 있습니다.")

st.info("Phase 0 세팅 화면입니다. `python scripts/check_apis.py` 로 각 API 호출을 점검하세요.")
