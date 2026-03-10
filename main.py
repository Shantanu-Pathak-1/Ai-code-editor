"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         ETHRIX-FORGE — FASTAPI CLOUD SYNC & BACKEND ENGINE                  ║
║         main.py  |  Deployed on Hugging Face Spaces (Docker)                ║
║                                                                              ║
║  Modules:                                                                    ║
║    1. MongoDB  — Workspace & Chat History persistence (motor)                ║
║    2. GitHub   — Clone / Commit / Push via PyGithub + GitPython              ║
║    3. Google Drive — OAuth2 ZIP upload                                       ║
║    4. AI Gateway — Secure proxy for Gemini, OpenRouter & Groq                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import io
import re
import json
import uuid
import asyncio
import zipfile
import tempfile
import logging
import shutil
from datetime import datetime, timezone
from typing import Optional, List, Any, Dict

import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field

# ── AI Providers ──────────────────────────────────────────────────────────────
from google import genai
from google.genai import types as genai_types

# ── Database ──────────────────────────────────────────────────────────────────
import motor.motor_asyncio
from bson import ObjectId
from bson.errors import InvalidId

# ── GitHub ────────────────────────────────────────────────────────────────────
from github import Github, GithubException
import git  # GitPython

# ── Google OAuth / Drive ──────────────────────────────────────────────────────
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.auth.transport.requests import Request as GoogleRequest

# Hugging Face path fix
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log    = logging.getLogger("ethrix-forge")
logger = logging.getLogger("ethrix_forge.ai_gateway")  # Alias for ai_gateway logs

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────────────────────
MONGODB_URI          = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY         = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY   = os.getenv("OPENROUTER_API_KEY", "")
GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN", "")           # optional server-side default
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/drive/callback")
SECRET_KEY           = os.getenv("SECRET_KEY", uuid.uuid4().hex)  # fallback for dev only

PORT = int(os.getenv("PORT", 7860))

GEMINI_MODEL     = os.getenv("GEMINI_MODEL",     "gemini-2.0-flash")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat-v3-0324:free")
GROQ_MODEL       = os.getenv("GROQ_MODEL",       "llama-3.3-70b-versatile")

# Errors that should trigger a key / provider switch
_RATE_LIMIT_PHRASES = (
    "429",
    "resource_exhausted",
    "rate limit",
    "quota exceeded",
    "too many requests",
)

# ─────────────────────────────────────────────────────────────────────────────
# MONGODB CLIENT  (module-level; initialised in lifespan)
# ─────────────────────────────────────────────────────────────────────────────
_mongo_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None

def get_db() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    """Dependency: returns the 'ethrix_forge' database handle."""
    if _mongo_client is None:
        raise HTTPException(status_code=503, detail="Database not initialised yet.")
    return _mongo_client["ethrix_forge"]

# ─────────────────────────────────────────────────────────────────────────────
# IN-MEMORY GOOGLE OAUTH SESSION STORE
# ─────────────────────────────────────────────────────────────────────────────
_drive_sessions: Dict[str, dict] = {}   # state_token → credentials dict

# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN — startup / shutdown
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mongo_client
    log.info("🔌 Connecting to MongoDB…")
    try:
        _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5_000,
        )
        await _mongo_client.admin.command("ping")
        log.info("✅ MongoDB connected.")
        db = _mongo_client["ethrix_forge"]
        await db.workspaces.create_index("user_id")
        await db.workspaces.create_index("updated_at")
        await db.chat_history.create_index("workspace_id")
        await db.chat_history.create_index("user_id")
        log.info("✅ MongoDB indexes ensured.")
    except Exception as exc:
        log.error(f"❌ MongoDB connection failed: {exc}")

    yield

    if _mongo_client:
        _mongo_client.close()
        log.info("🔌 MongoDB disconnected.")

# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Ethrix-Forge Backend",
    description="Cloud Sync, GitHub, Google Drive & AI Gateway for Ethrix-Forge IDE",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _serialize_doc(doc: dict) -> dict:
    if doc is None:
        return {}
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _serialize_doc(v)
        elif isinstance(v, list):
            out[k] = [_serialize_doc(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _validate_object_id(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail=f"Invalid document ID: '{oid}'")


# ═════════════════════════════════════════════════════════════════════════════
# ███  PYDANTIC SCHEMAS  ███████████████████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

class FileObject(BaseModel):
    filename: str = Field(..., example="index.html")
    language: str = Field(..., example="html")
    code:     str = Field(..., example="<!DOCTYPE html>...")

class WorkspaceSaveRequest(BaseModel):
    user_id:  str            = Field(..., example="user_abc123")
    name:     str            = Field(..., example="My Landing Page")
    files:    List[FileObject]
    metadata: Optional[dict] = Field(default_factory=dict)

class WorkspaceResponse(BaseModel):
    workspace_id: str
    user_id:      str
    name:         str
    files:        List[dict]
    metadata:     dict
    created_at:   str
    updated_at:   str

class ChatMessage(BaseModel):
    role:      str           = Field(..., example="user")
    content:   str
    timestamp: Optional[str] = None

class ChatHistorySaveRequest(BaseModel):
    workspace_id: str
    user_id:      str
    messages:     List[ChatMessage]

# ── AI Gateway Schemas ────────────────────────────────────────────────────────
class ExistingFile(BaseModel):
    """A file already open in the editor that the AI can read as context."""
    filename: str
    language: str
    code:     str

class AgentRequest(BaseModel):
    """
    POST body your React frontend must send to  /api/agent/generate
    {
        "prompt": "Add a dark-mode toggle to the Navbar",
        "existing_files": [
            {"filename": "index.html", "language": "html",       "code": "..."},
            {"filename": "style.css",  "language": "css",        "code": "..."}
        ],
        "model_preference": "gemini"   // optional: "gemini" | "openrouter" | "groq"
    }
    """
    prompt:           str
    existing_files:   list[ExistingFile] = []
    model_preference: str = "gemini"

class GeneratedFile(BaseModel):
    filename: str
    language: str
    code:     str

class AgentResponse(BaseModel):
    files:               list[GeneratedFile]
    provider_used:       str   # which provider actually answered
    total_files_changed: int

class AIGatewayRequest(BaseModel):
    prompt:   str          = Field(..., description="User's coding request")
    provider: str          = Field("gemini", description="'gemini' or 'groq'")
    model:    Optional[str] = None

class AIGatewayResponse(BaseModel):
    files:        List[dict]
    raw_response: str
    provider:     str
    model:        str


# ═════════════════════════════════════════════════════════════════════════════
# ███  AGENTIC AI GATEWAY LOGIC  ██████████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

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


# ── Gemini key discovery ──────────────────────────────────────────────────────

def _get_gemini_keys() -> list[str]:
    """Collect GEMINI_API_KEY, GEMINI_API_KEY_2 … GEMINI_API_KEY_10 in order."""
    keys: list[str] = []
    primary = os.getenv("GEMINI_API_KEY", "")
    if primary:
        keys.append(primary)
    for i in range(2, 11):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "")
        if k:
            keys.append(k)
    return keys


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_user_message(prompt: str, existing_files: list[ExistingFile]) -> str:
    """Wraps the user's instruction with current file context for the AI."""
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


# ── JSON parser — 3-strategy robust extraction ────────────────────────────────

def _parse_files_from_response(raw: str) -> list[dict]:
    """
    Strategy 1 — direct json.loads  (model obeyed instructions perfectly).
    Strategy 2 — bracket slicing    (model added preamble/postamble).
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


# ── Rate-limit detection ──────────────────────────────────────────────────────

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _RATE_LIMIT_PHRASES)


# ── Gemini provider ───────────────────────────────────────────────────────────

def _sync_call_gemini(api_key: str, user_message: str) -> str:
    """
    Synchronous google-genai SDK call.
    Always invoke via asyncio.to_thread() so FastAPI never blocks.
    """
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=AGENTIC_SYSTEM_PROMPT,
            temperature=0.2,         # lower = more deterministic / structured
            max_output_tokens=8192,
        ),
    )
    return response.text


async def _call_gemini_with_fallback(user_message: str) -> tuple[str, str]:
    """
    Tries every available Gemini API key in sequence.
    Switches keys on 429 / RESOURCE_EXHAUSTED; raises on hard failures.
    Returns (raw_text, key_label).
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
                    key_label, exc,
                )
                continue          # try next key
            else:
                logger.error("Gemini (%s) non-retryable error: %s", key_label, exc)
                raise             # hard failure — don't retry other keys

    raise RuntimeError(f"All Gemini keys exhausted. Last error: {last_exc}")


# ── OpenRouter provider ───────────────────────────────────────────────────────

async def _call_openrouter(user_message: str) -> str:
    """Async OpenRouter call via httpx."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured.")

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens":  8192,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://ethrix-forge.app",
        "X-Title":       "Ethrix-Forge",
    }

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_openrouter_safe(user_message: str) -> tuple[str, str]:
    logger.info("Trying OpenRouter (%s) …", OPENROUTER_MODEL)
    text = await _call_openrouter(user_message)
    logger.info("OpenRouter succeeded.")
    return text, f"openrouter/{OPENROUTER_MODEL}"


# ── Groq provider ─────────────────────────────────────────────────────────────

async def _call_groq(user_message: str) -> str:
    """Async Groq call via httpx."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured.")

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens":  8192,
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
        return resp.json()["choices"][0]["message"]["content"]


async def _call_groq_safe(user_message: str) -> tuple[str, str]:
    logger.info("Trying Groq (%s) …", GROQ_MODEL)
    text = await _call_groq(user_message)
    logger.info("Groq succeeded.")
    return text, f"groq/{GROQ_MODEL}"


# ── Master orchestrator ───────────────────────────────────────────────────────

async def run_agentic_workflow(request: AgentRequest) -> AgentResponse:
    """
    Core agentic pipeline — Think → Plan → Execute:
      1. Build the context-aware user message.
      2. Try providers in preferred order with automatic fallback.
      3. Parse the JSON response into structured GeneratedFile objects.
      4. Return only the files that were actually changed / created.
    """
    user_message = _build_user_message(request.prompt, request.existing_files)

    # Build provider call order based on user preference
    async def try_gemini()     -> tuple[str, str]: return await _call_gemini_with_fallback(user_message)
    async def try_openrouter() -> tuple[str, str]: return await _call_openrouter_safe(user_message)
    async def try_groq()       -> tuple[str, str]: return await _call_groq_safe(user_message)

    preference = request.model_preference.lower()
    if preference == "openrouter":
        provider_order = [try_openrouter, try_gemini,     try_groq]
    elif preference == "groq":
        provider_order = [try_groq,       try_gemini,     try_openrouter]
    else:  # default: gemini first
        provider_order = [try_gemini,     try_openrouter, try_groq]

    raw_text:      str                = ""
    provider_used: str                = "unknown"
    last_error:    Exception | None   = None

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
            else:
                logger.error("Unexpected provider error, falling back: %s", exc)
            last_error = exc
            continue
    else:
        raise HTTPException(
            status_code=503,
            detail=f"All AI providers failed. Last error: {last_error}",
        )

    # Parse response
    try:
        files_data = _parse_files_from_response(raw_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AI returned unparseable output: {exc}",
        )

    # Validate & build response objects
    generated_files: list[GeneratedFile] = []
    for item in files_data:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict item in AI response: %s", item)
            continue
        fn   = item.get("filename", "").strip()
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


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 4 — GOD MODE AI GATEWAY  ████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are Ethrix, an elite autonomous software engineer inside the Ethrix-Forge AI IDE. Your sole function is to generate complete, production-ready source code.
ABSOLUTE OUTPUT RULES — NEVER VIOLATE THESE:
1. Your response MUST be a single, raw, valid JSON array. Nothing else.
2. Each element: {"filename": "...", "language": "...", "code": "..."}
3. NO markdown fences. NO backticks. NO explanation. NO preamble.
4. All code must be complete and untruncated.
5. Escape double-quotes inside "code" as \\", newlines as \\n.
You are a JSON-outputting machine. You do not converse."""

# 🚀 God Mode multi-model fallback lists
GEMINI_MODELS     = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite-preview-02-05", "gemini-1.5-flash"]
OPENROUTER_MODELS = ["qwen/qwen-2.5-coder-32b-instruct:free", "meta-llama/llama-3.3-70b-instruct:free"]
GROQ_MODELS       = ["qwen-2.5-coder-32b", "llama-3.3-70b-versatile"]


async def _call_gemini_gateway(prompt: str, requested_model: str) -> str:
    """The God Mode AI Gateway: Gemini → OpenRouter → Groq with full model fallback."""
    full_prompt = f"{SYSTEM_PROMPT}\n\nUser Request:\n{prompt}"
    last_error  = ""

    # 🟢 STEP 1: GEMINI — cycle through all available keys and models
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
        for model in GEMINI_MODELS:
            log.info(f"🔄 Trying Gemini: {model}...")
            try:
                def sync_call(m):
                    return client.models.generate_content(model=m, contents=full_prompt)
                response = await asyncio.to_thread(sync_call, model)
                return response.text
            except Exception as e:
                last_error = f"Gemini Error: {str(e)}"
                log.warning(f"Gemini {model} failed: {e}")

    # 🔵 STEP 2: OPENROUTER — cycle through free models
    if OPENROUTER_API_KEY:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for model in OPENROUTER_MODELS:
                log.info(f"🔄 Trying OpenRouter: {model}...")
                try:
                    res = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                        json={"model": model, "messages": [{"role": "user", "content": full_prompt}]},
                    )
                    res.raise_for_status()
                    return res.json()["choices"][0]["message"]["content"]
                except Exception as e:
                    last_error = f"OpenRouter Error: {str(e)}"
                    log.warning(f"OpenRouter {model} failed: {e}")

    # 🟠 STEP 3: GROQ — cycle through available models
    if GROQ_API_KEY:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for model in GROQ_MODELS:
                log.info(f"🔄 Trying Groq: {model}...")
                try:
                    res = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                        json={"model": model, "messages": [{"role": "user", "content": full_prompt}]},
                    )
                    res.raise_for_status()
                    return res.json()["choices"][0]["message"]["content"]
                except Exception as e:
                    last_error = f"Groq Error: {str(e)}"
                    log.warning(f"Groq {model} failed: {e}")

    raise HTTPException(status_code=502, detail=f"All AI limits exhausted! Last error: {last_error}")


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 1 — MONGODB ENDPOINTS  ██████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/workspace/save", tags=["MongoDB"])
async def save_workspace(payload: WorkspaceSaveRequest, db=Depends(get_db)):
    now = _now()
    doc = {
        "user_id":    payload.user_id,
        "name":       payload.name,
        "files":      [f.model_dump() for f in payload.files],
        "metadata":   payload.metadata or {},
        "updated_at": now,
    }
    result = await db.workspaces.find_one_and_update(
        {"user_id": payload.user_id, "name": payload.name},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True, return_document=True,
    )
    if result is None:
        result = await db.workspaces.find_one({"user_id": payload.user_id, "name": payload.name})
    workspace_id = str(result["_id"])
    log.info(f"Workspace saved: {workspace_id} for user {payload.user_id}")
    return {"workspace_id": workspace_id, "message": "Workspace saved successfully."}

@app.get("/workspace/{workspace_id}", tags=["MongoDB"])
async def load_workspace(workspace_id: str, db=Depends(get_db)):
    oid = _validate_object_id(workspace_id)
    doc = await db.workspaces.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return _serialize_doc(doc)

@app.get("/workspace/user/{user_id}", tags=["MongoDB"])
async def list_workspaces(user_id: str, db=Depends(get_db)):
    cursor = db.workspaces.find({"user_id": user_id}, {"files": 0}).sort("updated_at", -1)
    docs = await cursor.to_list(length=100)
    return {"workspaces": [_serialize_doc(d) for d in docs]}

@app.delete("/workspace/{workspace_id}", tags=["MongoDB"])
async def delete_workspace(workspace_id: str, db=Depends(get_db)):
    oid        = _validate_object_id(workspace_id)
    ws_result  = await db.workspaces.delete_one({"_id": oid})
    chat_result = await db.chat_history.delete_many({"workspace_id": workspace_id})
    if ws_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return {
        "message": "Workspace deleted.",
        "files_deleted": ws_result.deleted_count,
        "chat_messages_deleted": chat_result.deleted_count,
    }

@app.post("/chat/save", tags=["MongoDB"])
async def save_chat_history(payload: ChatHistorySaveRequest, db=Depends(get_db)):
    now = _now()
    messages_with_ts = []
    for msg in payload.messages:
        m = msg.model_dump()
        if not m.get("timestamp"):
            m["timestamp"] = now.isoformat()
        messages_with_ts.append(m)
    await db.chat_history.find_one_and_update(
        {"workspace_id": payload.workspace_id, "user_id": payload.user_id},
        {"$set": {"messages": messages_with_ts, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"message": "Chat history saved.", "message_count": len(messages_with_ts)}

@app.get("/chat/{workspace_id}", tags=["MongoDB"])
async def load_chat_history(workspace_id: str, db=Depends(get_db)):
    doc = await db.chat_history.find_one({"workspace_id": workspace_id})
    if not doc:
        return {"messages": [], "workspace_id": workspace_id}
    return _serialize_doc(doc)

@app.delete("/chat/{workspace_id}", tags=["MongoDB"])
async def clear_chat_history(workspace_id: str, db=Depends(get_db)):
    result = await db.chat_history.delete_many({"workspace_id": workspace_id})
    return {"message": "Chat history cleared.", "deleted_count": result.deleted_count}


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 2 — GITHUB ENDPOINTS  ███████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

class GitHubCloneRequest(BaseModel):
    repo_url:     str
    token:        Optional[str] = None
    branch:       Optional[str] = "main"
    workspace_id: Optional[str] = None
    user_id:      Optional[str] = None

class GitHubCommitRequest(BaseModel):
    repo_full_name: str
    branch:         str = "main"
    commit_message: str
    files:          List[FileObject]
    token:          Optional[str] = None

class GitHubRepoInfoRequest(BaseModel):
    token:          Optional[str] = None
    repo_full_name: str

def _resolve_github_token(request_token: Optional[str]) -> str:
    token = request_token or GITHUB_TOKEN
    if not token:
        raise HTTPException(status_code=400, detail="No GitHub token provided.")
    return token

_TEXT_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".md", ".py", ".sh"}
_SKIP_DIRS       = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}

def _read_directory_as_files(root: str, max_files: int = 200) -> List[dict]:
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for filename in filenames:
            if len(results) >= max_files:
                break
            full_path = os.path.join(dirpath, filename)
            rel_path  = os.path.relpath(full_path, root).replace("\\", "/")
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _TEXT_EXTENSIONS and filename.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                    results.append({"filename": rel_path, "language": "plaintext", "code": fh.read()})
            except OSError:
                continue
    return results

@app.post("/github/clone", tags=["GitHub"])
async def github_clone(payload: GitHubCloneRequest, db=Depends(get_db)):
    token            = _resolve_github_token(payload.token)
    authenticated_url = re.sub(r"https://", f"https://{token}@", payload.repo_url)
    tmp_dir          = tempfile.mkdtemp(prefix="ethrix_clone_")
    try:
        git.Repo.clone_from(authenticated_url, tmp_dir, branch=payload.branch, depth=1)
        files = _read_directory_as_files(tmp_dir)
    except git.exc.GitCommandError as e:
        raise HTTPException(status_code=422, detail=f"Git clone failed: {str(e)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    workspace_id = None
    if payload.workspace_id and payload.user_id:
        save_payload = WorkspaceSaveRequest(
            user_id=payload.user_id,
            name=f"[GitHub] {payload.repo_url.split('/')[-1]}",
            files=[FileObject(**f) for f in files],
        )
        result       = await save_workspace(save_payload, db)
        workspace_id = result["workspace_id"]

    return {"message": f"Cloned {len(files)} files successfully.", "files": files, "workspace_id": workspace_id}

@app.post("/github/commit-push", tags=["GitHub"])
async def github_commit_push(payload: GitHubCommitRequest):
    token = _resolve_github_token(payload.token)
    try:
        gh   = Github(token)
        repo = gh.get_repo(payload.repo_full_name)
    except GithubException as e:
        raise HTTPException(status_code=422, detail=str(e))

    committed_files, errors = [], []
    for file_obj in payload.files:
        try:
            file_content = file_obj.code.encode("utf-8")
            file_path    = file_obj.filename
            try:
                existing = repo.get_contents(file_path, ref=payload.branch)
                repo.update_file(file_path, payload.commit_message, file_content, existing.sha, branch=payload.branch)
                action = "updated"
            except GithubException as ge:
                if ge.status == 404:
                    repo.create_file(file_path, payload.commit_message, file_content, branch=payload.branch)
                    action = "created"
                else:
                    raise
            committed_files.append({"filename": file_path, "action": action})
        except GithubException as e:
            errors.append({"filename": file_obj.filename, "error": str(e)})

    return {"message": f"Committed {len(committed_files)} files.", "committed_files": committed_files, "errors": errors}

@app.post("/github/repo-info", tags=["GitHub"])
async def github_repo_info(payload: GitHubRepoInfoRequest):
    token = _resolve_github_token(payload.token)
    try:
        gh   = Github(token)
        repo = gh.get_repo(payload.repo_full_name)
        return {
            "name":           repo.full_name,
            "description":    repo.description,
            "private":        repo.private,
            "default_branch": repo.default_branch,
            "stars":          repo.stargazers_count,
            "html_url":       repo.html_url,
        }
    except GithubException as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 3 — GOOGLE DRIVE ENDPOINTS  █████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def _build_oauth_flow() -> Flow:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google OAuth2 not configured.")
    client_config = {
        "web": {
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=_DRIVE_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

@app.get("/drive/auth", tags=["Google Drive"])
async def drive_auth_start():
    flow      = _build_oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _drive_sessions[state] = {"status": "pending"}
    return {"auth_url": auth_url, "state": state}

@app.get("/drive/callback", tags=["Google Drive"])
async def drive_auth_callback(code: str, state: str):
    if state not in _drive_sessions:
        raise HTTPException(status_code=400, detail="Invalid state token.")
    flow = _build_oauth_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    _drive_sessions[state] = {
        "status":        "authenticated",
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
    }
    return RedirectResponse(url="/?drive_connected=1")

@app.get("/drive/token/{state}", tags=["Google Drive"])
async def get_drive_token(state: str):
    session = _drive_sessions.get(state)
    if not session:
        raise HTTPException(status_code=404, detail="State token not found.")
    return session

class DriveUploadRequest(BaseModel):
    files:         List[FileObject]
    zip_filename:  str           = Field("ethrix-forge-workspace.zip")
    folder_id:     Optional[str] = None
    token:         str
    refresh_token: Optional[str] = None

@app.post("/drive/upload-workspace", tags=["Google Drive"])
async def drive_upload_workspace(payload: DriveUploadRequest):
    creds = Credentials(
        token=payload.token,
        refresh_token=payload.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_obj in payload.files:
            zf.writestr(file_obj.filename, file_obj.code)
    zip_buffer.seek(0)

    service  = build("drive", "v3", credentials=creds, cache_discovery=False)
    metadata = {"name": payload.zip_filename}
    if payload.folder_id:
        metadata["parents"] = [payload.folder_id]

    media  = MediaIoBaseUpload(zip_buffer, mimetype="application/zip", resumable=True)
    result = service.files().create(
        body=metadata, media_body=media, fields="id, name, webViewLink, size"
    ).execute()
    return {
        "message":       "Uploaded successfully.",
        "file_id":       result.get("id"),
        "web_view_link": result.get("webViewLink"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ███  AI GATEWAY ROUTE  ██████████████████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/agent/generate", response_model=AgentResponse, tags=["AI Gateway"])
async def agent_generate(request: AgentRequest):
    """
    Agentic code generation / editing endpoint for Ethrix-Forge.
    Accepts the user prompt + existing project files as context,
    returns only the files that were created or modified.
    """
    return await run_agentic_workflow(request)


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH & ROOT
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
async def root():
    return {"service": "Ethrix-Forge Backend", "status": "online", "docs": "/docs"}

@app.get("/health", tags=["Health"])
async def health_check():
    db_status = "disconnected"
    if _mongo_client:
        try:
            await _mongo_client.admin.command("ping")
            db_status = "connected"
        except Exception:
            pass
    return {
        "status":     "ok" if db_status == "connected" else "degraded",
        "database":   db_status,
        "ai_gateway": {
            "gemini_configured":     bool(GEMINI_API_KEY),
            "openrouter_configured": bool(OPENROUTER_API_KEY),
            "groq_configured":       bool(GROQ_API_KEY),
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False, log_level="info")