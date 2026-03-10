import os
import json
import asyncio
import logging
from typing import Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from google import genai

# ── LOGGING SETUP ──
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ethrix-forge")

app = FastAPI(title="Ethrix-Forge AI Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════════════════════
#  CLAUDE'S AGENTIC WORKFLOW CODE (Directly inside main.py!)
# ══════════════════════════════════════════════════════════════════════════════

class ExistingFile(BaseModel):
    filename: str
    language: str
    code: str

class AgentRequest(BaseModel):
    prompt: str
    existing_files: List[ExistingFile] = []
    model_preference: str = "gemini"

class GeneratedFile(BaseModel):
    filename: str
    language: str
    code: str

class AgentResponse(BaseModel):
    files: List[GeneratedFile]
    provider_used: str
    total_files_changed: int

AGENTIC_SYSTEM_PROMPT = """
You are Ethrix, an elite Expert Senior Software Architect. 
Your goal is to fulfill the user's request by analyzing the existing codebase and returning ONLY the files that need to be created or modified.

STRICT RULES:
1. You MUST respond with ONLY a valid JSON array of objects.
2. NO markdown formatting, NO backticks (```json), NO explanations, NO preambles.
3. Each object in the array MUST have exactly three string keys: "filename", "language", and "code".
4. If a file does not need changes, DO NOT include it in the output.
5. Provide complete code for the files you do output (no "..." or "insert here" placeholders).

Expected Output Format exactly like this:
[
  {
    "filename": "index.html",
    "language": "html",
    "code": "<!DOCTYPE html>..."
  }
]
"""

def _get_gemini_keys():
    keys = []
    base_key = os.getenv("GEMINI_API_KEY")
    if base_key: keys.append(base_key)
    for i in range(2, 10):
        k = os.getenv(f"GEMINI_API_KEY_{i}")
        if k: keys.append(k)
    return keys

async def _call_gemini_with_fallback(full_prompt: str) -> tuple[str, str]:
    keys = _get_gemini_keys()
    if not keys:
        raise ValueError("No Gemini keys found")
        
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    for key in keys:
        client = genai.Client(api_key=key)
        for model in models_to_try:
            try:
                def sync_call():
                    return client.models.generate_content(
                        model=model, 
                        contents=full_prompt
                    )
                response = await asyncio.to_thread(sync_call)
                return response.text, f"gemini ({model})"
            except Exception as e:
                err_str = str(e)
                log.warning(f"Gemini {model} failed with key ending in ...{key[-4:]}: {err_str}")
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    break # Switch to next API Key
    raise ValueError("All Gemini keys and models exhausted.")

async def _call_openrouter_safe(full_prompt: str) -> tuple[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key: raise ValueError("OpenRouter key missing")
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        res = await client.post(
            "[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "qwen/qwen-2.5-coder-32b-instruct:free",
                "messages": [{"role": "user", "content": full_prompt}]
            }
        )
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"], "openrouter (qwen-2.5)"

async def _call_groq_safe(full_prompt: str) -> tuple[str, str]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: raise ValueError("Groq key missing")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": full_prompt}]
            }
        )
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"], "groq (llama-3.3)"

def _parse_files_from_response(raw_text: str) -> list[dict]:
    text = raw_text.strip()
    if text.startswith("```json"): text = text[7:]
    if text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    text = text.strip()
    
    try:
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON: {e}\nRaw Output: {text[:200]}...")
        raise ValueError("AI did not return valid JSON.")

async def run_agentic_workflow(request: AgentRequest) -> AgentResponse:
    # 1. Build Context
    context_str = "\n".join(
        f"File: {f.filename}\n```{f.language}\n{f.code}\n```" 
        for f in request.existing_files
    )
    full_prompt = f"{AGENTIC_SYSTEM_PROMPT}\n\n--- EXISTING FILES ---\n{context_str}\n\n--- TASK ---\n{request.prompt}"

    # 2. Try Providers
    raw_response, provider = "", ""
    try:
        raw_response, provider = await _call_gemini_with_fallback(full_prompt)
    except Exception as e1:
        log.warning(f"Gemini chain failed: {e1}. Trying OpenRouter...")
        try:
            raw_response, provider = await _call_openrouter_safe(full_prompt)
        except Exception as e2:
            log.warning(f"OpenRouter failed: {e2}. Trying Groq...")
            try:
                raw_response, provider = await _call_groq_safe(full_prompt)
            except Exception as e3:
                raise HTTPException(status_code=502, detail="All AI providers exhausted.")

    # 3. Parse JSON
    try:
        files_data = _parse_files_from_response(raw_response)
        generated_files = [
            GeneratedFile(filename=f["filename"], language=f["language"], code=f["code"])
            for f in files_data if "filename" in f and "code" in f
        ]
        return AgentResponse(
            files=generated_files,
            provider_used=provider,
            total_files_changed=len(generated_files)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
#  FASTAPI ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def read_root():
    return {"status": "Ethrix-Forge API is Running (Agentic Mode)"}

@app.post("/api/agent/generate", response_model=AgentResponse)
async def agent_generate(request: AgentRequest):
    return await run_agentic_workflow(request)