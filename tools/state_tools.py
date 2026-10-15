"""
tools/state_tools.py
──────────────────────────────────────────────────────────────────────────────
ADK utility tools for reading session state.

In ADK's SequentialAgent, sub-agents share a single session.  State values
written by one agent (via tools) can be read by subsequent agents using this
tool.  This avoids relying solely on the conversation text chain, which can
truncate very large values (like a full game plan JSON).

Tools in this module:
  • read_session_state(key) → returns the value at state[key]
"""

from google.adk.tools.tool_context import ToolContext


def read_session_state(key: str, tool_context: ToolContext) -> dict:
    """
    Read a value from the shared session state.

    Use this tool to retrieve structured data written by a previous agent phase.
    Common keys:
      • "game_idea"              – the user's original game concept
      • "clarification_summary"  – plain-text requirements summary (Phase 1 output)
      • "game_plan_raw"          – JSON string of the game architecture (Phase 2 output)

    Args:
        key: The state key to read.

    Returns:
        {"key": <key>, "value": <value>} if the key exists, or
        {"key": <key>, "value": null, "error": "Key not found"} otherwise.
    """
    value = tool_context.state.get(key)
    if value is None:
        return {"key": key, "value": None, "error": "Key not found in session state"}
    return {"key": key, "value": value}
