# Small Model AI Prompt Builder

Talk through a project with a **small local model**; get back a complete, well-structured prompt for **Claude, Cursor, Antigravity, OpenAI, Gemini or Grok**.

The model never writes the prompt. It only *interviews* you and fills a form — then the page assembles the prompt deterministically. That is why a 4B–9B model is enough, why the output format is always exact, and why nothing leaves your network.

```
you:  sportsedge, my sports site. stop using ESPN, get data direct from source,
      articles should be ON my site. python/flask in docker on the .20 box
AI:   Got it — name, stack and environment captured. Is this a new project, or
      are you adding this to an existing site?
you:  existing. goals: articles readable on my site, scores from a non-ESPN API
AI:   Captured two goals. What does success look like — something I could test?
...
you:  done
AI:   Here is your complete brief.      → Copy prompt
```

## What it does

- **Chat interviewer** — describe the project any way you like; it extracts what it can, then asks **one question at a time** about the most valuable missing thing (goals → testable outcomes → deliverables → stack/environment → constraints/scope → how the AI should work). "Don't know" leaves a field empty; "done" builds the prompt.
- **Initial prompt** with per-tool formats (XML tags for Claude, markdown for Cursor/Antigravity/Gemini, role + brief for OpenAI, System/User for Grok), **type of work** instructions (bug fix, refactor, DevOps, research…), **phases / approval gates**, working rules.
- **Follow-up prompts** for the rest of the conversation: quick message, next task, fix/debug, review, change scope, **correction** (it has a fact wrong), **clarification** (it misread you), **redirect/stop**, **resume after interruption** — each with the right fields and a "keep / redo" instruction, plus per-turn **guardrails** and pasted context.
- **Tidy with AI** — one-shot clean-up of whatever is in the form; every change is shown old → new for approval.
- Keys under each selector explain what each choice generates. Prompt history per project, save/load, JSON import/export. Everything is stored in your browser.

## Quick start

### 1. Just the page (no AI)
Open `prompt_builder/static/prompt-builder.html` in a browser. The form, all formats and save/load work. The chat and Tidy buttons stay hidden because there is no server.

### 2. With a model — `pip`
```bash
pip install git+https://github.com/jkhall316/small-model-ai-prompt-builder
export PB_BASE_URL=http://127.0.0.1:11434/v1   # Ollama (default); see "Backends"
export PB_MODEL=qwen3:4b
prompt-builder --open                         # http://127.0.0.1:7810
```

### 3. With a model — Docker
```bash
cp .env.example .env    # edit PB_BASE_URL / PB_MODEL / PB_API_KEY
docker compose up -d    # http://localhost:7810
```

### 4. Inside your own FastAPI app (the "plugin" way)
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prompt_builder import Settings, create_router, STATIC_DIR

app = FastAPI()
app.include_router(create_router(Settings.from_env()))              # /api/pb/tidy, /api/pb/chat, /api/pb/tidy/status
app.mount("/pb", StaticFiles(directory=STATIC_DIR), name="pb")      # page at /pb/prompt-builder.html
```
Serve the page under any path; it finds the API through `<meta name="pb-api" content="/api/pb">` (or set `window.PB_API` before the script). Mounting it in an `<iframe>` inside an existing dashboard works too — same origin, no CORS.

## Backends

Any OpenAI-compatible `/v1/chat/completions` endpoint. `PB_EXTRA_BODY` is merged into every request — use it to switch off "thinking" on hybrid models, which otherwise burn the whole token budget before answering.

| Server | `PB_BASE_URL` | Notes |
|---|---|---|
| **Ollama** | `http://host:11434/v1` | `PB_EXTRA_BODY={"think": false}` for qwen3 / deepseek-r1 style models |
| **llama.cpp server** | `http://host:8080/v1` | `--jinja` recommended; `PB_EXTRA_BODY={"chat_template_kwargs": {"enable_thinking": false}}` for Qwen3/3.5 |
| **LM Studio** | `http://host:1234/v1` | |
| **vLLM** | `http://host:8000/v1` | same `chat_template_kwargs` trick |
| **LocalAI** | `http://host:8080/v1` | Granite 4.x: `{"reasoning_effort": "none"}` |
| **OpenAI / OpenRouter** | `https://api.openai.com/v1` | set `PB_API_KEY`; works, but defeats the "small local model" point |

Set `PB_JSON_MODE=false` if a backend rejects `response_format`.

### Which model?
Measured on the interviewer task (one turn ≈ 300–600 tokens of JSON):

| Model | Result |
|---|---|
| Qwen3.5-9B Q4 (llama.cpp, RTX 2080 Ti) | ~70 tok/s, 3–5 s per turn, reliable extraction — **what this was developed on** |
| Qwen3-4B-Instruct-2507 Q4 | fine on a GPU; Q8 on CPU was unusable (1–2 tok/s) |
| Granite-4.2-3B Q8 (CPU) | 15 tok/s, works with `reasoning_effort: none`; ~40 s per turn |
| ≤ 2B | drops details and breaks JSON too often |

Rule of thumb: **3–4B on a GPU** is the floor; **7–9B** is comfortable; anything bigger buys nothing here.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PB_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint |
| `PB_MODEL` | `qwen3:4b` | model name as the server knows it |
| `PB_API_KEY` | | bearer token if the server wants one |
| `PB_EXTRA_BODY` | `{}` | JSON merged into every request |
| `PB_JSON_MODE` | `true` | send `response_format: json_object` |
| `PB_TIMEOUT_S` | `180` | per request |
| `PB_CHAT_MAX_TOKENS` / `PB_TIDY_MAX_TOKENS` | `900` / `1500` | output budgets |
| `PB_PREFIX` | `/api/pb` | URL prefix of the API routes |
| `PB_HOST` / `PB_PORT` | `127.0.0.1` / `7810` | standalone server bind |
| `PB_ALLOWED_HOSTS` | loopback only | regex of accepted `Host` headers; `.*` to expose on a LAN |
| `PB_CONFIG` | | path to a JSON file with the same keys (`base_url`, `model`, …); env vars override it |

A bad value (non-JSON `PB_EXTRA_BODY`, non-numeric timeout, missing `PB_CONFIG` file) stops the server at startup with one line naming the variable.

### Endpoints
| | |
|---|---|
| `GET /` | the page (standalone server) |
| `GET /healthz` | `{"ok": true, "version": …}` |
| `GET /api/pb/tidy/status` | is the model endpoint up and is the model listed (Ollama-style `name:latest` tolerated) |
| `GET /api/pb/config` | effective settings with the key masked, URL credentials stripped and only the *keys* of `extra_body` |
| `POST /api/pb/chat` | `{mode, fields, messages}` → `{reply, fields, done}` |
| `POST /api/pb/tidy` | `{mode, fields}` → `{changes, model, ms}` |

The API has no authentication; the standalone server accepts loopback `Host` headers only unless you widen `PB_ALLOWED_HOSTS`, and the compose file publishes on `127.0.0.1`. A page on another site can still *fire* a request at `localhost:7810` (it cannot read the reply) — the cost is model time, not data.

## How it stays honest with a small model

- The model returns **only field values** as JSON (`response_format: json_object`), never the prompt.
- Fields that small models like to guess — deliverables, working rules, audience, out-of-scope, phases — are accepted **only when your message or the question you are answering is about that topic**.
- Tidy never sends pasted logs or context, and shows every change before applying it.
- The completeness meter is a checklist, not a judgement; "done" is yours to call.

## Security notes
- The server proxies to your model endpoint and holds its API key; by default it only answers requests whose `Host` is loopback. Open it with `PB_ALLOWED_HOSTS` deliberately.
- Everything the page stores (projects, history, chats) lives in the browser's `localStorage` for that origin.

## Project layout
```
prompt_builder/
  static/prompt-builder.html   the page: template engine + chat UI (vanilla HTML/CSS/JS, no build step)
  core.py                      the interviewer and tidy logic as plain functions
  llm.py                       OpenAI-compatible client + tolerant JSON extraction
  api.py                       FastAPI router factory (create_router)
  server.py                    standalone app + `prompt-builder` CLI
  settings.py                  env / file configuration
```

## License
MIT — see `LICENSE`.
