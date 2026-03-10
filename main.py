"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         ETHRIX-FORGE — FASTAPI CLOUD SYNC & BACKEND ENGINE                  ║
║         main.py  |  Deployed on Hugging Face Spaces (Docker)                ║
║                                                                              ║
║  Modules:                                                                    ║
║    1. MongoDB  — Workspace & Chat History persistence (motor)                ║
║    2. GitHub   — Clone / Commit / Push via PyGithub + GitPython              ║
║    3. Google Drive — OAuth2 ZIP upload                                       ║
║    4. AI Gateway — Secure proxy for Gemini & Groq (keys from HF env)        ║
╚══════════════════════════════════════════════════════════════════════════════╝

HUGGING FACE SPACE ENVIRONMENT VARIABLES (set in Space Settings → Variables):
  MONGODB_URI           — MongoDB Atlas connection string
  GEMINI_API_KEY        — Google AI Studio key
  GROQ_API_KEY          — Groq Cloud key
  GITHUB_TOKEN          — GitHub Personal Access Token (optional default)
  GOOGLE_CLIENT_ID      — Google OAuth2 Client ID
  GOOGLE_CLIENT_SECRET  — Google OAuth2 Client Secret
  GOOGLE_REDIRECT_URI   — OAuth2 callback URL (e.g. https://your-space.hf.space/drive/callback)
  SECRET_KEY            — Random secret for session signing (generate with: openssl rand -hex 32)
"""

import os
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
from google import genai
import asyncio
import logging

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ethrix-forge")

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────────────────────
MONGODB_URI          = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY         = os.getenv("GROQ_API_KEY", "")
GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN", "")           # optional server-side default
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/drive/callback")
SECRET_KEY           = os.getenv("SECRET_KEY", uuid.uuid4().hex)  # fallback for dev only

# Hugging Face Spaces runs on port 7860 by default
PORT = int(os.getenv("PORT", 7860))

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
# For production, replace with Redis or a DB-backed store.
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
        # Ping to verify connection
        await _mongo_client.admin.command("ping")
        log.info("✅ MongoDB connected.")
        # Create indexes
        db = _mongo_client["ethrix_forge"]
        await db.workspaces.create_index("user_id")
        await db.workspaces.create_index("updated_at")
        await db.chat_history.create_index("workspace_id")
        await db.chat_history.create_index("user_id")
        log.info("✅ MongoDB indexes ensured.")
    except Exception as exc:
        log.error(f"❌ MongoDB connection failed: {exc}")
        # Don't crash — endpoints will return 503 gracefully

    yield  # ← app runs here

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

# ── CORS ──────────────────────────────────────────────────────────────────────
# In production, restrict allow_origins to your HF Space / Vercel URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # ← tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_doc(doc: dict) -> dict:
    """Convert MongoDB ObjectId → str for JSON serialisation."""
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
# ███  MODULE 1 — MONGODB  ████████████████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

# ── Pydantic Models ──────────────────────────────────────────────────────────

class FileObject(BaseModel):
    """A single code file in the workspace."""
    filename: str = Field(..., example="index.html")
    language: str = Field(..., example="html")
    code:     str = Field(..., example="<!DOCTYPE html>...")


class WorkspaceSaveRequest(BaseModel):
    """Payload to save/update a workspace."""
    user_id:    str             = Field(..., example="user_abc123")
    name:       str             = Field(..., example="My Landing Page")
    files:      List[FileObject]
    metadata:   Optional[dict]  = Field(default_factory=dict)


class WorkspaceResponse(BaseModel):
    workspace_id: str
    user_id:      str
    name:         str
    files:        List[dict]
    metadata:     dict
    created_at:   str
    updated_at:   str


class ChatMessage(BaseModel):
    """A single chat message in the AI conversation history."""
    role:    str = Field(..., example="user")       # "user" | "assistant" | "system"
    content: str
    timestamp: Optional[str] = None


class ChatHistorySaveRequest(BaseModel):
    workspace_id: str
    user_id:      str
    messages:     List[ChatMessage]


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/workspace/save", tags=["MongoDB"])
async def save_workspace(
    payload: WorkspaceSaveRequest,
    db=Depends(get_db),
):
    """
    Create or update a workspace (files + metadata).
    If a workspace already exists for this user_id + name, it is overwritten.
    Returns the workspace_id.
    """
    now = _now()
    doc = {
        "user_id":    payload.user_id,
        "name":       payload.name,
        "files":      [f.model_dump() for f in payload.files],
        "metadata":   payload.metadata or {},
        "updated_at": now,
    }

    # Upsert by user_id + name so the user doesn't accumulate duplicate workspaces
    result = await db.workspaces.find_one_and_update(
        {"user_id": payload.user_id, "name": payload.name},
        {
            "$set": doc,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
        return_document=True,
    )

    if result is None:
        # Upsert inserted a new doc — fetch it
        result = await db.workspaces.find_one(
            {"user_id": payload.user_id, "name": payload.name}
        )

    workspace_id = str(result["_id"])
    log.info(f"Workspace saved: {workspace_id} for user {payload.user_id}")
    return {"workspace_id": workspace_id, "message": "Workspace saved successfully."}


@app.get("/workspace/{workspace_id}", tags=["MongoDB"])
async def load_workspace(workspace_id: str, db=Depends(get_db)):
    """Load a full workspace by its MongoDB ObjectId."""
    oid = _validate_object_id(workspace_id)
    doc = await db.workspaces.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return _serialize_doc(doc)


@app.get("/workspace/user/{user_id}", tags=["MongoDB"])
async def list_workspaces(user_id: str, db=Depends(get_db)):
    """
    List all workspaces belonging to a user (without file contents for efficiency).
    """
    cursor = db.workspaces.find(
        {"user_id": user_id},
        {"files": 0},           # Exclude file blobs from listing
    ).sort("updated_at", -1)

    docs = await cursor.to_list(length=100)
    return {"workspaces": [_serialize_doc(d) for d in docs]}


@app.delete("/workspace/{workspace_id}", tags=["MongoDB"])
async def delete_workspace(workspace_id: str, db=Depends(get_db)):
    """Permanently delete a workspace and its associated chat history."""
    oid = _validate_object_id(workspace_id)
    ws_result = await db.workspaces.delete_one({"_id": oid})
    chat_result = await db.chat_history.delete_many({"workspace_id": workspace_id})

    if ws_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")

    return {
        "message": "Workspace deleted.",
        "files_deleted": ws_result.deleted_count,
        "chat_messages_deleted": chat_result.deleted_count,
    }


# ── Chat History ─────────────────────────────────────────────────────────────

@app.post("/chat/save", tags=["MongoDB"])
async def save_chat_history(payload: ChatHistorySaveRequest, db=Depends(get_db)):
    """
    Overwrite (replace) the chat history for a given workspace.
    Each save replaces the full message array — the frontend manages the list.
    """
    now = _now()
    messages_with_ts = []
    for msg in payload.messages:
        m = msg.model_dump()
        if not m.get("timestamp"):
            m["timestamp"] = now.isoformat()
        messages_with_ts.append(m)

    await db.chat_history.find_one_and_update(
        {"workspace_id": payload.workspace_id, "user_id": payload.user_id},
        {
            "$set": {
                "messages":   messages_with_ts,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return {"message": "Chat history saved.", "message_count": len(messages_with_ts)}


@app.get("/chat/{workspace_id}", tags=["MongoDB"])
async def load_chat_history(workspace_id: str, db=Depends(get_db)):
    """Load the full chat history for a workspace."""
    doc = await db.chat_history.find_one({"workspace_id": workspace_id})
    if not doc:
        return {"messages": [], "workspace_id": workspace_id}
    return _serialize_doc(doc)


@app.delete("/chat/{workspace_id}", tags=["MongoDB"])
async def clear_chat_history(workspace_id: str, db=Depends(get_db)):
    """Delete all chat messages for a workspace."""
    result = await db.chat_history.delete_many({"workspace_id": workspace_id})
    return {"message": "Chat history cleared.", "deleted_count": result.deleted_count}


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 2 — GITHUB  █████████████████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

class GitHubCloneRequest(BaseModel):
    """Clone a GitHub repository into the workspace."""
    repo_url:     str  = Field(..., example="https://github.com/owner/repo")
    token:        Optional[str] = Field(None, description="GitHub PAT. Falls back to server GITHUB_TOKEN.")
    branch:       Optional[str] = Field("main", description="Branch to clone")
    workspace_id: Optional[str] = Field(None, description="Auto-save to this workspace after cloning")
    user_id:      Optional[str] = None


class GitHubCommitRequest(BaseModel):
    """Commit and push files to a GitHub repository."""
    repo_full_name: str  = Field(..., example="owner/repo")  # e.g. "torvalds/linux"
    branch:         str  = Field("main")
    commit_message: str  = Field(..., example="feat: update from Ethrix-Forge")
    files:          List[FileObject]
    token:          Optional[str] = None


class GitHubRepoInfoRequest(BaseModel):
    token:         Optional[str] = None
    repo_full_name: str


# ── Helper: resolve token ─────────────────────────────────────────────────────

def _resolve_github_token(request_token: Optional[str]) -> str:
    token = request_token or GITHUB_TOKEN
    if not token:
        raise HTTPException(
            status_code=400,
            detail="No GitHub token provided and GITHUB_TOKEN env var is not set."
        )
    return token


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/github/clone", tags=["GitHub"])
async def github_clone(payload: GitHubCloneRequest, db=Depends(get_db)):
    """
    Clone a GitHub repository into a temp directory, read all text files,
    and return them as a FileObject array (optionally auto-saving to MongoDB).
    """
    token = _resolve_github_token(payload.token)

    # Inject token into URL for private repo support
    authenticated_url = _inject_token_into_git_url(payload.repo_url, token)

    tmp_dir = tempfile.mkdtemp(prefix="ethrix_clone_")
    try:
        log.info(f"Cloning {payload.repo_url} (branch: {payload.branch}) → {tmp_dir}")
        git.Repo.clone_from(
            authenticated_url,
            tmp_dir,
            branch=payload.branch,
            depth=1,   # Shallow clone — faster, no full history needed
        )
        files = _read_directory_as_files(tmp_dir)
        log.info(f"Cloned {len(files)} files from {payload.repo_url}")

    except git.exc.GitCommandError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Git clone failed: {e.stderr.strip() if e.stderr else str(e)}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Optional: auto-save to MongoDB
    workspace_id = None
    if payload.workspace_id and payload.user_id:
        save_payload = WorkspaceSaveRequest(
            user_id=payload.user_id,
            name=f"[GitHub] {payload.repo_url.split('/')[-1]}",
            files=[FileObject(**f) for f in files],
        )
        result = await save_workspace(save_payload, db)
        workspace_id = result["workspace_id"]

    return {
        "message":      f"Cloned {len(files)} files successfully.",
        "files":        files,
        "workspace_id": workspace_id,
    }


@app.post("/github/commit-push", tags=["GitHub"])
async def github_commit_push(payload: GitHubCommitRequest):
    """
    Commit files to a GitHub repository using the GitHub Contents API.
    Creates or updates each file, then creates a commit.
    Works without needing a local git installation.
    """
    token = _resolve_github_token(payload.token)

    try:
        gh   = Github(token)
        repo = gh.get_repo(payload.repo_full_name)
    except GithubException as e:
        raise HTTPException(
            status_code=422,
            detail=f"GitHub API error accessing '{payload.repo_full_name}': {e.data.get('message', str(e))}"
        )

    committed_files = []
    errors = []

    for file_obj in payload.files:
        try:
            file_content = file_obj.code.encode("utf-8")
            file_path    = file_obj.filename

            # Try to get existing file SHA (required for updates)
            try:
                existing = repo.get_contents(file_path, ref=payload.branch)
                repo.update_file(
                    path=file_path,
                    message=payload.commit_message,
                    content=file_content,
                    sha=existing.sha,
                    branch=payload.branch,
                )
                action = "updated"
            except GithubException as ge:
                if ge.status == 404:
                    repo.create_file(
                        path=file_path,
                        message=payload.commit_message,
                        content=file_content,
                        branch=payload.branch,
                    )
                    action = "created"
                else:
                    raise

            committed_files.append({"filename": file_path, "action": action})
            log.info(f"GitHub: {action} '{file_path}' in {payload.repo_full_name}")

        except GithubException as e:
            errors.append({
                "filename": file_obj.filename,
                "error":    e.data.get("message", str(e)),
            })

    return {
        "message":         f"Committed {len(committed_files)} files to {payload.repo_full_name}@{payload.branch}.",
        "committed_files": committed_files,
        "errors":          errors,
        "repo_url":        f"https://github.com/{payload.repo_full_name}",
    }


@app.post("/github/repo-info", tags=["GitHub"])
async def github_repo_info(payload: GitHubRepoInfoRequest):
    """Fetch basic repository metadata (name, stars, branches, last commit)."""
    token = _resolve_github_token(payload.token)
    try:
        gh   = Github(token)
        repo = gh.get_repo(payload.repo_full_name)
        branches = [b.name for b in repo.get_branches()]
        commit = repo.get_commits()[0]
        return {
            "name":          repo.full_name,
            "description":   repo.description,
            "private":       repo.private,
            "default_branch": repo.default_branch,
            "branches":      branches,
            "stars":         repo.stargazers_count,
            "last_commit":   {
                "sha":     commit.sha[:7],
                "message": commit.commit.message.split("\n")[0],
                "author":  commit.commit.author.name,
                "date":    commit.commit.author.date.isoformat(),
            },
            "html_url":      repo.html_url,
        }
    except GithubException as e:
        raise HTTPException(status_code=422, detail=e.data.get("message", str(e)))


# ── Git helpers ───────────────────────────────────────────────────────────────

def _inject_token_into_git_url(url: str, token: str) -> str:
    """Turn https://github.com/... → https://TOKEN@github.com/..."""
    return re.sub(r"https://", f"https://{token}@", url)


# Text-based extensions we'll read when importing a cloned repo
_TEXT_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".scss", ".sass",
    ".json", ".md", ".txt", ".py", ".rb", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".sh", ".bash", ".yml", ".yaml", ".xml", ".sql", ".php", ".kt",
    ".swift", ".dart", ".vue", ".svelte", ".toml", ".ini", ".env.example",
    ".gitignore", ".dockerignore", "dockerfile", "makefile",
}

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}


def _read_directory_as_files(root: str, max_files: int = 200) -> List[dict]:
    """Walk a directory and return text files as FileObject-compatible dicts."""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for filename in filenames:
            if len(results) >= max_files:
                break
            full_path = os.path.join(dirpath, filename)
            rel_path  = os.path.relpath(full_path, root).replace("\\", "/")
            ext       = os.path.splitext(filename)[1].lower()

            if ext not in _TEXT_EXTENSIONS and filename.lower() not in _TEXT_EXTENSIONS:
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                    code = fh.read()
                results.append({
                    "filename": rel_path,
                    "language": _ext_to_language(ext),
                    "code":     code,
                })
            except OSError:
                continue

    return results


def _ext_to_language(ext: str) -> str:
    mapping = {
        ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript",
        ".html": "html", ".htm": "html",
        ".css": "css", ".scss": "scss", ".sass": "sass",
        ".json": "json", ".md": "markdown",
        ".py": "python", ".rb": "ruby", ".go": "go",
        ".rs": "rust", ".java": "java", ".c": "c",
        ".cpp": "cpp", ".sh": "shell", ".bash": "shell",
        ".yml": "yaml", ".yaml": "yaml", ".xml": "xml",
        ".sql": "sql", ".php": "php", ".kt": "kotlin",
        ".swift": "swift", ".dart": "dart",
        ".vue": "html", ".svelte": "html",
        ".toml": "ini", ".ini": "ini",
    }
    return mapping.get(ext, "plaintext")


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 3 — GOOGLE DRIVE  ███████████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════

# Drive scopes required
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _build_oauth_flow() -> Flow:
    """Construct a google-auth-oauthlib Flow from environment credentials."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth2 is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )
    client_config = {
        "web": {
            "client_id":                  GOOGLE_CLIENT_ID,
            "client_secret":              GOOGLE_CLIENT_SECRET,
            "auth_uri":                   "https://accounts.google.com/o/oauth2/auth",
            "token_uri":                  "https://oauth2.googleapis.com/token",
            "redirect_uris":              [GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=_DRIVE_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/drive/auth", tags=["Google Drive"])
async def drive_auth_start():
    """
    Step 1 of OAuth2: generate the Google authorisation URL.
    The frontend redirects the user to the returned `auth_url`.
    A `state` token is stored server-side to validate the callback.
    """
    flow = _build_oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # Store state so the callback can verify it
    _drive_sessions[state] = {"status": "pending"}
    return {"auth_url": auth_url, "state": state}


@app.get("/drive/callback", tags=["Google Drive"])
async def drive_auth_callback(code: str, state: str):
    """
    Step 2 of OAuth2: Google redirects here with an auth code.
    Exchange it for tokens and store them against the state key.
    The frontend polls /drive/token/{state} to retrieve credentials.
    """
    if state not in _drive_sessions:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state token.")

    flow = _build_oauth_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {str(e)}")

    creds = flow.credentials
    _drive_sessions[state] = {
        "status":        "authenticated",
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes or _DRIVE_SCOPES),
    }
    log.info(f"Drive OAuth2 completed for state={state[:8]}…")
    # Redirect to a frontend page that shows "Connected!" and closes the popup
    return RedirectResponse(url="/?drive_connected=1")


@app.get("/drive/token/{state}", tags=["Google Drive"])
async def get_drive_token(state: str):
    """
    Frontend polls this endpoint after redirecting the user to /drive/auth.
    Returns credential data when auth is complete.
    """
    session = _drive_sessions.get(state)
    if not session:
        raise HTTPException(status_code=404, detail="State token not found.")
    return session


class DriveUploadRequest(BaseModel):
    """Upload the workspace as a ZIP to Google Drive."""
    files:        List[FileObject]
    zip_filename: str             = Field("ethrix-forge-workspace.zip")
    folder_id:    Optional[str]   = Field(None, description="Google Drive folder ID. Uploads to root if None.")
    # Credentials returned by /drive/token/{state}
    token:         str
    refresh_token: Optional[str]  = None
    token_uri:     str             = "https://oauth2.googleapis.com/token"
    client_id:     Optional[str]  = None
    client_secret: Optional[str]  = None
    scopes:        Optional[List[str]] = None


@app.post("/drive/upload-workspace", tags=["Google Drive"])
async def drive_upload_workspace(payload: DriveUploadRequest):
    """
    Create a ZIP archive of all workspace files in memory and upload it
    directly to the user's Google Drive. Returns the Drive file ID and URL.
    """
    # Build credentials
    try:
        creds = Credentials(
            token=payload.token,
            refresh_token=payload.refresh_token,
            token_uri=payload.token_uri,
            client_id=payload.client_id or GOOGLE_CLIENT_ID,
            client_secret=payload.client_secret or GOOGLE_CLIENT_SECRET,
            scopes=payload.scopes or _DRIVE_SCOPES,
        )
        # Refresh if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired Google credentials: {str(e)}")

    # Build ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_obj in payload.files:
            zf.writestr(file_obj.filename, file_obj.code)
    zip_buffer.seek(0)

    # Upload to Drive
    try:
        service  = build("drive", "v3", credentials=creds, cache_discovery=False)
        metadata = {"name": payload.zip_filename}
        if payload.folder_id:
            metadata["parents"] = [payload.folder_id]

        media = MediaIoBaseUpload(zip_buffer, mimetype="application/zip", resumable=True)
        result = service.files().create(
            body=metadata,
            media_body=media,
            fields="id, name, webViewLink, size",
        ).execute()

        log.info(f"Drive upload: {result.get('name')} (id={result.get('id')})")
        return {
            "message":      "Workspace uploaded to Google Drive successfully.",
            "file_id":      result.get("id"),
            "file_name":    result.get("name"),
            "web_view_link": result.get("webViewLink"),
            "size_bytes":   result.get("size"),
        }
    except Exception as e:
        log.error(f"Drive upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Google Drive upload failed: {str(e)}")


@app.get("/drive/files", tags=["Google Drive"])
async def drive_list_files(
    token:         str,
    refresh_token: Optional[str] = None,
    folder_id:     Optional[str] = None,
):
    """List ZIP files in Google Drive (or a specific folder)."""
    try:
        creds = Credentials(
            token=token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=_DRIVE_SCOPES,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        query = "mimeType='application/zip' and trashed=false"
        if folder_id:
            query += f" and '{folder_id}' in parents"

        results = service.files().list(
            q=query,
            fields="files(id, name, size, createdTime, webViewLink)",
            orderBy="createdTime desc",
            pageSize=50,
        ).execute()

        return {"files": results.get("files", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═════════════════════════════════════════════════════════════════════════════
# ███  MODULE 4 — SECURE AI GATEWAY  ██████████████████████████████████████████
# ═════════════════════════════════════════════════════════════════════════════
#
# The React frontend sends prompts here. The backend appends the real API keys
# (stored as HF Secrets) before forwarding to the AI providers.
# The frontend NEVER sees the raw API keys.
# ─────────────────────────────────────────────────────────────────────────────

# ── Strict JSON Auto-Coding System Prompt ────────────────────────────────────
# (Mirrors useAIService.js for consistency — the gateway can also be used
#  as a backend-only generation path without the frontend SDK.)

SYSTEM_PROMPT = """You are Ethrix, an elite autonomous software engineer inside the Ethrix-Forge AI IDE. Your sole function is to generate complete, production-ready source code.

ABSOLUTE OUTPUT RULES — NEVER VIOLATE THESE:
1. Your response MUST be a single, raw, valid JSON array. Nothing else.
2. Each element: {"filename": "...", "language": "...", "code": "..."}
3. NO markdown fences. NO backticks. NO explanation. NO preamble.
4. All code must be complete and untruncated.
5. Escape double-quotes inside "code" as \\", newlines as \\n.

You are a JSON-outputting machine. You do not converse."""

# ── Models ────────────────────────────────────────────────────────────────────

class AIGatewayRequest(BaseModel):
    prompt:   str  = Field(..., description="User's coding request")
    provider: str  = Field("gemini", description="'gemini' or 'groq'")
    model:    Optional[str] = None


class AIGatewayResponse(BaseModel):
    files:        List[dict]
    raw_response: str
    provider:     str
    model:        str


# ── Naya Gemini SDK Import ──
log = logging.getLogger("ethrix-forge")

# 🚀 Shantanu's Master Fallback List (Top Free-Tier Models)
FALLBACK_MODELS = [
    "gemini-1.5-flash",       # Sabse fast aur stable (Top Priority)
    "gemini-1.5-pro",         # Heavy coding ke liye best
    "gemini-1.5-flash-8b",    # Naya aur super lightweight model
    "gemini-2.0-flash",                    # Naye accounts ke liye sabse stable
    "gemini-2.0-flash-lite-preview-02-05", # 2.0 ka lite version
    "gemini-1.0-pro"          # Sabse purana aur reliable backup
]

async def _call_gemini_gateway(prompt: str, requested_model: str) -> str:
    """Bulletproof Gemini Call with Shantanu's Fallback Engine"""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is missing!")

    client = genai.Client(api_key=GEMINI_API_KEY)
    full_prompt = f"{SYSTEM_PROMPT}\n\nUser Request:\n{prompt}"
    last_error = ""

    # Ek-ek karke saare models try karenge jab tak success na mile!
    for current_model in FALLBACK_MODELS:
        log.info(f"🔄 Trying Gemini model: {current_model}...")
        try:
            def sync_gemini_call(m):
                return client.models.generate_content(
                    model=m, 
                    contents=full_prompt
                )
                
            response = await asyncio.to_thread(sync_gemini_call, current_model)
            
            log.info(f"✅ Gemini Success with {current_model}! Raw Response: {response.text[:100]}...") 
            return response.text

        except Exception as e:
            # Agar fail hua, toh error log karke agla model try karega
            error_msg = str(e)
            log.warning(f"⚠️ Model {current_model} failed: {error_msg}")
            last_error = error_msg
            continue # Agle model par jao

    # Agar saare 5 models fail ho gaye (jo ki almost impossible hai)
    log.error(f"❌ ALL GEMINI MODELS FAILED. Last error: {last_error}")
    raise HTTPException(status_code=502, detail=f"All Gemini models exhausted. Last Error: {last_error}")


async def _call_groq_gateway(prompt: str, model: str) -> str:
    """Call Groq Chat Completions API."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not set on the server.")

    url  = "https://api.groq.com/openai/v1/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens":  8192,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url, json=body,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"}
        )

    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Groq rate limit exceeded. Please wait and retry.")
    if resp.status_code in (401, 403):
        raise HTTPException(status_code=502, detail="Groq API key is invalid or unauthorised.")
    if not resp.is_success:
        detail = resp.json().get("error", {}).get("message", resp.text)
        raise HTTPException(status_code=502, detail=f"Groq error: {detail}")

    data = resp.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


# ── JSON Parser (mirrors frontend logic) ─────────────────────────────────────

def _parse_gateway_response(raw: str, provider: str) -> List[dict]:
    if not raw or not raw.strip():
        raise HTTPException(status_code=502, detail=f"{provider} returned an empty response.")

    text = raw.strip()

    # Strategy 1: direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        # Groq json_object mode may wrap the array in a key
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Strategy 3: extract first [...] block
    array_match = re.search(r"\[[\s\S]*\]", text)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=422,
                detail=f"AI returned malformed JSON from {provider}. Parse error: {str(e)}"
            )

    raise HTTPException(
        status_code=422,
        detail=f"No valid JSON array found in {provider} response. Preview: {text[:300]}"
    )


# ── Default models per provider ───────────────────────────────────────────────
_GATEWAY_DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "groq":   "llama-3.3-70b-versatile",
}


# ── Main Gateway Endpoint ─────────────────────────────────────────────────────

@app.post("/ai/generate", response_model=AIGatewayResponse, tags=["AI Gateway"])
async def ai_generate(payload: AIGatewayRequest):
    """
    Secure AI code-generation proxy.
    The frontend sends a prompt; the backend appends the real API key and
    forwards to Gemini or Groq. Returns a parsed FileObject array.
    """
    provider = payload.provider.lower()
    model    = payload.model or _GATEWAY_DEFAULT_MODELS.get(provider)

    if not model:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Use 'gemini' or 'groq'."
        )

    log.info(f"AI Gateway request: provider={provider}, model={model}, prompt_len={len(payload.prompt)}")

    if provider == "gemini":
        raw = await _call_gemini_gateway(payload.prompt, model)
    elif provider == "groq":
        raw = await _call_groq_gateway(payload.prompt, model)
    else:
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' is not supported by the gateway.")

    files = _parse_gateway_response(raw, provider)

    return AIGatewayResponse(
        files=files,
        raw_response=raw,
        provider=provider,
        model=model,
    )


@app.get("/ai/providers", tags=["AI Gateway"])
async def ai_providers():
    """
    Returns which providers are configured on the server (without exposing keys).
    The frontend uses this to show/hide provider options.
    """
    return {
        "gemini": {
            "available": bool(GEMINI_API_KEY),
            "models":    ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash"],
        },
        "groq": {
            "available": bool(GROQ_API_KEY),
            "models":    ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH & ROOT
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
async def root():
    return {
        "service":    "Ethrix-Forge Backend",
        "version":    "1.0.0",
        "status":     "online",
        "docs":       "/docs",
        "timestamp":  _now().isoformat(),
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Deep health check — verifies MongoDB connectivity."""
    db_status = "disconnected"
    if _mongo_client:
        try:
            await _mongo_client.admin.command("ping")
            db_status = "connected"
        except Exception:
            db_status = "error"

    return {
        "status":   "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "ai_gateway": {
            "gemini_configured": bool(GEMINI_API_KEY),
            "groq_configured":   bool(GROQ_API_KEY),
        },
        "github_configured": bool(GITHUB_TOKEN),
        "drive_configured":  bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,   # Disable in production
        log_level="info",
    )
