"""
Help page: renders ``help.md`` (the file on disk is ``HELP.md``; this only
works on case-insensitive filesystems such as Windows).
"""
import streamlit as st

st.set_page_config(
    page_title="Help",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")


with open("help.md", "r", encoding="utf-8") as f:
    help_text = f.read()

st.markdown(help_text)
