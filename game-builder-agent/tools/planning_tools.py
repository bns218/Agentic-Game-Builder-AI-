"""
tools/planning_tools.py
──────────────────────────────────────────────────────────────────────────────
ADK tool called by the PlanningAgent once it has designed the game architecture.

Responsibilities:
  • Parse and validate the JSON plan.
  • Store it in session state so the ExecutionAgent can read it.
  • Persist game_plan.json to the output directory for auditability.

State keys written:
  • "game_plan"      dict  (parsed JSON)
  • "game_plan_raw"  str   (pretty-printed JSON string)
"""

import json
import os
import re
from pathlib import Path
from google.adk.tools.tool_context import ToolContext


OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))

REQUIRED_KEYS = {
    "title", "framework", "player_controls",
    "core_mechanics", "win_condition", "lose_condition", "entities",
}


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def save_game_plan(plan_json: str, tool_context: ToolContext) -> dict:
    """
    Validate and persist the structured game plan produced by the planning agent.

    Call this tool ONCE after you have designed the full game architecture.
    Pass the complete JSON game plan as a string argument.

    Args:
        plan_json: JSON string conforming to the game-plan schema described in
                   your system prompt.

    Returns:
        {"status": "saved", "title": <game title>} on success, or
        {"status": "error", "message": <description>} on validation failure.
    """
    cleaned = _strip_fences(plan_json)

    # Normalize smart quotes → regular quotes
    cleaned = cleaned.replace("“", '"').replace("”", '"')
    cleaned = cleaned.replace("’", "'")

    # Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    try:
        plan = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print("\n  🔍 RAW PLAN JSON (debug):")
        print(cleaned)
        return {"status": "error", "message": f"Invalid JSON: {exc}"}


    missing = REQUIRED_KEYS - set(plan.keys())
    if missing:
        return {
            "status": "error",
            "message": f"Plan is missing required keys: {sorted(missing)}. Please regenerate.",
        }

    # Persist to session state
    pretty = json.dumps(plan, indent=2, ensure_ascii=False)
    tool_context.state["game_plan"]     = plan
    tool_context.state["game_plan_raw"] = pretty

    # Write audit file to disk
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = OUTPUT_DIR / "game_plan.json"
    plan_path.write_text(pretty, encoding="utf-8")

    # Pretty-print summary to terminal
    fw  = plan.get("framework", "?").upper()
    ttl = plan.get("title", "Untitled")
    print(f"\n  📐  Plan saved  →  {plan_path}")
    print(f"       Title     : {ttl}")
    print(f"       Framework : {fw}")
    print(f"       Genre     : {plan.get('genre', '?')}")
    print(f"       Mechanics : {len(plan.get('core_mechanics', []))} defined")
    print(f"       Entities  : {', '.join(e['name'] for e in plan.get('entities', []))}")

    return {"status": "saved", "title": ttl, "framework": fw}
