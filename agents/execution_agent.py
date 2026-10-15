"""
agents/execution_agent.py
──────────────────────────────────────────────────────────────────────────────
Phase 3: Code Generation

ROOT CAUSE OF ORIGINAL BUG (v1)
─────────────────────────────────
The original single ExecutionAgent was asked to both generate code AND call a
tool in the same turn.  Gemini defaults to returning text when it perceives its
primary job as "writing code", treating the tool call as optional.

v2 FIX — split generate / write into two agents
─────────────────────────────────────────────────
  GeneratorAgent  – reads the plan, generates code, stores it in session
                    state via store_generated_code() tool.  Uses mode=ANY to
                    guarantee a tool call (the only output is stored code).
  WriterAgent     – reads the three code strings from state and writes to disk
                    via write_game_files().

CRITICAL: WriterAgent must NOT use mode=ANY (generate_content_config with
tool_config mode=ANY).  Reason: after write_game_files() succeeds, mode=ANY
forces the agent to call ANOTHER tool, creating an infinite loop that re-reads
state and re-writes the files endlessly (observed in original run: 15+ writes).
WriterAgent uses default AUTO mode so it can emit a final text response to stop.

ADDITIONAL GUARD: write_game_files() returns {"status": "already_written"} if
execution_done is already True in state, providing a belt-and-suspenders stop.

3. ORCHESTRATOR FALLBACK: agent.py contains a regex fallback extractor
   that catches any remaining text-only code output.
"""

import os
from google.adk.agents import LlmAgent, SequentialAgent
from google.genai       import types

from tools.execution_tools import write_game_files, store_generated_code
from tools.state_tools     import read_session_state


# ─── Forced tool-use config ───────────────────────────────────────────────────

_FORCE_ANY_TOOL = types.GenerateContentConfig(
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode="ANY",   # Model MUST call a tool; cannot emit text-only response
        )
    )
)


# ─── Agent 1: GeneratorAgent ──────────────────────────────────────────────────

GENERATOR_SYSTEM = """\
You are an expert game developer. Your ONLY job is to generate the complete game code and \
save it to session state using the store_generated_code tool.

CRITICAL REQUIREMENT:
Write EVERYTHING into a single, self-contained .html file (HTML layout, CSS inside <style>, \
and all JavaScript game logic inside <script>). Zero separate .css or .js files!

Steps you MUST follow exactly:
  1. Call read_session_state("game_plan_raw") to get the JSON game plan.
  2. Call read_session_state("clarification_summary") to get requirements context.
  3. Write the COMPLETE, fully working code for the single .html file.
  4. Call store_generated_code(game_html=...) to save.

CODE RULES FOR ERROR-FREE, TOTAL PLAYABLE GAME:
  • SINGLE STANDALONE FILE: The output must run immediately when opened in any browser or iframe.
  • ZERO EXTERNAL ASSETS:
    - Graphics: Draw all characters, obstacles, backgrounds, and particles directly with HTML5 Canvas 2D context (fillRect, arc, beginPath, fillText, createLinearGradient) or Phaser CDN. Never use local image files or external image URLs.
    - Sound: Use the browser Web Audio API (new (window.AudioContext || window.webkitAudioContext)()) with synthetic oscillators for retro bleeps/explosions/powerup sounds. Zero audio file dependencies!
  • INPUT CONTROLS:
    - Listen for Keyboard: Arrow keys, WASD, Space, etc.
    - Include on-screen touch/mouse buttons (or virtual d-pad) so mobile/mouse players can play flawlessly without a keyboard.
  • GAME STATES:
    - Menu / Title screen (instructions + "Click or Press Space to Start").
    - Active gameplay loop (powered by requestAnimationFrame with delta time).
    - Game Over & Victory screens with final score and a prominent "Play Again / Restart" button.
    - Live HUD showing Score, Lives / Health bar, Level / Wave, and High Score.
  • COMPLETE & ERROR-FREE:
    - Never write truncated code, stubs, or comments like '// implement here'.
    - Wrap the game bootstrap inside window.addEventListener('DOMContentLoaded', ...) or window.onload.
    - Include a lightweight window.onerror safety net that displays errors on the canvas if anything fails.
    - Clean, modern, arcade CSS styling (dark themed or retro neon background, centered responsive canvas).

Call store_generated_code(game_html=...) exactly once with the complete, self-contained HTML code.
"""

generator_agent = LlmAgent(
    name          = "GeneratorAgent",
    model         = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    instruction  = GENERATOR_SYSTEM,
    tools         = [read_session_state, store_generated_code],
    generate_content_config = _FORCE_ANY_TOOL,
    description   = (
        "Generates a complete, single-file playable game HTML (including <style> and <script>) "
        "and stores it in session state."
    ),
)


# ─── Agent 2: WriterAgent ─────────────────────────────────────────────────────

WRITER_SYSTEM = """\
Your ONLY job is to read the stored game HTML from session state and write it to disk.

Steps (follow EXACTLY):
  1. Call read_session_state("generated_game_html") → get the full HTML string.
  2. Call write_game_files(game_html=<value from step 1>)
     Pass the full HTML in a SINGLE write_game_files call.
     Do NOT call write_game_files more than once.
  3. After write_game_files returns {"status": "written", ...} you are DONE.
     Respond with: "Game HTML written successfully." and STOP. Do not call any more tools.

Do not rewrite, modify, or summarise the code. Just read-and-write.
"""

writer_agent = LlmAgent(
    name          = "WriterAgent",
    model         = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    instruction   = WRITER_SYSTEM,
    tools         = [read_session_state, write_game_files],
    description   = (
        "Reads generated game HTML from session state and writes index.html "
        "to disk via write_game_files()."
    ),
)


# ─── Composed execution pipeline ──────────────────────────────────────────────

execution_agent = SequentialAgent(
    name       = "ExecutionAgent",
    sub_agents = [generator_agent, writer_agent],
    description = (
        "Phase 3 pipeline: GeneratorAgent produces code into state; "
        "WriterAgent reads state and writes files to disk."
    ),
)
