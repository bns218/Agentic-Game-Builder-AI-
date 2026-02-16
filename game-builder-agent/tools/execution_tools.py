"""
tools/execution_tools.py
──────────────────────────────────────────────────────────────────────────────
Two tools for Phase 3:

  store_generated_code()  – called by GeneratorAgent to save code to state
  write_game_files()      – called by WriterAgent to flush state → disk

Splitting storage and writing into separate tools + separate agents is the
fix for the bug where the model emitted code as text instead of a tool call:

  Before (broken):
    ExecutionAgent: "generate code AND call write_game_files in one turn"
    → LLM chose to just output the code as text (tool call felt optional)

  After (fixed):
    GeneratorAgent: only job = call store_generated_code()
    WriterAgent:    only job = call write_game_files() with state values
    → Each agent has a single, unambiguous mandatory tool call
"""

import os
from pathlib import Path
from google.adk.tools.tool_context import ToolContext


OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))


# ─── Tool 1: store (GeneratorAgent calls this) ────────────────────────────────

def store_generated_code(
    index_html: str,
    style_css:  str,
    game_js:    str,
    tool_context: ToolContext,
) -> dict:
    """
    Store the generated game code in session state for the WriterAgent to use.

    Call this tool ONCE after you have generated complete, runnable code for
    all three files.  Do NOT call this with placeholder or incomplete code.

    Args:
        index_html: Complete contents of index.html.
        style_css:  Complete contents of style.css.
        game_js:    Complete contents of game.js.

    Returns:
        {"status": "stored", "sizes": {"index_html": N, ...}}
    """
    if not index_html.strip():
        return {"status": "error", "message": "index_html is empty"}
    if not game_js.strip():
        return {"status": "error", "message": "game_js is empty"}

    tool_context.state["generated_index_html"] = index_html.strip()
    tool_context.state["generated_style_css"]  = style_css.strip()
    tool_context.state["generated_game_js"]    = game_js.strip()
    tool_context.state["code_stored"]          = True

    sizes = {
        "index_html": len(index_html),
        "style_css":  len(style_css),
        "game_js":    len(game_js),
    }
    print(f"\n  💾  Code stored in session state: {sizes}")
    return {"status": "stored", "sizes": sizes}


# ─── Tool 2: write (WriterAgent calls this) ───────────────────────────────────

def write_game_files(
    index_html: str = "",
    style_css:  str = "",
    game_js:    str = "",
    tool_context: ToolContext = None,
) -> dict:
    """
    Write the three game files to disk.

    Call this tool ONCE with ALL THREE files together after reading all state values.
    Do NOT call this after reading only one or two values — wait until you have all three.
    Do NOT call this more than once.

    Args:
        index_html: Complete contents of index.html (DOCTYPE included).
        style_css:  Complete contents of style.css.
        game_js:    Complete contents of game.js (all game logic).

    Returns:
        {"status": "written", "files": [...]} on success.
        {"status": "already_written"} if called a second time (stop looping).
        {"status": "error", ...} if required files are empty.
    """
    # Guard: prevent infinite re-writes caused by mode=ANY looping
    if tool_context and tool_context.state.get("execution_done"):
        return {
            "status": "already_written",
            "message": "Files already written. Your job is complete — do not call any more tools.",
        }

    if not index_html.strip():
        return {"status": "error", "message": "index_html is empty — you must read generated_index_html from state BEFORE calling write_game_files."}
    if not game_js.strip():
        return {"status": "error", "message": "game_js is empty — you must read generated_game_js from state BEFORE calling write_game_files."}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files_written = []
    for filename, content in [
        ("index.html", index_html),
        ("style.css",  style_css),
        ("game.js",    game_js),
    ]:
        dest = OUTPUT_DIR / filename
        dest.write_text(content.strip(), encoding="utf-8")
        size_kb = dest.stat().st_size / 1024
        files_written.append({
            "file":    filename,
            "path":    str(dest),
            "size_kb": round(size_kb, 1),
        })

    if tool_context:
        tool_context.state["execution_done"] = True
        tool_context.state["output_dir"]     = str(OUTPUT_DIR)

    print("\n  ✅  Game files written:")
    for f in files_written:
        print(f"       {f['file']:<14}  →  {f['path']}  ({f['size_kb']} KB)")

    return {"status": "written", "files": files_written, "output_dir": str(OUTPUT_DIR)}
