# Changelog

## 0.1.0 — 2026-10-08

First public release.

- Single-page builder with six target formats (Claude, Cursor, Antigravity, OpenAI, Gemini, Grok), an initial-prompt mode and nine follow-up kinds (quick, next, fix, review, change, correction, clarification, redirect, resume), per-turn guardrails, pasted context, phases/approval gates, keys explaining what each choice generates, prompt history, save/load, JSON import/export.
- **Chat interviewer**: describe the project in your own words; a small local model extracts fields and asks one question at a time until you say "done". The page then assembles the prompt deterministically.
- **Tidy with AI**: one-shot clean-up of whatever is in the form, every change shown for approval.
- Works against any OpenAI-compatible endpoint; `response_format: json_object` is used so even 3–9B models return parseable output. Guard rails stop small models from inventing deliverables, audience or scope.
- Pluggable: `create_router(Settings)` for FastAPI apps, a standalone `prompt-builder` server, a Docker image, or just open the HTML file (form only, no AI).
