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
You are an expert game developer. Your ONLY job is to generate game code and \
save it to session state using the store_generated_code tool.

Steps you MUST follow exactly:
  1. Call read_session_state("game_plan_raw") to get the JSON game plan.
  2. Call read_session_state("clarification_summary") to get requirements context.
  3. Write the COMPLETE code for all three files in your head.
  4. Call store_generated_code(index_html=..., style_css=..., game_js=...) to save.

CODE RULES (breaking any rule makes the game unplayable):
  • The game must run by opening index.html directly in a browser — zero build steps.
  • Use ONLY code-drawn graphics: Canvas fillRect/arc/fillText or Phaser Graphics/Text.
    Absolutely NO external image or audio file references.
  • If framework = "phaser3" load Phaser from CDN in index.html:
      <script src="https://cdn.jsdelivr.net/npm/phaser@3/dist/phaser.min.js"></script>
  • All game logic in game.js. index.html bootstraps only. style.css handles layout.
  • Implement ALL game states: menu screen, gameplay loop, game-over / win screen.
  • Show a HUD (timer, score, lives, or equivalent) during gameplay.
  • Implement EVERY mechanic, entity, and control listed in the game plan.
  • Files must be COMPLETE — no stubs, no TODOs, no truncation.
  • Never use alert() / confirm() / prompt() — all UI drawn on canvas.
  • Add on-screen touch buttons for mobile play.

Call store_generated_code() exactly once with the full final code.
"""

generator_agent = LlmAgent(
    name          = "GeneratorAgent",
    model         = "gemini-2.5-flash-lite",
    instruction  = GENERATOR_SYSTEM,
    tools         = [read_session_state, store_generated_code],
    generate_content_config = _FORCE_ANY_TOOL,
    description   = (
        "Generates complete game code (index.html, style.css, game.js) "
        "from the game plan and stores it in session state."
    ),
)


# ─── Agent 2: WriterAgent ─────────────────────────────────────────────────────

WRITER_SYSTEM = """\
Your ONLY job is to read all three stored game code strings from session state \
and write them to disk in a single call.

Steps (follow EXACTLY, in this order — do NOT interleave reads and writes):
  1. Call read_session_state("generated_index_html") → save result locally.
  2. Call read_session_state("generated_style_css")  → save result locally.
  3. Call read_session_state("generated_game_js")    → save result locally.
  4. Call write_game_files(index_html=<value from step 1>,
                           style_css=<value from step 2>,
                           game_js=<value from step 3>)
     Pass ALL THREE values together in a SINGLE write_game_files call.
     Do NOT call write_game_files more than once.
     Do NOT call write_game_files after step 1 or step 2 — wait until step 4.
  5. After write_game_files returns {"status": "written", ...} you are DONE.
     Respond with: "Files written successfully." and STOP. Do not call any more tools.

Do not rewrite, modify, or summarise the code. Just read-all-then-write-once.
"""

writer_agent = LlmAgent(
    name          = "WriterAgent",
    model         = "gemini-2.5-flash-lite",
    instruction   = WRITER_SYSTEM,
    tools         = [read_session_state, write_game_files],
    # NOTE: Do NOT use _FORCE_ANY_TOOL (mode=ANY) here.
    # With mode=ANY the agent is forced to call a tool after EVERY response,
    # including after write_game_files succeeds — causing an infinite loop.
    # Using default AUTO mode lets the agent emit a final text reply to stop.
    description   = (
        "Reads generated code from session state and writes the three "
        "game files to disk via write_game_files()."
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
