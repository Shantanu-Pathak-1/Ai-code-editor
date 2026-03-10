# ============================================================
#  Ethrix-Forge — Agentic AI Gateway
#  Drop-in module for main.py  (FastAPI + google-genai + httpx)
#  Author-ready: copy the imports + constants + functions below
# ============================================================

# ── REQUIRED IMPORTS (merge into your existing main.py imports) ──────────────
import os
import json
import asyncio
import logging
from typing import Any

import httpx
from google import genai                        # pip install google-genai
from google.genai import types as genai_types
from fastapi import HTTPException
from pydantic import BaseModel

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ethrix_forge.ai_gateway")


# ══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC REQUEST / RESPONSE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ExistingFile(BaseModel):
    """A file already open in the editor that the AI can read as context."""
    filename: str
    language: str
    code: str


class AgentRequest(BaseModel):
    """
    POST body your React frontend must send to  /api/agent/generate
    {
        "prompt": "Add a dark-mode toggle to the Navbar",
        "existing_files": [
            {"filename": "index.html",  "language": "html",       "code": "..."},
            {"filename": "style.css",   "language": "css",        "code": "..."}
        ],
        "model_preference": "gemini"   // optional: "gemini" | "openrouter" | "groq"
    }
    """
    prompt: str
    existing_files: list[ExistingFile] = []
    model_preference: str = "gemini"


class GeneratedFile(BaseModel):
    filename: str
    language: str
    code: str


class AgentResponse(BaseModel):
    files: list[GeneratedFile]
    provider_used: str          # which provider actually answered
    total_files_changed: int


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTEM PROMPT  (the "brain" of the agentic workflow)
# ══════════════════════════════════════════════════════════════════════════════

AGENTIC_SYSTEM_PROMPT = """
You are Ethrix, an elite AI Software Architect and Senior Full-Stack Developer
embedded inside the Ethrix-Forge Cloud Code Editor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKFLOW  (Think → Plan → Execute)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 – THINK (internal, do not output)
  • Re-read the user's request and ALL existing files carefully.
  • Understand the full project structure, dependencies, and intent.
  • Identify EXACTLY which files need to be created or modified.

STEP 2 – PLAN (internal, do not output)
  • List the minimal set of files that must change.
  • Never touch files that are unaffected by the request.
  • If a new file is needed (e.g., a component, a utility), create it.

STEP 3 – EXECUTE (this is your ONLY output)
  • Respond with a VALID JSON array — nothing else.
  • No markdown code fences, no explanations, no preamble.
  • Each element in the array is an object with exactly these three keys:
      "filename"  — relative path e.g. "components/Navbar.js"
      "language"  — lowercase language id e.g. "javascript", "python", "css"
      "code"      — the complete, production-ready file content as a string

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. OUTPUT FORMAT: Your entire response MUST be a JSON array.
   ✅ CORRECT:  [ {"filename": "...", "language": "...", "code": "..."} ]
   ❌ WRONG:    Any text, markdown, or explanation outside the JSON array.

2. SELECTIVE EDITING: Only include files you actually changed or created.
   If index.html is unchanged, DO NOT include it in your response.

3. COMPLETE FILES: Each "code" value must contain the full file content —
   never use placeholders like "// rest of code here".

4. FOLDER SUPPORT: Use forward-slash paths for nested files:
   "src/components/Button.jsx", "assets/css/theme.css"

5. LANGUAGE IDS: Use standard lowercase identifiers:
   html, css, javascript, typescript, python, json, markdown, etc.

6. QUALITY: Write production-grade code. Use modern best practices,
   clean variable names, and add brief inline comments where helpful.
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  PROVIDER CONFIG  — loaded from environment variables
# ══════════════════════════════════════════════════════════════════════════════

def _get_gemini_keys() -> list[str]:
    """
    Collect all GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, …
    from environment variables in order.
    """
    keys: list[str] = []
    # Primary key
    primary = os.getenv("GEMINI_API_KEY", "")
    if primary:
        keys.append(primary)
    # Numbered backups: GEMINI_API_KEY_2 … GEMINI_API_KEY_10
    for i in range(2, 11):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "")
        if k:
            keys.append(k)
    return keys


OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
GROQ_API_KEY:       str = os.getenv("GROQ_API_KEY", "")

GEMINI_MODEL      = os.getenv("GEMINI_MODEL",      "gemini-2.0-flash")
OPENROUTER_MODEL  = os.getenv("OPENROUTER_MODEL",  "deepseek/deepseek-chat-v3-0324:free")
GROQ_MODEL        = os.getenv("GROQ_MODEL",        "llama-3.3-70b-versatile")

# Errors that should trigger a key / provider switch
_RATE_LIMIT_PHRASES = (
    "429",
    "resource_exhausted",
    "rate limit",
    "quota exceeded",
    "too many requests",
)


# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT BUILDER  — assembles the full user message with context
# ══════════════════════════════════════════════════════════════════════════════

def _build_user_message(prompt: str, existing_files: list[ExistingFile]) -> str:
    """
    Wraps the user's instruction with the current file context so the AI
    understands what already exists before making changes.
    """
    parts: list[str] = []

    if existing_files:
        parts.append("=== EXISTING PROJECT FILES (read-only context) ===\n")
        for f in existing_files:
            parts.append(
                f"FILE: {f.filename}  [language: {f.language}]\n"
                f"```{f.language}\n{f.code}\n```\n"
            )
        parts.append("=== END OF EXISTING FILES ===\n\n")

    parts.append(f"USER REQUEST:\n{prompt}")
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
#  JSON PARSER  — robust extraction from raw LLM text
# ══════════════════════════════════════════════════════════════════════════════

def _parse_files_from_response(raw: str) -> list[dict]:
    """
    Tries multiple strategies to extract the JSON array from LLM output.
    Strategy 1 — direct json.loads (ideal: model obeyed instructions).
    Strategy 2 — find the first '[' … last ']' and parse that slice.
    Strategy 3 — strip markdown fences then retry.
    """
    text = raw.strip()

    # Strategy 1: Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 2: Bracket slicing
    start = text.find("[")
    end   = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                logger.warning("JSON extracted via bracket-slice strategy.")
                return data
        except json.JSONDecodeError:
            pass

    # Strategy 3: Strip markdown code fences
    import re
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            logger.warning("JSON extracted after stripping markdown fences.")
            return data
    except json.JSONDecodeError:
        pass

    logger.error("All JSON parse strategies failed. Raw response:\n%s", raw[:2000])
    raise ValueError("AI response could not be parsed as a JSON array of files.")


# ══════════════════════════════════════════════════════════════════════════════
#  PROVIDER CALLS
# ══════════════════════════════════════════════════════════════════════════════

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _RATE_LIMIT_PHRASES)


# ── Gemini ────────────────────────────────────────────────────────────────────

def _sync_call_gemini(api_key: str, user_message: str) -> str:
    """
    Synchronous Gemini call using the new google-genai SDK.
    Wrapped with asyncio.to_thread() at the call site so FastAPI never blocks.
    """
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=AGENTIC_SYSTEM_PROMPT,
            temperature=0.2,        # lower = more deterministic / structured
            max_output_tokens=8192,
        ),
    )
    return response.text


async def _call_gemini_with_fallback(user_message: str) -> tuple[str, str]:
    """
    Tries every available Gemini API key in sequence.
    Returns (raw_text, key_label) or raises RuntimeError if all keys fail.
    """
    keys = _get_gemini_keys()
    if not keys:
        raise RuntimeError("No GEMINI_API_KEY found in environment.")

    last_exc: Exception | None = None
    for idx, key in enumerate(keys):
        key_label = "GEMINI_API_KEY" if idx == 0 else f"GEMINI_API_KEY_{idx + 1}"
        try:
            logger.info("Trying Gemini with %s …", key_label)
            text = await asyncio.to_thread(_sync_call_gemini, key, user_message)
            logger.info("Gemini (%s) succeeded.", key_label)
            return text, key_label
        except Exception as exc:
            last_exc = exc
            if _is_rate_limit_error(exc):
                logger.warning(
                    "%s hit rate/quota limit (%s). Switching to next key …",
                    key_label, exc
                )
                continue          # try next key
            else:
                logger.error("Gemini (%s) non-retryable error: %s", key_label, exc)
                raise             # hard failure — don't retry other keys

    raise RuntimeError(
        f"All Gemini keys exhausted. Last error: {last_exc}"
    )


# ── OpenRouter ────────────────────────────────────────────────────────────────

async def _call_openrouter(user_message: str) -> str:
    """Async OpenRouter call via httpx."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured.")

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system",  "content": AGENTIC_SYSTEM_PROMPT},
            {"role": "user",    "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://ethrix-forge.app",   # your app URL
        "X-Title":       "Ethrix-Forge",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        resp = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp = await resp  if asyncio.iscoroutine(resp) else resp   # compatibility shim
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_openrouter_safe(user_message: str) -> tuple[str, str]:
    logger.info("Trying OpenRouter (%s) …", OPENROUTER_MODEL)
    text = await _call_openrouter(user_message)
    logger.info("OpenRouter succeeded.")
    return text, f"openrouter/{OPENROUTER_MODEL}"


# ── Groq ──────────────────────────────────────────────────────────────────────

async def _call_groq(user_message: str) -> str:
    """Async Groq call via httpx."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured.")

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system",  "content": AGENTIC_SYSTEM_PROMPT},
            {"role": "user",    "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_groq_safe(user_message: str) -> tuple[str, str]:
    logger.info("Trying Groq (%s) …", GROQ_MODEL)
    text = await _call_groq(user_message)
    logger.info("Groq succeeded.")
    return text, f"groq/{GROQ_MODEL}"


# ══════════════════════════════════════════════════════════════════════════════
#  MASTER ORCHESTRATOR  — Think → Plan → Execute with full fallback chain
# ══════════════════════════════════════════════════════════════════════════════

async def run_agentic_workflow(request: AgentRequest) -> AgentResponse:
    """
    Core agentic pipeline:
      1. Build the context-aware user message.
      2. Try providers in preferred order with automatic fallback.
      3. Parse the JSON response into structured GeneratedFile objects.
      4. Return only the files that were actually changed / created.
    """
    user_message = _build_user_message(request.prompt, request.existing_files)

    # ── Build the provider call order based on user preference ────────────────
    async def try_gemini()      -> tuple[str, str]: return await _call_gemini_with_fallback(user_message)
    async def try_openrouter()  -> tuple[str, str]: return await _call_openrouter_safe(user_message)
    async def try_groq()        -> tuple[str, str]: return await _call_groq_safe(user_message)

    preference = request.model_preference.lower()
    if preference == "openrouter":
        provider_order = [try_openrouter, try_gemini,     try_groq]
    elif preference == "groq":
        provider_order = [try_groq,       try_gemini,     try_openrouter]
    else:  # default: gemini first
        provider_order = [try_gemini,     try_openrouter, try_groq]

    # ── Try each provider, moving on only if rate-limited or unavailable ──────
    raw_text: str       = ""
    provider_used: str  = "unknown"
    last_error: Exception | None = None

    for provider_fn in provider_order:
        try:
            raw_text, provider_used = await provider_fn()
            break                   # success — stop trying fallbacks
        except RuntimeError as exc:
            # RuntimeError = "no key configured" or "all keys exhausted"
            logger.warning("Provider unavailable: %s", exc)
            last_error = exc
            continue
        except Exception as exc:
            if _is_rate_limit_error(exc):
                logger.warning("Rate limit on provider, falling back: %s", exc)
                last_error = exc
                continue
            # Unexpected non-rate-limit error — still try next provider
            logger.error("Unexpected provider error, falling back: %s", exc)
            last_error = exc
            continue
    else:
        # All providers failed
        raise HTTPException(
            status_code=503,
            detail=f"All AI providers failed. Last error: {last_error}",
        )

    # ── Parse response ────────────────────────────────────────────────────────
    try:
        files_data = _parse_files_from_response(raw_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AI returned unparseable output: {exc}",
        )

    # ── Validate & build response objects ─────────────────────────────────────
    generated_files: list[GeneratedFile] = []
    for item in files_data:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict item in AI response: %s", item)
            continue
        fn = item.get("filename", "").strip()
        lang = item.get("language", "").strip().lower()
        code = item.get("code", "")
        if not fn or code is None:
            logger.warning("Skipping incomplete file entry: %s", item)
            continue
        generated_files.append(GeneratedFile(filename=fn, language=lang, code=code))

    if not generated_files:
        raise HTTPException(
            status_code=500,
            detail="AI returned an empty list of files. No changes were made.",
        )

    return AgentResponse(
        files=generated_files,
        provider_used=provider_used,
        total_files_changed=len(generated_files),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  FASTAPI ROUTE  — add this to your main.py router
# ══════════════════════════════════════════════════════════════════════════════
#
#   from fastapi import APIRouter
#   router = APIRouter()
#
#   @router.post("/api/agent/generate", response_model=AgentResponse)
#   async def agent_generate(request: AgentRequest):
#       """
#       Agentic code generation / editing endpoint for Ethrix-Forge.
#       Accepts the user prompt + existing project files as context,
#       returns only the files that were created or modified.
#       """
#       return await run_agentic_workflow(request)
#
# ══════════════════════════════════════════════════════════════════════════════
