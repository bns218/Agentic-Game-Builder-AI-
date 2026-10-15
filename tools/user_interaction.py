"""
tools/user_interaction.py
──────────────────────────────────────────────────────────────────────────────
ADK tools that bridge the ClarificationAgent with the terminal user.

The ClarificationAgent runs inside a LoopAgent.  It uses these two tools to:
  1. ask_user_question  – surface a question to the user and store the answer.
  2. complete_clarification – signal that requirements are clear and exit the loop.

State keys written:
  • "qa_history"              list[{question, answer}]
  • "clarification_summary"   str (plain-text recap for downstream agents)
  • "_clarification_done"     bool (internal sentinel)

ADK LoopAgent exits when a tool sets tool_context.actions.escalate = True.
"""

from google.adk.tools.tool_context import ToolContext


# ─── Tool 1 ───────────────────────────────────────────────────────────────────

def ask_user_question(question: str, tool_context: ToolContext) -> dict:
    """
    Ask the user a single clarifying question about their game idea.

    Use this tool whenever you need information that is blocking your ability
    to plan and build the game. Do NOT ask trivial or cosmetic questions.

    Args:
        question: The specific question to ask the user.

    Returns:
        {"answer": <user's reply>}
    """
    print("\n" + "─" * 58)
    print(f"  ❓  {question}")
    answer = input("  Your answer: ").strip()
    while not answer:
        answer = input("  (Please provide an answer): ").strip()

    # Accumulate Q&A pairs in session state
    qa_history: list = tool_context.state.get("qa_history", [])
    qa_history.append({"question": question, "answer": answer})
    tool_context.state["qa_history"] = qa_history

    return {"answer": answer}


# ─── Tool 2 ───────────────────────────────────────────────────────────────────

def complete_clarification(summary: str, tool_context: ToolContext) -> dict:
    """
    Call this tool when you have gathered enough information to build the game.

    Provide a concise summary of everything you now know about the game
    (original idea + all clarifications). This summary will be passed to the
    game-planning and code-generation agents.

    Args:
        summary: Full plain-text recap of the game requirements.

    Returns:
        {"status": "done"}
    """
    tool_context.state["clarification_summary"] = summary
    tool_context.state["_clarification_done"]   = True

    # Setting escalate=True tells the LoopAgent to stop iterating.
    tool_context.actions.escalate = True

    print("\n  ✅  Clarification complete.")
    return {"status": "done", "summary_preview": summary[:120] + "…"}
