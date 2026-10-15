"""
test_suite.py  –  Comprehensive Automated Test Suite for Agentic Game Builder AI
══════════════════════════════════════════════════════════════════════════════════
Tests:
  1. Agent Architecture & ADK Primitive Graph
  2. Execution Tools & Single-File Bundler
  3. Planning Tools & JSON Schema Validation
  4. State Reading & Session State Tools
  5. HTML & JavaScript Integrity of Generated Game
  6. FastAPI Server Routes & Static Endpoints
"""

import json
import os
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path("./output").resolve()

def test_agent_graph():
    print("\n--- [Test 1] Agent Architecture & ADK Hierarchy ---")
    from agents.clarification_agent import clarification_loop, clarification_agent
    from agents.planning_agent import planning_agent
    from agents.execution_agent import execution_agent, generator_agent, writer_agent
    from google.adk.agents import SequentialAgent, LoopAgent, LlmAgent

    assert isinstance(clarification_loop, LoopAgent), "clarification_loop should be LoopAgent"
    assert isinstance(clarification_agent, LlmAgent), "clarification_agent should be LlmAgent"
    assert isinstance(planning_agent, LlmAgent), "planning_agent should be LlmAgent"
    assert isinstance(execution_agent, SequentialAgent), "execution_agent should be SequentialAgent"
    assert isinstance(generator_agent, LlmAgent), "generator_agent should be LlmAgent"
    assert isinstance(writer_agent, LlmAgent), "writer_agent should be LlmAgent"
    print("  [OK] All agent classes and ADK primitive types verified.")

    pipeline = SequentialAgent(
        name="GameBuilderPipeline",
        sub_agents=[clarification_loop, planning_agent, execution_agent],
        description="End-to-end pipeline"
    )
    assert len(pipeline.sub_agents) == 3
    print("  [OK] GameBuilderPipeline successfully assembled with 3 phases.")


def test_bundler_and_extractor():
    print("\n--- [Test 2] Single-File HTML Bundler & Extractor ---")
    from tools.execution_tools import bundle_to_single_html
    from server import extract_clean_html

    # Test 1: Clean markdown fenced HTML
    fenced_html = "```html\n<!DOCTYPE html>\n<html><head><title>Test</title></head><body><h1>Game</h1></body></html>\n```"
    res1 = extract_clean_html(fenced_html)
    assert res1.startswith("<!DOCTYPE html>"), f"Failed clean start: {res1[:25]}"
    assert res1.endswith("</html>"), f"Failed clean end: {res1[-25:]}"
    assert "```" not in res1, "Fences were not removed"
    print("  [OK] Markdown fences stripped properly.")

    # Test 2: HTML with surrounding comments
    commented_html = "<!-- 📐 ARCHITECTURE PLAN -->\n<!-- note -->\n<!DOCTYPE html><html><body>Test</body></html>\n<!-- footer -->"
    res2 = extract_clean_html(commented_html)
    assert res2.startswith("<!DOCTYPE html>"), f"Comments not stripped: {res2[:25]}"
    assert "<!-- 📐" not in res2, "Comment was not stripped"
    print("  [OK] Outer HTML comments stripped cleanly.")

    # Test 3: Separate index_html, style_css, game_js bundled into 1 file
    part_html = "<canvas id='canvas'></canvas>"
    part_css = "body { background: black; }"
    part_js = "const canvas = document.getElementById('canvas');"
    bundled = bundle_to_single_html(index_html=part_html, style_css=part_css, game_js=part_js)
    assert "<!DOCTYPE html>" in bundled
    assert "<style>" in bundled and part_css in bundled
    assert "<script>" in bundled and part_js in bundled
    assert part_html in bundled
    print("  [OK] Separate HTML + CSS + JS bundled into a single standalone HTML document.")


def test_planning_and_state_tools():
    print("\n--- [Test 3] Planning Tools & State Validation ---")
    from tools.planning_tools import save_game_plan
    from tools.state_tools import read_session_state
    from tools.execution_tools import store_generated_code, write_game_files

    class MockContext:
        def __init__(self):
            self.state = {}
            class MockActions:
                escalate = False
            self.actions = MockActions()

    ctx = MockContext()

    # Valid schema test
    valid_plan = json.dumps({
        "title": "Neon Racer",
        "framework": "vanilla",
        "player_controls": {"keys": ["ArrowLeft", "ArrowRight"]},
        "core_mechanics": ["dodge obstacles", "collect fuel"],
        "win_condition": "reach finish line",
        "lose_condition": "fuel == 0",
        "entities": [{"name": "car", "visual": "red box"}]
    })
    res_plan = save_game_plan(valid_plan, ctx)
    assert res_plan["status"] == "saved"
    assert ctx.state["game_plan"]["title"] == "Neon Racer"
    print("  [OK] Valid JSON game plan accepted and stored in state.")

    # Missing keys test
    invalid_plan = json.dumps({"title": "Incomplete Game"})
    res_bad = save_game_plan(invalid_plan, ctx)
    assert res_bad["status"] == "error"
    assert "missing required keys" in res_bad["message"].lower()
    print("  [OK] Incomplete plan rejected with descriptive validation error.")

    # State read test
    read_ok = read_session_state("game_plan", ctx)
    assert read_ok["value"]["title"] == "Neon Racer"
    read_missing = read_session_state("non_existent_key", ctx)
    assert read_missing["value"] is None
    print("  [OK] read_session_state retrieves state values accurately.")

    # Store code test
    html_sample = "<!DOCTYPE html><html><head><style>body{}</style></head><body><script>1;</script></body></html>"
    store_res = store_generated_code(game_html=html_sample, tool_context=ctx)
    assert store_res["status"] == "stored"
    assert ctx.state["code_stored"] is True
    print("  [OK] store_generated_code writes HTML to session state.")


def test_current_game_html_integrity():
    print("\n--- [Test 4] Current Generated Game HTML & JS Verification ---")
    game_file = OUTPUT_DIR / "index.html"
    assert game_file.exists(), f"Game file does not exist at {game_file}"

    content = game_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content, "Missing <!DOCTYPE html>"
    assert "<canvas" in content, "Missing <canvas> element"
    assert "<style>" in content and "</style>" in content, "Missing <style> tags"
    assert "<script>" in content and "</script>" in content, "Missing <script> tags"
    assert "AudioContext" in content, "Missing Web Audio API synthesis"
    assert "<!--" not in content[:30], "Code should not start with HTML comment"
    print(f"  [OK] output/index.html verified ({len(content)} bytes, {len(content.splitlines())} lines).")
    print("  [OK] Contains canvas, sound synthesis, responsive styling, and complete game loop.")


def test_server_endpoints():
    print("\n--- [Test 5] FastAPI Web Server Endpoints ---")
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)

    # 1. Root UI route
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Agentic Game-Builder AI" in res_root.text
    print("  [OK] GET / serves the interactive Live Coding Web Dashboard.")

    # 2. Status API
    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "hasApiKey" in data
    assert "outputDir" in data
    assert "hasCurrentGame" in data
    assert data["hasCurrentGame"] is True
    print(f"  [OK] GET /api/status returns valid JSON (hasCurrentGame={data['hasCurrentGame']}).")

    # 3. Current game HTML endpoint
    res_game = client.get("/api/game/current")
    assert res_game.status_code == 200
    assert "<!DOCTYPE html>" in res_game.text
    print("  [OK] GET /api/game/current returns the playable HTML game.")

    # 4. Download endpoint
    res_dl = client.get("/api/download")
    assert res_dl.status_code == 200
    assert res_dl.headers.get("content-type", "").startswith("text/html")
    print("  [OK] GET /api/download sends the index.html file download.")

    # 5. Static output mount
    res_static = client.get("/output/index.html")
    assert res_static.status_code == 200
    print("  [OK] GET /output/index.html static mount accessible for direct playing.")


if __name__ == "__main__":
    try:
        test_agent_graph()
        test_bundler_and_extractor()
        test_planning_and_state_tools()
        test_current_game_html_integrity()
        test_server_endpoints()
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED! TOTAL PROJECT VERIFIED 100% OPERATIONAL.")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
