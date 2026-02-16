"""
agents/clarification_agent.py
──────────────────────────────────────────────────────────────────────────────
Phase 1: Requirements Clarification

This module exposes TWO ADK agents:

  clarification_agent  (LlmAgent)
    ┗━ The actual Gemini-powered agent that asks questions and decides when to stop.
       It reads the game idea from session state and iteratively calls:
         • ask_user_question(question)   — one at a time, never in batches
         • complete_clarification(summary) — exits the loop

  clarification_loop  (LoopAgent)
    ┗━ Wraps clarification_agent, running it repeatedly until the agent calls
       complete_clarification() which sets actions.escalate = True.
       max_iterations is a safety cap — the LLM should escalate long before.

Design rationale:
  • A LoopAgent is the natural ADK primitive for "ask until satisfied".
  • Questions are asked one at a time so the agent can react to each answer
    before deciding whether another question is needed.
  • The system prompt strongly steers toward ≤3 questions total for UX.
"""

from google.adk.agents import LlmAgent, LoopAgent
from tools.user_interaction import ask_user_question, complete_clarification


# ─── System prompt for the clarification LLM ─────────────────────────────────

CLARIFICATION_SYSTEM = """\
You are a senior game designer clarifying requirements before building a small \
HTML/CSS/JavaScript browser game.

You will receive a game idea in the first user message.  Your job is to identify \
the MINIMUM set of questions needed to implement the game correctly.

Rules:
1. Ask ONE question per turn using the ask_user_question tool.
2. Stop when you have enough information — aim for ≤3 questions total.
3. Do NOT ask about trivial details (colour palettes, font choices, exact pixel sizes).
4. Do NOT ask anything that has a sensible default you can pick yourself.
5. When requirements are sufficiently clear, call complete_clarification with a
   rich plain-text summary covering: game concept, genre, core mechanic, controls,
   win/lose conditions, difficulty, and any specific details the user mentioned.

The session state key "game_idea" contains the user's original idea.
Start by reading it, then ask your first (and possibly only) question.
"""


# ─── Inner LlmAgent ──────────────────────────────────────────────────────────

clarification_agent = LlmAgent(
    name        = "ClarificationAgent",
    model       = "gemini-2.5-flash-lite",
    instruction  = CLARIFICATION_SYSTEM,
    tools       = [ask_user_question, complete_clarification],
    description = (
        "Asks the user targeted clarifying questions about their game idea "
        "and produces a structured requirements summary."
    ),
)


# ─── Outer LoopAgent ─────────────────────────────────────────────────────────

clarification_loop = LoopAgent(
    name         = "ClarificationLoop",
    sub_agents   = [clarification_agent],
    max_iterations = 6,   # hard cap; agent should self-terminate much sooner
    description  = (
        "Runs the ClarificationAgent in a loop until it signals that "
        "requirements are clear (via actions.escalate)."
    ),
)
