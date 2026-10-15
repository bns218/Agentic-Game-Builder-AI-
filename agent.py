#!/usr/bin/env python3
"""
agent.py  –  Agentic Game-Builder AI (Google ADK Edition)
══════════════════════════════════════════════════════════
Entry point that wires together the three ADK agents into a SequentialAgent
pipeline and drives it with a single Runner.

ADK agent graph:

    SequentialAgent: GameBuilderPipeline
    ├── LoopAgent:       ClarificationLoop
    │   └── LlmAgent:   ClarificationAgent  (tools: ask_user_question, complete_clarification)
    ├── LlmAgent:        PlanningAgent       (tools: read_session_state, save_game_plan)
    └── SequentialAgent: ExecutionAgent
        ├── LlmAgent:   GeneratorAgent      (tools: read_session_state, store_generated_code)
        └── LlmAgent:   WriterAgent         (tools: read_session_state, write_game_files)

BUG FIX (v2):
  The original ExecutionAgent emitted code as text instead of calling write_game_files().
  Fixed by splitting Phase 3 into GeneratorAgent + WriterAgent, applying
  generate_content_config(tool_config mode=ANY) to force function calls,
  and adding a fallback extractor in handle_event() as belt-and-suspenders.
"""

import asyncio
import os
import re
import sys
import time
from pathlib import Path

# Fix Windows console UTF-8 output encoding for emojis and unicode banners
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── ADK imports ────────────────────────────────────────────────────────────────
from google.adk.agents   import SequentialAgent
from google.adk.runners  import Runner
from google.adk.sessions import InMemorySessionService
from google.genai        import types

# ── Our agents ─────────────────────────────────────────────────────────────────
from agents.clarification_agent import clarification_loop
from agents.planning_agent      import planning_agent
from agents.execution_agent     import execution_agent


# ─── Constants ────────────────────────────────────────────────────────────────

APP_NAME = "game-builder-agent"
USER_ID  = "player-one"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./output")).resolve()

BANNER = r"""
  ╔════════════════════════════════════════════════════════════╗
  ║     🎮  Agentic Game-Builder AI  –  Powered by Gemini ADK  ║
  ║     Clarify  →  Plan  →  Generate  →  Play                 ║
  ║          (All-in-one Single .html Playable Game)           ║
  ╚════════════════════════════════════════════════════════════╝
"""

PHASE_LABELS = {
    "ClarificationLoop":    "Phase 1 · Requirements Clarification",
    "ClarificationAgent":   "Phase 1 · Requirements Clarification",
    "PlanningAgent":        "Phase 2 · Game Architecture Planning",
    "ExecutionAgent":       "Phase 3 · Code Generation",
    "GeneratorAgent":       "Phase 3a · Generating Single-File HTML Game",
    "WriterAgent":          "Phase 3b · Writing index.html to Disk",
    "GameBuilderPipeline":  "Pipeline",
}


# ─── Fallback extractor ───────────────────────────────────────────────────────
# Belt-and-suspenders: if WriterAgent or GeneratorAgent emits code as raw text,
# extract and save index.html automatically.

_FALLBACK_TRIGGERED = False

def _try_fallback_write(text: str) -> bool:
    """
    Attempt to extract a single standalone game HTML file from raw text response.
    Returns True if files were written, False otherwise.
    """
    global _FALLBACK_TRIGGERED
    if _FALLBACK_TRIGGERED:
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Full HTML doc match
    html_match = re.search(
        r"(?:```html\s*)?(<!DOCTYPE html>.*?</html>)(?:\s*```)?",
        text, re.DOTALL | re.IGNORECASE
    )
    if html_match:
        content = html_match.group(1).strip()
        (OUTPUT_DIR / "index.html").write_text(content, encoding="utf-8")
        _FALLBACK_TRIGGERED = True
        print(f"\n  ⚠️  FALLBACK: extracted and wrote index.html from text response ({len(content)} bytes)")
        return True

    # 2. Extract parts if separately fenced
    css_match = re.search(r"```css\s*(.*?)```", text, re.DOTALL)
    js_match = re.search(r"```(?:javascript|js)\s*(.*?)```", text, re.DOTALL)
    body_match = re.search(r"```html\s*(.*?)```", text, re.DOTALL)

    css_code = css_match.group(1).strip() if css_match else ""
    js_code = js_match.group(1).strip() if js_match else ""
    body_code = body_match.group(1).strip() if body_match else ""

    if js_code or body_code:
        bundled = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Playable Game</title>
  <style>
    {css_code}
  </style>
</head>
<body>
  {body_code}
  <script>
    {js_code}
  </script>
</body>
</html>"""
        (OUTPUT_DIR / "index.html").write_text(bundled, encoding="utf-8")
        _FALLBACK_TRIGGERED = True
        print(f"\n  ⚠️  FALLBACK: bundled code into index.html ({len(bundled)} bytes)")
        return True

    return False


# ─── Event handler ────────────────────────────────────────────────────────────

_last_author: str | None = None


def handle_event(event) -> None:
    """Pretty-print ADK runner events and run fallback extractor on code output."""
    global _last_author

    author = getattr(event, "author", None) or "Agent"
    label  = PHASE_LABELS.get(author)

    if label and author != _last_author:
        print(f"\n{'═' * 60}")
        print(f"  🔄  {label}")
        print(f"{'═' * 60}")
        _last_author = author

    if not event.content or not event.content.parts:
        return

    for part in event.content.parts:
        if hasattr(part, "function_call") and part.function_call:
            fn = part.function_call
            args_preview = str(fn.args)[:90] if fn.args else ""
            print(f"  🔧  [{author}] → {fn.name}({args_preview}…)")

        if hasattr(part, "function_response") and part.function_response:
            fr  = part.function_response
            res = str(fr.response)[:90] if fr.response else ""
            print(f"  ↩️   [{author}] ← {res}…")

    if event.is_final_response():
        text = "".join(
            p.text for p in event.content.parts
            if hasattr(p, "text") and p.text
        ).strip()

        if text:
            # Run fallback extractor if this looks like code output
            if "<!DOCTYPE" in text or "```html" in text:
                _try_fallback_write(text)
            else:
                preview = text[:200] + ("…" if len(text) > 200 else "")
                print(f"\n  💬  [{author}] {preview}")


# ─── Core async runner ────────────────────────────────────────────────────────

async def run_pipeline(game_idea: str) -> None:
    print(BANNER)

    pipeline        = SequentialAgent(
        name        = "GameBuilderPipeline",
        sub_agents  = [clarification_loop, planning_agent, execution_agent],
        description = "End-to-end game builder: clarify → plan → generate.",
    )
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name = APP_NAME,
        user_id  = USER_ID,
        state    = {"game_idea": game_idea},
    )
    runner = Runner(
        agent           = pipeline,
        app_name        = APP_NAME,
        session_service = session_service,
    )

    initial_message = types.Content(
        role  = "user",
        parts = [types.Part(text=(
            f"Build me a game based on this idea: {game_idea}\n\n"
            "Follow all three phases: clarify requirements, plan the architecture, "
            "then generate the complete playable game files."
        ))],
    )

    print(f"  💡  Game idea: {game_idea}\n")
    start = time.time()

    async for event in runner.run_async(
        user_id     = USER_ID,
        session_id  = session.id,
        new_message = initial_message,
    ):
        handle_event(event)

    elapsed = time.time() - start

    # ── Completion check ──────────────────────────────────────────────────────
    final_session = await session_service.get_session(
        app_name   = APP_NAME,
        user_id    = USER_ID,
        session_id = session.id,
    )
    state      = final_session.state if final_session else {}
    game_plan  = state.get("game_plan", {})

    # Success = tool wrote index.html OR fallback extracted it
    index_exists = (OUTPUT_DIR / "index.html").exists()
    success = state.get("execution_done") or _FALLBACK_TRIGGERED or index_exists

    print("\n" + "═" * 60)
    print("  🚀  BUILD COMPLETE" if success else "  ⚠️  BUILD INCOMPLETE")
    print("═" * 60)

    if success:
        file_size_kb = round((OUTPUT_DIR / "index.html").stat().st_size / 1024, 1) if index_exists else 0
        print(f"""
  Game title : {game_plan.get('title', 'Playable Browser Game')}
  Framework  : {game_plan.get('framework', 'vanilla').upper()}
  File       : {OUTPUT_DIR / 'index.html'} ({file_size_kb} KB)
  Format     : Single self-contained .html (HTML + CSS + JS)
  Time taken : {elapsed:.1f}s

  ▶  To play: open {OUTPUT_DIR}/index.html in your browser!
        """)
    else:
        print(f"\n  State keys: {list(state.keys())}")
        print(f"  index.html exists: {index_exists}")
        print("  Try running again or check the output directory manually.")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    # Check if user wants to launch the interactive live-coding web interface
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["--web", "web", "-w"]:
        import uvicorn
        port = int(os.environ.get("PORT", "8000"))
        print("\n" + BANNER)
        print(f"  🌐  Launching Web UI with Live Coding & Live Game Preview...")
        print(f"  👉  Open in browser: http://localhost:{port}\n")
        uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
        return

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "\n  ❌  ERROR: Gemini API key not found.\n"
            "  Set GEMINI_API_KEY:\n\n"
            "    $env:GEMINI_API_KEY=\"AIza...\"\n"
            "    export GEMINI_API_KEY=AIza...\n"
            "  Or launch the web interface to enter it in browser:\n"
            "    python agent.py --web\n"
        )
        sys.exit(1)

    if len(sys.argv) > 1:
        game_idea = " ".join(sys.argv[1:]).strip()
    else:
        print(BANNER)
        print("  Describe the game you want to build (or run with --web for the Web UI).\n")
        game_idea = input("  Your idea: ").strip()
        while not game_idea:
            game_idea = input("  (Please describe a game): ").strip()

    try:
        asyncio.run(run_pipeline(game_idea))
    except KeyboardInterrupt:
        print("\n\n  Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        print(f"\n  ❌  Fatal error: {exc}")
        raise


if __name__ == "__main__":
    main()
