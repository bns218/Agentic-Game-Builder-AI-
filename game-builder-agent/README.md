# 🎮 Agentic Game-Builder AI  –  Powered by Google Gemini ADK

An AI agent pipeline that accepts a natural-language game idea, asks clarifying
questions, produces a structured game plan, and generates a fully playable browser
game (`index.html` + `style.css` + `game.js`) — built entirely on the
**Google Agent Development Kit (ADK)**.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Docker Build & Run](#docker-build--run)
3. [Local Run (no Docker)](#local-run-no-docker)
4. [Agent Architecture](#agent-architecture)
5. [Bug Fix – v2](#bug-fix--v2-executionagent-text-output-problem)
6. [How Data Flows Between Agents](#how-data-flows-between-agents)
7. [Trade-offs](#trade-offs)
8. [Future Improvements](#future-improvements)
9. [Project Structure](#project-structure)

---

## Quick Start

```bash
git clone <repo-url>
cd game-builder-agent
mkdir -p output

# Build the image
docker build -t game-builder-agent .

# Run interactively (you will be asked questions about your game)
docker run -it --rm \
  -e GEMINI_API_KEY=AIza... \
  -v "$(pwd)/output:/output" \
  game-builder-agent

# OR pass the game idea inline
docker run -it --rm \
  -e GEMINI_API_KEY=AIza... \
  -v "$(pwd)/output:/output" \
  game-builder-agent "a retro space shooter with power-ups"
```

Open `output/index.html` in any modern browser to play the generated game.

> **API Key**: Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com).

---

## Docker Build & Run

### Prerequisites

| Tool   | Version |
|--------|---------|
| Docker | 20.10+  |
| Gemini API key | `AIza...` (free tier available) |

### Step-by-step

```bash
# 1. Build the image (multi-stage, final image ~130 MB)
docker build -t game-builder-agent .

# 2. Create output directory on the host
mkdir -p output

# 3. Run (interactive – the agent asks clarifying questions)
docker run -it --rm \
  -e GEMINI_API_KEY="AIza..." \
  -v "$(pwd)/output:/output" \
  game-builder-agent
```

#### Using Docker Compose

```bash
export GEMINI_API_KEY="AIza..."

# Interactive
docker compose run --rm agent

# Inline idea
docker compose run --rm agent "a puzzle game where you match colours"
```

### Output files

After the agent finishes you will find these in `./output/`:

```
output/
├── index.html        ← Open this in a browser to play
├── style.css
├── game.js
└── game_plan.json    ← Structured game plan (for audit / debugging)
```

---

## Local Run (no Docker)

```bash
# Python 3.12+
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export GEMINI_API_KEY="AIza..."
export OUTPUT_DIR="./output"

python agent.py                             # interactive prompt
python agent.py "a top-down maze game"      # inline idea
```

---

## Agent Architecture

The system uses three core ADK primitives composed into a pipeline:

```
SequentialAgent: GameBuilderPipeline
│
├── LoopAgent: ClarificationLoop          (Phase 1)
│   └── LlmAgent: ClarificationAgent
│       tools: ask_user_question
│               complete_clarification ──► sets actions.escalate = True
│
├── LlmAgent: PlanningAgent               (Phase 2)
│   tools: read_session_state
│           save_game_plan
│
└── SequentialAgent: ExecutionAgent       (Phase 3)  ← split in v2
    ├── LlmAgent: GeneratorAgent
    │   tools: read_session_state
    │           store_generated_code      ← saves to state
    └── LlmAgent: WriterAgent
        tools: read_session_state
                write_game_files          ← reads state, writes disk
```

### ADK Primitives Used

| Primitive | Role in this project |
|-----------|---------------------|
| `LlmAgent` | Each phase's reasoning brain (Gemini 2.0 Flash) |
| `LoopAgent` | Wraps clarification so the agent can ask multiple questions |
| `SequentialAgent` | Chains all three phases on a single shared session |
| `Runner` | Drives the pipeline and streams events |
| `InMemorySessionService` | Provides shared state across all agents |
| `ToolContext.state` | Dict that agents use to pass structured data forward |
| `ToolContext.actions.escalate` | Signal for LoopAgent to stop iterating |

### Phase 1 — Clarification (`ClarificationLoop`)

A `LoopAgent` wraps the `ClarificationAgent` (an `LlmAgent`).  On each
iteration the agent either:
- Calls `ask_user_question(question)` to surface one targeted question,
  storing the answer in `state["qa_history"]`.
- Or calls `complete_clarification(summary)` when it has enough information.
  This sets `tool_context.actions.escalate = True`, which causes the
  `LoopAgent` to stop iterating.

A `max_iterations=6` safety cap prevents infinite loops if the LLM
fails to escalate.

### Phase 2 — Planning (`PlanningAgent`)

An `LlmAgent` that:
1. Calls `read_session_state("clarification_summary")` to retrieve Phase 1's output.
2. Designs the full game architecture: framework choice, entities, mechanics,
   controls, win/lose conditions, canvas size, technical notes.
3. Calls `save_game_plan(plan_json)` which validates required keys and writes
   `game_plan.json` to the output directory.

### Phase 3 — Execution (`ExecutionAgent`)

An `LlmAgent` that:
1. Calls `read_session_state("game_plan_raw")` for the full JSON plan.
2. Calls `read_session_state("clarification_summary")` for extra fidelity.
3. Generates all three game files.
4. Calls `write_game_files(index_html, style_css, game_js)` to write them to disk.

---

## Bug Fix – v2: ExecutionAgent Text-Output Problem

### What went wrong

When running v1, Phase 3 emitted the game code as a **text response** instead
of calling `write_game_files()`.  The pipeline reported "BUILD INCOMPLETE" and
no files were written to disk.

```
💬  [ExecutionAgent] ```html
<!DOCTYPE html>
...                               ← code in text, NOT a tool call
```

### Root cause

The original `ExecutionAgent` was a single `LlmAgent` asked to do two things
in one turn: *generate code* and *call a tool with that code*.  Gemini treats
"write code" as its primary job and emits a text response; calling a tool feels
optional when the code is already visible in the output.

### Fix (three layers of defence)

**Layer 1 — Split the work (structural fix)**

Phase 3 is now a `SequentialAgent` containing two specialised agents:

```
SequentialAgent: ExecutionAgent
├── LlmAgent: GeneratorAgent   → only job: call store_generated_code()
└── LlmAgent: WriterAgent      → only job: call write_game_files()
```

`GeneratorAgent` stores the code in session state.  `WriterAgent` reads it
from state and writes the files.  Each agent has a single, unambiguous mandatory
tool call — there is no "optional" text path.

**Layer 2 — Force tool use (`mode="ANY"`)**

Both agents use ADK's `generate_content_config` with `tool_config`:

```python
generate_content_config = types.GenerateContentConfig(
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="ANY")
    )
)
```

`mode="ANY"` tells the Gemini API that **every response must be a function
call**.  A plain-text response is rejected at the API level.

**Layer 3 — Orchestrator fallback extractor**

`agent.py`'s event handler watches for final text responses containing
`<!DOCTYPE` or ` ```html ` and automatically extracts + writes the files using
regex if the tool path somehow still fails.  This ensures the user always gets
a playable game even if layers 1–2 have an unexpected edge case.

---

## How Data Flows Between Agents

```
Session State (InMemorySessionService)
────────────────────────────────────────────────────────────

 Before run:
   game_idea  ←  set by orchestrator from CLI input

 After Phase 1 (ClarificationLoop):
   qa_history              list[{question, answer}]
   clarification_summary   str  ← rich plain-text requirements

 After Phase 2 (PlanningAgent):
   game_plan               dict  ← parsed JSON plan
   game_plan_raw           str   ← pretty-printed JSON

 After Phase 3a (GeneratorAgent):
   generated_index_html    str  ← complete index.html code
   generated_style_css     str  ← complete style.css code
   generated_game_js       str  ← complete game.js code
   code_stored             bool

 After Phase 3b (WriterAgent):
   execution_done          bool
   output_dir              str   ← path to written files
```

Agents read state via the `read_session_state(key)` tool.  This gives them
explicit, on-demand access to structured prior outputs without relying on
the LLM to perfectly reproduce large JSON blobs from conversation context.

---

## Trade-offs

### 1. `SequentialAgent` + shared session vs. separate Runner calls per phase

**Chosen**: Single `SequentialAgent` with one `Runner` and one session.

**Pros**: Clean ADK-idiomatic design; state flows naturally; one Runner to manage.

**Cons**: If Phase 3 fails, you must restart from Phase 1 (no mid-pipeline resume).

**Alternative**: Run each phase with its own `Runner.run_async()` call in the
orchestrator's `main()`.  This allows retry from any phase but adds boilerplate.
With more time, a checkpoint file (`checkpoint.json`) would enable resume.

---

### 2. `LoopAgent` for clarification vs. multi-turn conversation

**Chosen**: `LoopAgent` wrapping a single `LlmAgent`.

**Why ADK's `LoopAgent`?** It is the idiomatic primitive for "keep doing X until
condition met" in ADK.  The loop exit is controlled by `actions.escalate`, which
is cleaner than polling a flag or tracking turn count manually.

**Trade-off**: The `ClarificationAgent` must proactively call `complete_clarification()`
to exit — if the LLM forgets to, the `max_iterations` cap kicks in.  We mitigate
this with a strong system-prompt instruction and a conservative cap of 6.

---

### 3. Single-pass file generation vs. per-file LLM calls

**Chosen**: Generate all three files in one `write_game_files()` tool call.

**Why**: CSS class names and JS variable names must be consistent across files.
If generated separately, `style.css` might define `.player-hp` but `game.js`
references `.player-health-bar` — a silent, hard-to-debug mismatch.

**Trade-off**: Larger single response; more prone to token-limit truncation.
Mitigated by using a high `max_tokens` in the runner config and writing
robust system-prompt rules against truncation.

---

### 4. `read_session_state` tool vs. relying on conversation context

**Chosen**: Explicit tool call to read state.

**Why**: ADK `LlmAgent`s don't automatically inject session state into their
context window.  The conversation chain carries prior agents' *text* responses,
but a full JSON game plan (often 2–4 KB) can be truncated.  Having the agent
call `read_session_state("game_plan_raw")` fetches the exact stored value
deterministically.

**Trade-off**: One extra tool call per agent start.  The cost is negligible.

---

### 5. `gemini-2.0-flash` vs. `gemini-1.5-pro`

**Chosen**: `gemini-2.0-flash` for all three agents.

**Why**: Faster response time and lower cost; excellent instruction following and
code generation.  The game files are small enough that Flash handles them well.

**Alternative**: Use Flash for clarification (low complexity) and Pro for
execution (high-quality code).  This mixed strategy would increase cost slightly
but improve code quality for complex games.  Easy to switch — just change the
`model=` parameter in each `LlmAgent`.

---

## Future Improvements

### Reliability

- **Self-healing loop**: After `write_game_files()`, spawn Playwright headlessly
  to open `index.html`, capture console errors, and feed them back to a
  `DebugAgent` that patches `game.js` automatically.

- **Phase checkpointing**: Persist `session.state` to a JSON file after each
  phase so a crashed run can be resumed without re-asking all questions.

- **Structured output enforcement**: Use Gemini's `response_schema` parameter
  for the planning phase to guarantee a valid JSON plan every time — no regex,
  no retry needed.

### UX

- **Web UI**: Replace the CLI with a FastAPI + WebSocket backend and a React
  frontend that streams agent events in real time and previews the game in an
  `<iframe>`.

- **Streaming display**: Use `Runner.run_async()` events to show the generated
  code as it arrives, rather than waiting for the full response.

- **Iteration mode**: After playing, let the user say "make enemies faster" and
  trigger a targeted `EditAgent` that diffs and patches `game.js` only.

### Architecture

- **Per-agent model routing**: Flash for clarification, Pro/Flash-Thinking for
  complex game design, Flash for simple file writing.

- **Parallel sub-agents**: Use ADK's `ParallelAgent` to generate `style.css` and
  `index.html` concurrently while `game.js` is being written, then merge.

- **Multi-provider support**: Abstract the `model=` field behind a config file so
  teams can swap to Claude, GPT-4o, or a local Ollama model without code changes.

---

## Project Structure

```
game-builder-agent/
│
├── agent.py                        # Orchestrator – SequentialAgent + Runner + fallback extractor
│
├── agents/
│   ├── __init__.py
│   ├── clarification_agent.py      # Phase 1: LoopAgent + ClarificationAgent
│   ├── planning_agent.py           # Phase 2: PlanningAgent
│   └── execution_agent.py          # Phase 3: GeneratorAgent + WriterAgent (v2 split)
│
├── tools/
│   ├── __init__.py
│   ├── user_interaction.py         # ask_user_question, complete_clarification
│   ├── planning_tools.py           # save_game_plan
│   ├── execution_tools.py          # store_generated_code, write_game_files  ← v2
│   └── state_tools.py              # read_session_state
│
├── output/                         # Generated game files (created at runtime)
│   ├── index.html
│   ├── style.css
│   ├── game.js
│   └── game_plan.json
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt                # google-adk, google-genai
└── README.md
```

---

*Built with Google Gemini ADK (`google-adk`) and `gemini-2.0-flash`.*
