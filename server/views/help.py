"""
Help page, in tabs: **How to use it** (``content/help.md``) and **About**
(``content/about.md``). Link to a tab with ``/help?tab=about``.
"""
import streamlit as st

from core.firmware import available_name
from ui import open_tabs, page_setup, render_markdown
from version import VERSION

page_setup("Help")
st.title("Help")
how_tab, about_tab = open_tabs({"how": "How to use it", "about": "About"})
with how_tab:
    render_markdown("help.md")
with about_tab:
    render_markdown("about.md")
    st.caption(f"Server software {VERSION} · controller software {available_name()} on offer. "
               "What changed in each version is in `CHANGELOG.md` in the project folder.")
