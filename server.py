"""
server.py  –  FastAPI Web Server for Agentic Game-Builder AI
══════════════════════════════════════════════════════════════
Serves the web UI and provides real-time WebSocket streaming for:
  • Live code generation (token-by-token live coding display)
  • Live game running in an interactive iframe
  • Single self-contained .html game output
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Fix Windows console UTF-8 output encoding for emojis and unicode banners
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tools.execution_tools import bundle_to_single_html, OUTPUT_DIR

app = FastAPI(title="Agentic Game Builder AI")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR  = BASE_DIR / "web"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files if web directory exists
if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

# Mount output directory so /output/index.html is accessible directly in browser
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR), html=True), name="output")


@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Web UI not found.</h1>", status_code=404)


@app.get("/api/status")
async def get_status():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    game_file = OUTPUT_DIR / "index.html"
    return {
        "hasApiKey": bool(api_key),
        "outputDir": str(OUTPUT_DIR),
        "hasCurrentGame": game_file.exists(),
        "currentGameSize": game_file.stat().st_size if game_file.exists() else 0,
    }


@app.get("/api/game/current")
async def get_current_game():
    game_file = OUTPUT_DIR / "index.html"
    if not game_file.exists():
        return HTMLResponse("<h3>No game built yet.</h3>", status_code=404)
    return HTMLResponse(content=game_file.read_text(encoding="utf-8"))


@app.get("/api/download")
async def download_game():
    game_file = OUTPUT_DIR / "index.html"
    if not game_file.exists():
        return JSONResponse({"error": "No game generated yet"}, status_code=404)
    return FileResponse(
        path=str(game_file),
        filename="game.html",
        media_type="text/html",
    )


def extract_clean_html(raw_text: str) -> str:
    """Extract and validate clean standalone HTML from generated text."""
    text = raw_text.strip()
    
    # 1. Regex match for <!DOCTYPE html> ... </html>
    match = re.search(r"<!DOCTYPE html>.*?</html>", text, re.DOTALL | re.IGNORECASE)
    if match:
        html = match.group(0).strip()
        # Clean any accidental outer comment tags
        html = re.sub(r"^\s*<!--\s*", "", html)
        html = re.sub(r"\s*-->\s*$", "", html)
        return html
    
    # 2. Check for fenced html block
    fenced = re.search(r"```(?:html)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
        if "<!doctype" not in content.lower():
            content = f"<!DOCTYPE html>\n{content}"
        return content

    # 3. Use fallback bundler
    cleaned = re.sub(r"^\s*<!--.*?-->", "", text, flags=re.DOTALL).strip()
    return bundle_to_single_html(game_html=cleaned or text)


@app.websocket("/ws/generate")
async def websocket_generate(websocket: WebSocket):
    await websocket.accept()

    try:
        data = await websocket.receive_text()
        req = json.loads(data)
        idea = req.get("idea", "").strip()
        api_key = req.get("apiKey", "").strip() or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        raw_model = req.get("model", "").strip()
        
        # Automatically upgrade deprecated models to gemini-3.8-flash
        if not raw_model or "2.0-flash" in raw_model or "1.5" in raw_model:
            model_name = "gemini-3.8-flash"
        else:
            model_name = raw_model

        if not idea:
            await websocket.send_json({
                "type": "error",
                "message": "Game idea cannot be empty. Please describe the game you want to build."
            })
            return

        if not api_key:
            await websocket.send_json({
                "type": "error",
                "message": "Gemini API key is required. Please set GEMINI_API_KEY or input your key in the settings modal."
            })
            return

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # ── Step 1: Start Live Generation ─────────────────────────────────────
        await websocket.send_json({
            "type": "phase",
            "phase": "coding",
            "message": f"Architecting & live coding single-file HTML game for: '{idea}' (using {model_name})..."
        })
        await asyncio.sleep(0.2)

        system_instruction = """You are an elite browser game developer. Your task is to generate a COMPLETE, FULLY PLAYABLE, 100% SELF-CONTAINED HTML5 browser game.

CRITICAL HARD REQUIREMENTS:
1. OUTPUT FORMAT:
   - Output ONLY the complete, ready-to-run <!DOCTYPE html> document.
   - Start immediately with <!DOCTYPE html> and end with </html>.
   - Do NOT wrap in markdown fences (no ```html).
   - Do NOT output conversational prose, explanations, or introductory text.
   - Do NOT wrap code in HTML comments (no <!-- -->).

2. SINGLE .HTML FILE ONLY:
   - All styling MUST be inside <style>...</style> in <head>.
   - All game logic MUST be inside <script>...</script> before </body>.
   - Zero external .css, .js, local image files, sprite sheets, or external audio files.

3. GRAPHICS & RENDERING:
   - Draw all visuals (characters, sprites, environments, UI, particles) using HTML5 Canvas 2D API (ctx.fillRect, ctx.arc, ctx.beginPath, ctx.createLinearGradient, ctx.fillText, etc.).
   - Make visuals vibrant, clean, and retro-arcade or cyber-styled with high contrast.

4. SOUND SYNTHESIS (WEB AUDIO API):
   - Include a synthetic sound effects manager using the browser Web Audio API:
     const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
   - Implement audio triggers for sounds (jump, laser, hit, coin/point, game over, victory) using oscillators (sine, square, sawtooth) with frequency ramps and gain envelopes.
   - Audio must resume on first user click/keypress.

5. CONTROLS:
   - Support Keyboard (Arrow keys, WASD, Space).
   - ALWAYS include on-screen virtual touch buttons or touch drag/click handlers so mobile, tablet, and mouse-only players can play effortlessly!

6. GAME LOOP & STATE MANAGEMENT:
   - Use requestAnimationFrame with proper delta-time handling.
   - States: MENU/TITLE screen (instructions + Start button), PLAYING state, GAME OVER screen, and VICTORY/NEXT LEVEL screen.
   - Score counter, Health/Lives bar, and a working 'Play Again / Restart' button.

7. ERROR-FREE GUARANTEE:
   - Write 100% COMPLETE runnable code without any placeholders, truncated blocks, or '// todo'.
   - Include an error boundary (window.onerror) that displays any unexpected issue on screen instead of a silent blank canvas.
   - Wrap initialization in window.addEventListener('DOMContentLoaded', ...).
"""

        user_prompt = f"""Build the complete, self-contained playable game now:
Game Idea: "{idea}"

Start directly with <!DOCTYPE html>."""

        full_code = ""

        # Run stream in thread
        def stream_generator():
            return client.models.generate_content_stream(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    max_output_tokens=8192,
                )
            )

        try:
            response_stream = await asyncio.to_thread(stream_generator)
            for chunk in response_stream:
                chunk_text = chunk.text or ""
                if chunk_text:
                    full_code += chunk_text
                    await websocket.send_json({
                        "type": "chunk",
                        "chunk": chunk_text
                    })
                    await asyncio.sleep(0.005)
        except Exception as stream_err:
            # If model 404, retry with gemini-3.8-flash
            err_str = str(stream_err)
            if ("404" in err_str or "not available" in err_str.lower() or "not found" in err_str.lower()) and model_name != "gemini-3.8-flash":
                print(f"  Model '{model_name}' not available, retrying with gemini-3.8-flash...")
                model_name = "gemini-3.8-flash"
                response_stream = await asyncio.to_thread(stream_generator)
                full_code = ""
                for chunk in response_stream:
                    chunk_text = chunk.text or ""
                    if chunk_text:
                        full_code += chunk_text
                        await websocket.send_json({
                            "type": "chunk",
                            "chunk": chunk_text
                        })
                        await asyncio.sleep(0.005)
            else:
                raise stream_err

        # ── Step 2: Clean, Validate and Save ───────────────────────────────────
        await websocket.send_json({
            "type": "phase",
            "phase": "validating",
            "message": "Validating single-file HTML and writing to output/index.html..."
        })

        clean_html = extract_clean_html(full_code)

        # Save to output/index.html
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUTPUT_DIR / "index.html"
        dest.write_text(clean_html.strip(), encoding="utf-8")
        size_kb = round(dest.stat().st_size / 1024, 1)

        # Also write game plan audit
        audit_plan = {
            "idea": idea,
            "output_file": str(dest),
            "size_kb": size_kb,
            "format": "single_file_html",
        }
        (OUTPUT_DIR / "game_plan.json").write_text(json.dumps(audit_plan, indent=2), encoding="utf-8")

        await websocket.send_json({
            "type": "complete",
            "code": clean_html,
            "size_kb": size_kb,
            "path": str(dest),
            "message": f"Game successfully generated and saved! ({size_kb} KB)"
        })

    except WebSocketDisconnect:
        print("  Client disconnected from /ws/generate")
    except Exception as exc:
        print(f"  WebSocket generation error: {exc}", file=sys.stderr)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Generation error: {str(exc)}"
            })
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n🎮 Starting Agentic Game Builder AI on http://localhost:{port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
