"""
app.py — Movie Night Recommender Streamlit UI

Run: streamlit run app.py
"""
import sys
import os

# Ensure project root is on sys.path so relative imports in tools/ work
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv("local.env")

import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

from tools.history_tool import compute_taste_profile_summary
from tools.enrich_watchlist import enrich_watchlist
from graph import graph
from state import RecommenderState

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Movie Night Recommender",
    page_icon="🎬",
    layout="wide",
)

# ── Status label map ──────────────────────────────────────────────────────────
_STATUS_LABELS = {
    "search_watchlist": "Searching your watchlist...",
    "get_taste_profile": "Analyzing your watch history...",
    "check_streaming": "Checking streaming availability...",
}

# ── Genre list (matching movie_data_final.csv columns) ───────────────────────
_GENRES = [
    "Any", "Action", "Adventure", "Animation", "Comedy", "Crime",
    "Documentary", "Drama", "Fantasy", "History", "Horror", "Music",
    "Mystery", "Romance", "Rom_Com", "Sci_Fi", "Thriller", "War", "Western",
]

_SERVICES = ["Any", "Max", "Hulu", "Criterion Channel", "Kanopy"]


# ── Startup: compute taste profile once ──────────────────────────────────────
@st.cache_data(show_spinner="Loading your watch history...")
def _load_taste_profile() -> dict:
    return compute_taste_profile_summary()


@st.cache_data(show_spinner="Enriching watchlist with TMDB metadata...")
def _enrich_watchlist() -> None:
    enrich_watchlist()


# ── Session state init ────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "taste_profile" not in st.session_state:
    st.session_state.taste_profile = _load_taste_profile()

_enrich_watchlist()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Filters")
    st.caption("Refine your recommendations")

    genre_filter = st.selectbox("Genre", _GENRES)
    max_runtime = st.slider("Max runtime (min)", min_value=60, max_value=240, value=180, step=5)
    mood_hint = st.text_input("Mood / vibe", placeholder="slow burn, uplifting, cerebral...")
    streaming_filter = st.selectbox("Service", _SERVICES)

    st.divider()

    # Quick taste profile snapshot
    profile = st.session_state.taste_profile
    if profile:
        st.subheader("Your Taste Profile")
        st.caption(f"{profile.get('total_films_watched', '?')} films watched")
        top = profile.get("top_genres", [])
        if top:
            st.markdown("**Top genres:** " + ", ".join(top[:3]))
        decade_prefs = profile.get("decade_preferences", {})
        if decade_prefs:
            best_decade = max(decade_prefs, key=lambda d: decade_prefs[d])
            st.markdown(f"**Favorite decade:** {best_decade}s")
        rt = profile.get("runtime_median_minutes")
        if rt:
            st.markdown(f"**Typical runtime:** ~{rt} min")

    st.divider()
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()


# ── Main chat area ────────────────────────────────────────────────────────────
st.title("Movie Night Recommender")
st.caption("Ask what to watch tonight. The agent searches your watchlist, checks your taste, and finds what's streaming.")

# Render chat history
for msg in st.session_state.messages:
    role = "user" if isinstance(msg, HumanMessage) else "assistant"
    with st.chat_message(role):
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        st.markdown(content)

# Chat input
if user_input := st.chat_input("What should I watch tonight?"):
    # Display user message
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append(HumanMessage(content=user_input))

    # Build state
    state: RecommenderState = {
        "messages": st.session_state.messages,
        "genre_filter": genre_filter if genre_filter != "Any" else None,
        "max_runtime": max_runtime if max_runtime < 240 else None,
        "mood_hint": mood_hint.strip() or None,
        "streaming_filter": streaming_filter if streaming_filter != "Any" else None,
        "taste_profile": st.session_state.taste_profile,
        "watchlist_results": None,
        "streaming_results": None,
    }

    # Stream response
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""
        active_tool = None

        status_container = st.status("Thinking...", expanded=False)

        tools_were_called = False
        try:
            for chunk in graph.stream(state, stream_mode="messages"):
                # chunk is a tuple: (message_chunk, metadata)
                if not isinstance(chunk, tuple):
                    continue
                msg_chunk, metadata = chunk

                # Detect tool call starts from metadata or message content
                node = metadata.get("langgraph_node", "")

                if node == "tools":
                    # We're in the tool execution phase
                    tools_were_called = True
                    if hasattr(msg_chunk, "name") and msg_chunk.name in _STATUS_LABELS:
                        label = _STATUS_LABELS[msg_chunk.name]
                        status_container.update(label=label, state="running")

                elif node == "supervisor":
                    # Check if this is a tool-call message (no text to stream yet)
                    if hasattr(msg_chunk, "tool_calls") and msg_chunk.tool_calls:
                        tools_called = [tc["name"] for tc in msg_chunk.tool_calls]
                        labels = [_STATUS_LABELS.get(t, t) for t in tools_called]
                        status_container.update(label=" + ".join(labels), state="running")

                    # Stream text content
                    if hasattr(msg_chunk, "content"):
                        content = msg_chunk.content
                        if isinstance(content, str) and content:
                            if tools_were_called and full_response and not full_response[-1].isspace():
                                full_response += "\n\n"
                                tools_were_called = False
                            full_response += content
                            response_placeholder.markdown(full_response + "▌")
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "")
                                    if text:
                                        if tools_were_called and full_response and not full_response[-1].isspace():
                                            full_response += "\n\n"
                                            tools_were_called = False
                                        full_response += text
                                        response_placeholder.markdown(full_response + "▌")

        except Exception as e:
            full_response = f"Sorry, something went wrong: {str(e)}"

        status_container.update(label="Done", state="complete", expanded=False)
        response_placeholder.markdown(full_response)

        if full_response:
            st.session_state.messages.append(AIMessage(content=full_response))
