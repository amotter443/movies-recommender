"""
graph.py — LangGraph supervisor ReAct loop for Movie Night Recommender

Topology:
  [START] → supervisor → (tool calls?) → tools → supervisor → ...
                               (done?) → [END]
"""
from dotenv import load_dotenv

load_dotenv("local.env")

from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from state import RecommenderState
from tools import search_watchlist, search_watch_history, get_taste_profile, check_streaming
from prompts import build_system_prompt

# ── Model setup ──────────────────────────────────────────────────────────────
_tools = [search_watchlist, search_watch_history, get_taste_profile, check_streaming]
_model = ChatAnthropic(model="claude-sonnet-4-6", streaming=True).bind_tools(_tools)


# ── Nodes ─────────────────────────────────────────────────────────────────────
def supervisor_node(state: RecommenderState) -> dict:
    system_prompt = build_system_prompt(state)
    messages = [{"role": "system", "content": system_prompt}] + list(state["messages"])
    response = _model.invoke(messages)
    return {"messages": [response]}


# ── Edges ─────────────────────────────────────────────────────────────────────
def should_continue(state: RecommenderState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


# ── Graph construction ────────────────────────────────────────────────────────
_tool_node = ToolNode(_tools)

builder = StateGraph(RecommenderState)
builder.add_node("supervisor", supervisor_node)
builder.add_node("tools", _tool_node)
builder.set_entry_point("supervisor")
builder.add_conditional_edges("supervisor", should_continue)
builder.add_edge("tools", "supervisor")

graph = builder.compile()


# ── Quick terminal test ───────────────────────────────────────────────────────
if __name__ == "__main__":
    from langchain_core.messages import HumanMessage

    test_state: RecommenderState = {
        "messages": [HumanMessage(content="What should I watch tonight?")],
        "genre_filter": None,
        "max_runtime": None,
        "mood_hint": None,
        "streaming_filter": None,
        "taste_profile": None,
        "watchlist_results": None,
        "streaming_results": None,
    }

    print("Running graph...\n")
    for chunk in graph.stream(test_state, stream_mode="messages"):
        for msg, metadata in chunk:
            if hasattr(msg, "content") and isinstance(msg.content, str):
                print(msg.content, end="", flush=True)
    print("\n\nDone.")
