"""
agents/planning_agent.py
──────────────────────────────────────────────────────────────────────────────
Phase 2: Game Architecture Planning

The PlanningAgent reads the clarification summary from session state,
designs the complete game architecture, and persists it via save_game_plan().

The plan JSON is the "contract" between planning and execution:
  • Framework choice        (phaser3 vs vanilla canvas)
  • All entities with visual descriptions (code-drawn only — no image files)
  • Player controls
  • Game states (menu / playing / paused / game_over / win)
  • Core mechanics, win/lose conditions, scoring
  • Canvas dimensions
  • Technical implementation notes

The save_game_plan tool validates required keys and writes game_plan.json.
If validation fails, the tool returns an error and the agent must regenerate.
"""

from google.adk.agents import LlmAgent
from google.genai import types
from tools.planning_tools import save_game_plan
from tools.state_tools    import read_session_state


# ─── System prompt ────────────────────────────────────────────────────────────

PLANNING_SYSTEM = """\
You are a senior game architect planning a complete, self-contained browser game that will be \
implemented ENTIRELY inside a single .html file (containing HTML layout, <style> tags, and <script> tags).

Architecture & Constraints (CRITICAL):
  1. SINGLE FILE: All HTML structure, CSS styling, and JavaScript logic will live in one self-contained .html file.
  2. GRAPHICS: Use ONLY code-drawn graphics via HTML5 Canvas 2D API (fillRect, arc, path, gradients, etc.) or Phaser CDN. Do NOT reference external image files or sprite sheets.
  3. AUDIO: Synthesize retro sounds using Web Audio API (AudioContext oscillators) — zero external audio URLs!
  4. CONTROLS: Plan both keyboard controls (arrows, WASD, space) AND virtual/touch/mouse controls so the game runs seamlessly on all devices without errors.
  5. ERROR-FREE: Plan a complete game loop with start/menu screen, active play, game over/restart, score/lives HUD, and clear winning/losing conditions.

Framework choice guideline:
  • Choose "vanilla" (Canvas 2D) for arcade/puzzle/retro/action games (zero dependencies, instant execution, highest reliability).
  • Choose "phaser3" only if complex physics or particle engines are strictly needed (loaded via public CDN in the single HTML file).

Your task:
  1. Call read_session_state("clarification_summary") to get the requirements.
  2. Also call read_session_state("game_idea") for the original concept.
  3. Design the complete game architecture.
  4. Call save_game_plan() with the COMPLETE JSON plan as a string argument.

The JSON MUST follow this exact schema (all keys required):
{
  "title":               "Game title",
  "tagline":             "One-sentence hook",
  "framework":           "phaser3" | "vanilla",
  "framework_rationale": "Why you chose this framework",
  "genre":               "platformer" | "shooter" | "puzzle" | "arcade" | "other",
  "player_controls": {
    "description": "Plain-English summary",
    "keys": ["ArrowLeft", "ArrowRight", "Space", ...]
  },
  "game_states": ["menu", "playing", "paused", "game_over"],
  "entities": [
    {
      "name":        "player",
      "description": "What it does",
      "visual":      "Exact drawing description, e.g. blue 32×32 rectangle"
    }
  ],
  "core_mechanics": ["mechanic 1", "mechanic 2"],
  "win_condition":  "...",
  "lose_condition": "...",
  "scoring":        "How points are tracked (or 'none')",
  "difficulty":     "How difficulty ramps up",
  "levels_or_waves":"...",
  "canvas_size":    {"width": 800, "height": 600},
  "technical_notes": ["note 1", "note 2"]
}

Be highly specific. The execution agent will implement this plan EXACTLY — vague \
descriptions cause broken games. Prefer achievable mechanics over ambitious ones.
"""


import os

# ─── Agent ───────────────────────────────────────────────────────────────────

planning_agent = LlmAgent(
    name="PlanningAgent",
    model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    instruction=PLANNING_SYSTEM,
    tools=[read_session_state, save_game_plan],
    generate_content_config=types.GenerateContentConfig(
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY"  # FORCE tool calls
            )
        )
    ),
)