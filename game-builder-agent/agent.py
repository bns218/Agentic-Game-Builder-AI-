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
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))

BANNER = r"""
  ╔════════════════════════════════════════════════════════════╗
  ║     🎮  Agentic Game-Builder AI  –  Powered by Gemini ADK  ║
  ║     Clarify  →  Plan  →  Generate  →  Play                 ║
  ╚════════════════════════════════════════════════════════════╝
"""

PHASE_LABELS = {
    "ClarificationLoop":    "Phase 1 · Requirements Clarification",
    "ClarificationAgent":   "Phase 1 · Requirements Clarification",
    "PlanningAgent":        "Phase 2 · Game Architecture Planning",
    "ExecutionAgent":       "Phase 3 · Code Generation",
    "GeneratorAgent":       "Phase 3a · Generating Code",
    "WriterAgent":          "Phase 3b · Writing Files to Disk",
    "GameBuilderPipeline":  "Pipeline",
}


# ─── Fallback extractor ───────────────────────────────────────────────────────
# Belt-and-suspenders: if WriterAgent or GeneratorAgent somehow emits code as
# text instead of calling a tool, extract and write the files ourselves.

_FALLBACK_TRIGGERED = False

def _try_fallback_write(text: str) -> bool:
    """
    Attempt to extract game files from a raw text response.
    Returns True if files were written, False otherwise.
    """
    global _FALLBACK_TRIGGERED
    if _FALLBACK_TRIGGERED:
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = {}

    # Look for HTML
    html_match = re.search(
        r"(?:```html\s*)?(<!DOCTYPE html>.*?)</(?:html)>(?:\s*```)?",
        text, re.DOTALL | re.IGNORECASE
    )
    if html_match:
        content = html_match.group(0)
        content = re.sub(r"^```html\s*", "", content).rstrip("`").strip()
        (OUTPUT_DIR / "index.html").write_text(content, encoding="utf-8")
        written["index.html"] = True

    # Look for CSS (between ```css fences or after a css comment block)
    css_match = re.search(r"```css\s*(.*?)```", text, re.DOTALL)
    if css_match:
        (OUTPUT_DIR / "style.css").write_text(css_match.group(1).strip(), encoding="utf-8")
        written["style.css"] = True

    # Look for JS
    js_match = re.search(r"```javascript\s*(.*?)```|```js\s*(.*?)```", text, re.DOTALL)
    if js_match:
        content = (js_match.group(1) or js_match.group(2)).strip()
        (OUTPUT_DIR / "game.js").write_text(content, encoding="utf-8")
        written["game.js"] = True

    if "index.html" in written and "game.js" in written:
        _FALLBACK_TRIGGERED = True
        print(f"\n  ⚠️  FALLBACK: extracted and wrote {list(written.keys())} from text response")
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

    # Success = tool wrote files OR fallback extracted them
    files_on_disk = [
        (OUTPUT_DIR / f).exists()
        for f in ["index.html", "style.css", "game.js"]
    ]
    success = state.get("execution_done") or _FALLBACK_TRIGGERED or all(files_on_disk)

    print("\n" + "═" * 60)
    print("  🚀  BUILD COMPLETE" if success else "  ⚠️  BUILD INCOMPLETE")
    print("═" * 60)

    if success:
        print(f"""
  Game title : {game_plan.get('title', 'Untitled')}
  Framework  : {game_plan.get('framework', '?').upper()}
  Output dir : {OUTPUT_DIR}
  Time taken : {elapsed:.1f}s

  ▶  To play: open {OUTPUT_DIR}/index.html in your browser
        """)
    else:
        print(f"\n  State keys: {list(state.keys())}")
        print(f"  Files on disk: index.html={files_on_disk[0]}, "
              f"style.css={files_on_disk[1]}, game.js={files_on_disk[2]}")
        print("  Try running again or check the output directory manually.")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(
            "\n  ❌  ERROR: Gemini API key not found.\n"
            "  Set GEMINI_API_KEY:\n\n"
            "    export GEMINI_API_KEY=AIza...\n"
            "    docker run -e GEMINI_API_KEY=AIza... ...\n"
        )
        sys.exit(1)

    if len(sys.argv) > 1:
        game_idea = " ".join(sys.argv[1:]).strip()
    else:
        print(BANNER)
        print("  Describe the game you want to build.\n")
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
