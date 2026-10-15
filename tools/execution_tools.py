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
import re
from pathlib import Path
from google.adk.tools.tool_context import ToolContext


OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./output")).resolve()


# ─── Helper to bundle into a single standalone HTML file ──────────────────────

def bundle_to_single_html(game_html: str = "", index_html: str = "", style_css: str = "", game_js: str = "") -> str:
    """Ensure code is a complete, self-contained HTML file containing HTML, CSS, and JS."""
    if game_html and game_html.strip():
        html = game_html.strip()
        # Clean any accidental outer markdown fences
        html = re.sub(r"^```(?:html)?\s*", "", html, flags=re.IGNORECASE)
        html = re.sub(r"\s*```$", "", html)
        if not html.lower().startswith("<!doctype html"):
            html = f"<!DOCTYPE html>\n{html}"
        # Auto-repair unclosed script/body/html tags if stream was truncated
        if "<script" in html.lower() and "</script>" not in html.lower():
            html += "\n</script>"
        if "<body" in html.lower() and "</body>" not in html.lower():
            html += "\n</body>"
        if "</html>" not in html.lower():
            html += "\n</html>"
        return html

    # If separate parts were passed, bundle them into one single HTML file
    css_block = f"<style>\n{style_css.strip()}\n</style>" if style_css.strip() else ""
    js_block  = f"<script>\n{game_js.strip()}\n</script>"  if game_js.strip()  else ""

    # Check if index_html already has html/body tags
    if "<body" in index_html.lower():
        # Inject style into <head> or at top, inject script before </body> or at bottom
        html = index_html
        if css_block:
            if "</head>" in html:
                html = html.replace("</head>", f"  {css_block}\n</head>")
            else:
                html = f"{css_block}\n{html}"
        if js_block:
            if "</body>" in html:
                html = html.replace("</body>", f"  {js_block}\n</body>")
            else:
                html = f"{html}\n{js_block}"
        return html

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Playable Game</title>
  {css_block}
</head>
<body>
  {index_html.strip()}
  {js_block}
</body>
</html>"""


# ─── Tool 1: store (GeneratorAgent calls this) ────────────────────────────────

def store_generated_code(
    game_html: str = "",
    index_html: str = "",
    style_css:  str = "",
    game_js:    str = "",
    tool_context: ToolContext = None,
) -> dict:
    """
    Store the generated self-contained game HTML code in session state for the WriterAgent.

    The game code MUST be written entirely in a single .html file containing all
    HTML structure, CSS (<style>), and JavaScript (<script>).

    Args:
        game_html: Complete standalone HTML file (including <!DOCTYPE html>, <style>, and <script>).
        index_html: (Optional fallback) HTML layout if generated separately.
        style_css:  (Optional fallback) CSS stylesheet.
        game_js:    (Optional fallback) JavaScript game logic.

    Returns:
        {"status": "stored", "size": N}
    """
    full_html = bundle_to_single_html(
        game_html=game_html,
        index_html=index_html,
        style_css=style_css,
        game_js=game_js
    )

    if not full_html or len(full_html.strip()) < 50:
        return {"status": "error", "message": "Generated HTML content is empty or incomplete."}

    if tool_context:
        tool_context.state["generated_game_html"] = full_html
        tool_context.state["generated_index_html"] = full_html
        tool_context.state["code_stored"] = True

    print(f"\n  💾  Single-file game HTML stored in session state ({len(full_html)} bytes)")
    return {"status": "stored", "size": len(full_html), "file": "index.html"}


# ─── Tool 2: write (WriterAgent calls this) ───────────────────────────────────

def write_game_files(
    game_html: str = "",
    index_html: str = "",
    style_css:  str = "",
    game_js:    str = "",
    tool_context: ToolContext = None,
) -> dict:
    """
    Write the complete, self-contained game into a single .html file on disk.

    Args:
        game_html: Complete self-contained HTML content (including <style> and <script>).
        index_html: (Optional fallback) HTML layout if separate.
        style_css:  (Optional fallback) CSS if separate.
        game_js:    (Optional fallback) JS if separate.

    Returns:
        {"status": "written", "file": "index.html", "path": ...}
    """
    # Guard: prevent infinite re-writes caused by mode=ANY looping
    if tool_context and tool_context.state.get("execution_done"):
        return {
            "status": "already_written",
            "message": "Game HTML already written. Your job is complete — do not call any more tools.",
        }

    # If game_html is not passed directly, look for it in tool_context state
    if not game_html and tool_context:
        game_html = tool_context.state.get("generated_game_html") or tool_context.state.get("generated_index_html") or ""

    full_html = bundle_to_single_html(
        game_html=game_html,
        index_html=index_html,
        style_css=style_css,
        game_js=game_js
    )

    if not full_html or len(full_html.strip()) < 50:
        return {"status": "error", "message": "game_html is empty — read generated_game_html from state before calling write_game_files."}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUTPUT_DIR / "index.html"
    dest.write_text(full_html.strip(), encoding="utf-8")
    size_kb = round(dest.stat().st_size / 1024, 1)

    if tool_context:
        tool_context.state["execution_done"] = True
        tool_context.state["output_dir"]     = str(OUTPUT_DIR)
        tool_context.state["output_file"]    = str(dest)

    print("\n  ✅  Single-file game written:")
    print(f"       index.html  →  {dest}  ({size_kb} KB)")

    return {
        "status": "written",
        "file": "index.html",
        "path": str(dest),
        "size_kb": size_kb,
        "output_dir": str(OUTPUT_DIR),
    }
