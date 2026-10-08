"""The two model-backed operations, as plain functions so any web framework (or a CLI) can wrap them:

    status(settings)         -> is the endpoint up and is the model there?
    tidy(settings, body)     -> clean up the form fields; returns only the fields that changed
    chat(settings, body)     -> one interviewer turn; returns the reply, the field changes and a done flag

The page itself (static/prompt-builder.html) is a deterministic template engine; the model only ever fills form
fields. It never writes the final prompt, so a small model is enough and the output format is always exact.
"""
from __future__ import annotations

import json
import re
import time

from .llm import ModelError, complete, extract_json, list_models, model_listed
from .settings import Settings


class PBError(Exception):
    def __init__(self, message: str, status: int = 502, raw: str = ""):
        super().__init__(message)
        self.status = status
        self.raw = raw


# ------------------------------------------------------------------------------------------------ vocabulary
# These lists are duplicated in the page; keep them in sync (the page's checkbox labels must match exactly).
DELIVS = ["Working code (complete files)", "Project folder structure", "README with setup steps", "Dockerfile / docker-compose.yml", ".env.example",
          "Database schema / migrations", "API documentation", "Automated tests", "Deployment / run instructions", "Architecture overview",
          "Implementation plan / roadmap", "Troubleshooting guide", "UI mockup / wireframe", "Sample data / seed data"]
STYLES = ["Ask clarifying questions before writing code", "Propose a plan and wait for my approval", "Give step-by-step instructions I can follow",
          "Provide complete file contents (no snippets or '...')", "Don't assume prior knowledge; explain commands",
          "State which OS/shell/container each command runs in", "Build in small, testable milestones", "Flag risks, assumptions, and trade-offs",
          "Keep it simple; avoid over-engineering", "Include verification steps for every stage"]
TYPES = ["New project from scratch", "Add a feature to an existing project", "Fix a bug / debug", "Refactor / clean up",
         "Deploy / infrastructure / DevOps", "Research / planning only (no code yet)"]
FU_KINDS = {"quick": "Quick message (one-liner, no boilerplate)", "next": "Next task in this project", "fix": "Fix / debug a result",
            "review": "Review / verify last output", "change": "Change direction / scope", "correct": "Correction (the AI has a fact wrong)",
            "clarify": "Clarification (the AI misread my intent)", "redirect": "Redirect / stop (do this instead)", "resume": "Resume after interruption"}

# Text fields the Tidy pass may rewrite. Pasted material (logs, context) is deliberately excluded.
TIDY_FIELDS = {
    "initial": {
        "name": "Project name (short)",
        "oneliner": "One-sentence summary: what it is, for whom",
        "problem": "Problem being solved / why this needs to exist",
        "users": "Users / audience",
        "goals": "Goals, one per line",
        "outcomes": "Success criteria / expected outcomes, one per line, each testable",
        "outscope": "Out of scope: what NOT to build, one per line",
        "phases": "Phases / approval gates in order, one per line (only if the notes describe a sequence)",
        "stack": "Tech stack / preferred tools",
        "env": "Environment: OS, hardware, where it runs",
        "constraints": "Constraints: budget, APIs, performance, security, rules; one per line",
        "extra": "Anything else: tone, special rules",
    },
    "followup": {
        "fuTask": "The request for this turn (task / what is wrong / what I meant / what to do instead), clear and specific",
        "fuExpected": "Expected outcome, testable",
        "fuDone": "Done so far / already tried / believed done, one item per line",
        "fuGuard": "Guardrails for this turn: things not to touch, interrupt or assume; one per line",
    },
}

# Everything the interviewer may fill.
CHAT_FIELDS = {
    "initial": dict(TIDY_FIELDS["initial"], **{
        "type": "Type of work: exactly one of " + " | ".join(TYPES),
        "context": "Existing context: repo structure, files, errors, links, prior decisions (verbatim material the user gives)",
        "deliv": "Deliverables: a JSON array of labels chosen ONLY from this list: " + " | ".join(DELIVS),
        "delivOther": "Other deliverables the user asks for that are NOT in the deliv list (e.g. 'comparison of candidate APIs with cost'), one per line",
        "style": "How the AI should work: a JSON array of labels chosen ONLY from this list: " + " | ".join(STYLES),
    }),
    "followup": dict(TIDY_FIELDS["followup"], **{
        "fuKind": "Kind of follow-up: exactly one key from " + ", ".join(f"{k} ({v})" for k, v in FU_KINDS.items()),
        "fuLast": "Pasted evidence: the error, log, wrong output or last reply (verbatim)",
        "fuPaste": "Other pasted context (verbatim)",
    }),
}

ORDER = {
    "initial": "1) what it is and for whom (name, oneliner, type) 2) the problem 3) goals 4) success criteria that can be tested "
               "5) deliverables 6) stack and environment 7) constraints and out of scope 8) how the AI should work (style) and phases/approval gates.",
    "followup": "1) what happened / what they want now (this decides fuKind) 2) the specific request (fuTask) 3) evidence or last output if relevant "
                "4) expected outcome 5) what is done or already tried 6) guardrails for this turn.",
}

TIDY_SYSTEM = (
    "You tidy a person's rough notes into clean fields for a software-project prompt. "
    "You will receive a JSON object of fields (key, description, current text). Return ONLY a JSON object with the SAME keys and the tidied text as string values.\n"
    "Rules:\n"
    "- Preserve the author's meaning, facts, names, numbers, paths and IP addresses exactly. Never invent details, examples or requirements that are not in the notes.\n"
    "- Fix spelling, grammar and punctuation. Turn fragments into clear sentences. Keep the author's voice; do not pad.\n"
    "- People often dump everything into one field. If goals, outcomes, constraints, stack or env are EMPTY and the notes in other fields clearly STATE such things, FILL them from those notes (one item per line) and shorten the source field to what belongs there. This is the main value of the pass.\n"
    "- users, outscope and phases are different: fill them ONLY with things the notes say explicitly. Never infer an audience, never guess what is out of scope, never invent phases. If the notes do not say, leave them empty.\n"
    "- Fields described as 'one per line' are newline-separated lists, no bullets or numbering.\n"
    "- Make success criteria / expected outcomes testable only where the notes allow; otherwise leave them as stated.\n"
    "- If you have nothing to improve in a field, return it unchanged. Leave empty fields empty unless rule 3 applies.\n"
    "- No commentary, no markdown fences: output the JSON object only."
)

INTERVIEW = (
    "You ALWAYS answer with one JSON object and nothing else: {\"reply\": \"<what you say to the user>\", \"fields\": {<only fields that changed>}, \"done\": <true|false>}.\n"
    "You are a friendly, sharp interviewer helping a person build a complete brief for an AI coding assistant. You fill a form by chatting.\n"
    "You receive: the form fields (key, what it means, current value), and the conversation so far. Each turn you:\n"
    "1. Extract everything the user's latest message tells you into the fields (fix spelling, keep their meaning and facts exactly, never invent).\n"
    "2. Reply in plain language: one short line reflecting what you captured (only if something new), then ONE question about the most valuable missing thing, "
    "in this priority: {order} Skip anything already filled. Offer a concrete example in the question when it helps ('e.g. ...'). Keep replies under 60 words.\n"
    "3. If the user says they don't know or to skip, leave the field empty and move on. If they ask you to suggest, suggest 2-3 options and ask which.\n"
    "   Never guess 'deliv', 'style', 'users', 'outscope' or 'phases': set them only from what the user explicitly says (you may ASK about them, offering the list). "
    "Every stated aim goes into 'goals' (one per line); every measurable result into 'outcomes'; every limit or preference into 'constraints'.\n"
    "4. When the user says they are done / build it / that's enough, OR all important fields have content and nothing material is missing: set done=true, "
    "make any last field fixes, and reply with a one-line wrap-up (no question).\n"
    "List fields ('one per line') are newline-separated strings. 'deliv' and 'style' are JSON arrays of exact labels from their lists. "
    "Output ONLY a JSON object: {\"reply\": string, \"fields\": {only the fields that changed}, \"done\": boolean}. No markdown fences."
)

# Small models "helpfully" guess checkbox lists and audience. Changes to these fields are accepted only when the
# user's latest message, or the question they are answering, is actually about that topic.
GUARDED = {
    "deliv": r"\bdeliverables?\b|\bdeliver\b|\breadme\b|\bdocumentation\b|api docs|\broadmap\b|\bmockup\b|\bwireframe\b|seed data|sample data|troubleshooting guide|architecture overview|complete files|automated tests?|unit tests?|\.env\b|compose file|\bdockerfile\b|\bmigrations?\b|db schema|what (do you|should i) (want|get|produce)",
    "style": r"\brules?\b|\bapprov|\bpropose\b|wait for|step[- ]by[- ]step|explain (the )?commands?|\bmilestones?\b|\brisks?\b|trade-?offs?|keep it simple|over-?engineer|\bverif|\bclarif|ask (me )?questions|which (os|shell)|\bsnippets?\b|how (you|the ai|it) (should )?work",
    "users": r"\busers?\b|\baudience\b|\bcustomers?\b|\bpeople\b|\bfans\b|\bteam\b|\bstaff\b|\bclients?\b|\bfor my\b|\bwho (is|are) (it|this) for\b",
    "outscope": r"out[- ]of[- ]scope|not (going to )?build|don'?t build|\bexclude\b|\bexcluding\b|\bno code\b|\bnot (now|yet)\b|\bleave out\b",
    "phases": r"\bphases?\b|\bgates?\b|\bstages?\b|\bfirst\b[\s\S]{0,80}\bthen\b|\bapprov|\bstep ?1\b|\bmilestones?\b",
}


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "done")
    return bool(v)


# ------------------------------------------------------------------------------------------------ operations
def status(settings: Settings) -> dict:
    """Is the endpoint reachable and is the configured model listed? (Some servers don't list models; then ok=True with a note.)"""
    try:
        ids = list_models(settings)
    except Exception as ex:   # noqa: BLE001 - we want the user-facing reason, whatever it is
        return dict(ok=False, model=settings.model, base_url=settings.base_url, error=f"Model host not reachable ({ex.__class__.__name__}: {ex}).")
    if not ids:
        return dict(ok=True, model=settings.model, base_url=settings.base_url, models=[], note="Endpoint up; it does not list models.")
    present = model_listed(settings.model, ids)
    return dict(ok=present, model=settings.model, base_url=settings.base_url, models=ids,
                error=None if present else f"Model '{settings.model}' is not on the host (it has: {', '.join(ids)}).")


def _mode(body: dict) -> str:
    return "followup" if body.get("mode") == "followup" else "initial"


def _fields(body: dict) -> dict:
    f = body.get("fields")
    return f if isinstance(f, dict) else {}


def tidy(settings: Settings, body: dict) -> dict:
    mode = _mode(body)
    spec = TIDY_FIELDS[mode]
    fields = _fields(body)
    payload = {k: {"description": d, "text": str(fields.get(k) or "")} for k, d in spec.items()}
    if not any(v["text"].strip() for v in payload.values()):
        raise PBError("Nothing to tidy: the fields are empty.", 400)
    in_chars = sum(len(v["text"]) for v in payload.values())
    budget = min(settings.tidy_max_tokens, max(250, int(in_chars / 3 * 1.6) + 40 * len(payload)))
    t0 = time.time()
    try:
        txt, truncated = complete(settings, [{"role": "system", "content": TIDY_SYSTEM},
                                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
                                  max_tokens=budget, temperature=0.2)
        out = extract_json(txt)
    except ModelError as ex:
        raise PBError(str(ex))
    if not isinstance(out, dict):
        raise PBError("The model returned something that is not a field object.")
    changes = {}
    for k in spec:
        new = out.get(k)
        if isinstance(new, list):
            new = "\n".join(str(x) for x in new)
        if not isinstance(new, str):
            continue
        new = new.strip()
        old = payload[k]["text"].strip()
        # Tidy may empty a field only when it moved that content elsewhere (i.e. it also filled other fields).
        if new != old and (new or any(isinstance(out.get(j), str) and out.get(j).strip() and not payload[j]["text"].strip() for j in spec)):
            changes[k] = new
    return dict(changes=changes, model=settings.model, ms=int((time.time() - t0) * 1000), max_tokens=budget, truncated=truncated)


def chat(settings: Settings, body: dict) -> dict:
    mode = _mode(body)
    spec = CHAT_FIELDS[mode]
    fields = _fields(body)
    raw_msgs = body.get("messages")
    msgs = [m for m in (raw_msgs if isinstance(raw_msgs, list) else [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)][-30:]
    if not msgs or msgs[-1]["role"] != "user":
        raise PBError("The last message must be from the user.", 400)
    current = {k: (fields.get(k) if isinstance(fields.get(k), list) else str(fields.get(k) or "")) for k in spec}
    system = (INTERVIEW.replace("{order}", ORDER[mode])
              + "\n\nFIELD MEANINGS (mode: " + mode + "):\n" + json.dumps(spec, ensure_ascii=False, indent=1)
              + "\n\nCURRENT VALUES (plain strings; deliv/style are arrays). In your 'fields' output use the SAME plain shape and include only fields you change:\n"
              + json.dumps(current, ensure_ascii=False, indent=1))
    txt = ""
    try:
        # low temperature: extraction should be deterministic; the "conversation" part does not need creativity
        txt, truncated = complete(settings, [{"role": "system", "content": system}] + msgs, max_tokens=settings.chat_max_tokens, temperature=0.15)
        out = extract_json(txt)
    except ModelError as ex:
        raise PBError(str(ex), raw=txt[:400])
    if not isinstance(out, dict):
        raise PBError("The model returned something that is not a chat object.", raw=txt[:400])
    topic = (msgs[-1]["content"] + " " + (msgs[-2]["content"] if len(msgs) > 1 else "")).lower()
    proposed = out.get("fields")
    changes = {}
    for k, v in (proposed.items() if isinstance(proposed, dict) else []):
        if k not in spec or (k in GUARDED and not re.search(GUARDED[k], topic)):
            continue
        if isinstance(v, dict):
            v = v.get("current", v.get("value", ""))
        if v == current.get(k):
            continue
        if k in ("deliv", "style"):
            allowed = DELIVS if k == "deliv" else STYLES
            if isinstance(v, str):
                v = [x.strip() for x in v.split("\n") if x.strip()]
            if isinstance(v, list):
                kept = [x for x in v if isinstance(x, str) and x in allowed]
                if kept or not v:          # a paraphrased list that matches nothing must not uncheck everything
                    if kept != current.get(k):
                        changes[k] = kept
            continue
        if isinstance(v, list):
            v = "\n".join(str(x) for x in v)
        v = str(v if v is not None else "").strip()
        if not v:                          # the model never erases what the user typed; only the form can
            continue
        if (k == "type" and v not in TYPES) or (k == "fuKind" and v not in FU_KINDS):
            continue
        changes[k] = v
    reply = str(out.get("reply") or "").strip() or ("Got it." if changes else "Tell me more?")
    return dict(reply=reply, fields=changes, done=_truthy(out.get("done")), truncated=truncated)
