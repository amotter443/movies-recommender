from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


class RecommenderState(TypedDict):
    messages: Annotated[list, add_messages]   # full chat + tool messages
    genre_filter: Optional[str]               # from sidebar
    max_runtime: Optional[int]                # from sidebar (minutes)
    mood_hint: Optional[str]                  # from sidebar text input
    streaming_filter: Optional[str]           # from sidebar ("Max", "Hulu", etc.)
    taste_profile: Optional[dict]             # pre-computed at startup
    watchlist_results: Optional[list]         # populated by watchlist_tool
    streaming_results: Optional[list]         # populated by streaming_tool
