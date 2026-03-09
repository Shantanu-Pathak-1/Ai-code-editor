/**
 * ╔══════════════════════════════════════════════════════════════════════════╗
 * ║         ETHRIX-FORGE — AI API SERVICE INTEGRATION MODULE                ║
 * ║         useAIService.js  |  Custom React Hook                           ║
 * ║                                                                          ║
 * ║  Providers Supported:                                                    ║
 * ║    • Google Gemini  (google-genai SDK — new 2024+ SDK)                  ║
 * ║    • Groq           (OpenAI-compatible REST)                             ║
 * ║    • OpenRouter     (OpenAI-compatible REST, multi-model gateway)        ║
 * ╚══════════════════════════════════════════════════════════════════════════╝
 *
 * USAGE IN App.jsx:
 *   import { useAIService } from './useAIService';
 *
 *   const {
 *     generate,
 *     isLoading,
 *     error,
 *     activeProvider,
 *     setActiveProvider,
 *     apiKey,
 *     setApiKey,
 *     activeModel,
 *     setActiveModel,
 *     lastRawResponse,
 *     retryLastRequest,
 *   } = useAIService();
 *
 *   // Then call:
 *   const files = await generate("Build me a responsive landing page");
 *   // Returns: [{ filename, language, code }, ...] — ready for Monaco injection
 */

import { useState, useCallback, useRef } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// 1. PROVIDER REGISTRY
//    Central configuration for all supported AI providers.
//    Add new providers here without touching hook logic.
// ─────────────────────────────────────────────────────────────────────────────

export const PROVIDERS = {
  GEMINI: "gemini",
  GROQ: "groq",
  OPENROUTER: "openrouter",
};

export const PROVIDER_CONFIG = {
  [PROVIDERS.GEMINI]: {
    label: "Google Gemini",
    sdkType: "gemini",                   // uses google-genai SDK
    defaultModel: "gemini-2.0-flash",
    availableModels: [
      { id: "gemini-2.0-flash",        label: "Gemini 2.0 Flash" },
      { id: "gemini-2.0-flash-lite",   label: "Gemini 2.0 Flash Lite" },
      { id: "gemini-1.5-pro",          label: "Gemini 1.5 Pro" },
      { id: "gemini-1.5-flash",        label: "Gemini 1.5 Flash" },
    ],
    docsUrl: "https://ai.google.dev/gemini-api/docs",
  },
  [PROVIDERS.GROQ]: {
    label: "Groq",
    sdkType: "openai-compat",
    endpoint: "https://api.groq.com/openai/v1/chat/completions",
    defaultModel: "llama-3.3-70b-versatile",
    availableModels: [
      { id: "llama-3.3-70b-versatile",    label: "LLaMA 3.3 70B Versatile" },
      { id: "llama-3.1-8b-instant",       label: "LLaMA 3.1 8B Instant" },
      { id: "mixtral-8x7b-32768",         label: "Mixtral 8x7B" },
      { id: "gemma2-9b-it",               label: "Gemma 2 9B" },
    ],
    docsUrl: "https://console.groq.com/docs/openai",
  },
  [PROVIDERS.OPENROUTER]: {
    label: "OpenRouter",
    sdkType: "openai-compat",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    defaultModel: "anthropic/claude-3.5-sonnet",
    availableModels: [
      { id: "anthropic/claude-3.5-sonnet",       label: "Claude 3.5 Sonnet" },
      { id: "openai/gpt-4o",                     label: "GPT-4o" },
      { id: "openai/gpt-4o-mini",                label: "GPT-4o Mini" },
      { id: "google/gemini-2.0-flash-001",       label: "Gemini 2.0 Flash" },
      { id: "meta-llama/llama-3.3-70b-instruct", label: "LLaMA 3.3 70B" },
      { id: "deepseek/deepseek-r1",              label: "DeepSeek R1" },
    ],
    extraHeaders: {
      "HTTP-Referer": "https://ethrix-forge.dev",  // Replace with your domain
      "X-Title": "Ethrix-Forge IDE",
    },
    docsUrl: "https://openrouter.ai/docs",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// 2. SYSTEM PROMPT
//    Strictly instructs the AI to return ONLY a valid JSON array.
//    No markdown, no prose, no backticks — ever.
// ─────────────────────────────────────────────────────────────────────────────

const SYSTEM_PROMPT = `You are Ethrix, an elite autonomous software engineer embedded inside the Ethrix-Forge AI IDE. Your sole function is to generate complete, production-ready source code in response to user requests.

ABSOLUTE OUTPUT RULES — NEVER VIOLATE THESE:
1. Your response MUST be a single, raw, valid JSON array. Nothing else.
2. The array contains file objects. Each file object MUST have exactly three keys:
   - "filename": the full file name with extension (e.g., "index.html", "styles/main.css", "src/App.jsx")
   - "language": the lowercase language identifier used by Monaco Editor (e.g., "html", "css", "javascript", "typescript", "python", "json")
   - "code": the complete, untruncated source code for that file as a single string
3. DO NOT wrap the JSON in markdown code fences (\`\`\`json ... \`\`\`).
4. DO NOT include any explanation, preamble, commentary, or text before or after the JSON array.
5. DO NOT truncate code. Every file must be fully complete and functional.
6. DO NOT use placeholder comments like "// ... rest of code here".
7. Strings inside the "code" value MUST have all double-quotes escaped as \\", and all newlines as \\n.

VALID OUTPUT EXAMPLE:
[{"filename":"index.html","language":"html","code":"<!DOCTYPE html>\\n<html>\\n<head>\\n  <title>App</title>\\n</head>\\n<body>\\n  <h1>Hello</h1>\\n</body>\\n</html>"},{"filename":"style.css","language":"css","code":"body {\\n  margin: 0;\\n  font-family: sans-serif;\\n}"}]

CODE QUALITY STANDARDS:
- Write modern, idiomatic code for the target language/framework.
- Include all necessary imports, dependencies, and boilerplate.
- Produce fully functional code that runs without modification.
- Separate concerns properly across multiple files when appropriate.
- Use best practices: error handling, accessibility, responsive design where relevant.

You are a machine that outputs JSON. You do not converse. You do not explain. You only output the JSON array.`;

// ─────────────────────────────────────────────────────────────────────────────
// 3. ERROR CLASSES
//    Custom errors for granular error handling in consuming components.
// ─────────────────────────────────────────────────────────────────────────────

export class AIServiceError extends Error {
  constructor(message, code, provider, retryable = false) {
    super(message);
    this.name = "AIServiceError";
    this.code = code;
    this.provider = provider;
    this.retryable = retryable;
    this.timestamp = new Date().toISOString();
  }
}

export const ERROR_CODES = {
  INVALID_API_KEY:      "INVALID_API_KEY",
  RATE_LIMITED:         "RATE_LIMITED",
  QUOTA_EXCEEDED:       "QUOTA_EXCEEDED",
  INVALID_JSON:         "INVALID_JSON",
  EMPTY_RESPONSE:       "EMPTY_RESPONSE",
  NETWORK_ERROR:        "NETWORK_ERROR",
  PROVIDER_ERROR:       "PROVIDER_ERROR",
  NO_API_KEY:           "NO_API_KEY",
  MODEL_NOT_FOUND:      "MODEL_NOT_FOUND",
  CONTEXT_TOO_LONG:     "CONTEXT_TOO_LONG",
  SAFETY_BLOCKED:       "SAFETY_BLOCKED",
  UNKNOWN:              "UNKNOWN",
};

// ─────────────────────────────────────────────────────────────────────────────
// 4. JSON PARSER — Safe, multi-strategy extraction
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Safely extracts and parses a JSON array from an AI text response.
 * Handles cases where the model accidentally wraps output in markdown fences.
 *
 * @param {string} rawText - Raw text response from AI
 * @param {string} provider - Provider name for error attribution
 * @returns {Array<{filename: string, language: string, code: string}>}
 * @throws {AIServiceError} if valid JSON array cannot be extracted
 */
function parseAIResponse(rawText, provider) {
  if (!rawText || typeof rawText !== "string" || rawText.trim().length === 0) {
    throw new AIServiceError(
      "AI returned an empty response. The model may have been rate limited or the request was too large.",
      ERROR_CODES.EMPTY_RESPONSE,
      provider,
      true
    );
  }

  let text = rawText.trim();

  // Strategy 1: Direct parse (model obeyed instructions perfectly)
  try {
    const parsed = JSON.parse(text);
    return validateFileArray(parsed, provider);
  } catch (_) {
    // Fall through to extraction strategies
  }

  // Strategy 2: Strip markdown code fences (```json ... ``` or ``` ... ```)
  const fencePatterns = [
    /^```(?:json)?\s*\n?([\s\S]*?)\n?```$/i,
    /^`([\s\S]*?)`$/,
  ];
  for (const pattern of fencePatterns) {
    const match = text.match(pattern);
    if (match) {
      try {
        const parsed = JSON.parse(match[1].trim());
        return validateFileArray(parsed, provider);
      } catch (_) {
        // Continue to next strategy
      }
    }
  }

  // Strategy 3: Extract the first [...] block found in the string
  const arrayMatch = text.match(/\[[\s\S]*\]/);
  if (arrayMatch) {
    try {
      const parsed = JSON.parse(arrayMatch[0]);
      return validateFileArray(parsed, provider);
    } catch (parseError) {
      throw new AIServiceError(
        `The AI returned malformed JSON that could not be repaired. Parse error: ${parseError.message}. ` +
          `Raw preview: ${text.substring(0, 200)}...`,
        ERROR_CODES.INVALID_JSON,
        provider,
        false
      );
    }
  }

  // All strategies failed
  throw new AIServiceError(
    `No valid JSON array found in the AI response. ` +
      `The model may have ignored formatting instructions. ` +
      `Raw preview: ${text.substring(0, 300)}`,
    ERROR_CODES.INVALID_JSON,
    provider,
    false
  );
}

/**
 * Validates that a parsed value is an array of valid file objects.
 * Auto-repairs common issues (missing language, wrong types).
 */
function validateFileArray(data, provider) {
  if (!Array.isArray(data)) {
    throw new AIServiceError(
      `Expected a JSON array but received ${typeof data}. The AI returned a non-array JSON value.`,
      ERROR_CODES.INVALID_JSON,
      provider,
      false
    );
  }

  if (data.length === 0) {
    throw new AIServiceError(
      "The AI returned an empty file array. No files were generated.",
      ERROR_CODES.EMPTY_RESPONSE,
      provider,
      true
    );
  }

  return data.map((item, index) => {
    if (typeof item !== "object" || item === null) {
      throw new AIServiceError(
        `File at index ${index} is not a valid object.`,
        ERROR_CODES.INVALID_JSON,
        provider,
        false
      );
    }

    const filename = String(item.filename || `file_${index + 1}.txt`).trim();
    const code = String(item.code || "").trim();

    // Auto-infer language from extension if missing
    const language =
      item.language ||
      inferLanguageFromFilename(filename) ||
      "plaintext";

    return {
      id: `${filename}-${Date.now()}-${index}`,  // Unique ID for React keys / Monaco models
      filename,
      language: String(language).toLowerCase().trim(),
      code,
    };
  });
}

/** Maps common file extensions to Monaco Editor language identifiers */
function inferLanguageFromFilename(filename) {
  const ext = filename.split(".").pop()?.toLowerCase();
  const map = {
    js: "javascript", jsx: "javascript", ts: "typescript", tsx: "typescript",
    html: "html", htm: "html", css: "css", scss: "scss", sass: "sass",
    json: "json", md: "markdown", py: "python", rb: "ruby",
    java: "java", go: "go", rs: "rust", cpp: "cpp", c: "c",
    sh: "shell", bash: "shell", yml: "yaml", yaml: "yaml",
    xml: "xml", svg: "xml", sql: "sql", php: "php",
    kt: "kotlin", swift: "swift", dart: "dart",
  };
  return map[ext] || "plaintext";
}

// ─────────────────────────────────────────────────────────────────────────────
// 5. PROVIDER-SPECIFIC API CALLERS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * HTTP status code → structured AIServiceError mapper for OpenAI-compatible APIs
 */
function mapHttpError(status, body, provider) {
  const message = body?.error?.message || body?.message || `HTTP ${status}`;

  switch (status) {
    case 401:
    case 403:
      return new AIServiceError(
        `Invalid or unauthorized API key for ${provider}. Please check your key in Settings. Details: ${message}`,
        ERROR_CODES.INVALID_API_KEY,
        provider,
        false
      );
    case 429: {
      const isQuota =
        message.toLowerCase().includes("quota") ||
        message.toLowerCase().includes("billing");
      return new AIServiceError(
        isQuota
          ? `${provider} quota exceeded. Check your billing dashboard.`
          : `${provider} rate limit hit. Please wait a moment and try again.`,
        isQuota ? ERROR_CODES.QUOTA_EXCEEDED : ERROR_CODES.RATE_LIMITED,
        provider,
        true
      );
    }
    case 404:
      return new AIServiceError(
        `Model not found on ${provider}. Try selecting a different model. Details: ${message}`,
        ERROR_CODES.MODEL_NOT_FOUND,
        provider,
        false
      );
    case 413:
      return new AIServiceError(
        `Your request is too long for this model's context window. Try a simpler prompt or a model with a larger context.`,
        ERROR_CODES.CONTEXT_TOO_LONG,
        provider,
        false
      );
    case 500:
    case 502:
    case 503:
      return new AIServiceError(
        `${provider} server error (${status}). This is a provider-side issue. Retrying may help. Details: ${message}`,
        ERROR_CODES.PROVIDER_ERROR,
        provider,
        true
      );
    default:
      return new AIServiceError(
        `${provider} returned unexpected status ${status}. Details: ${message}`,
        ERROR_CODES.UNKNOWN,
        provider,
        false
      );
  }
}

// ── 5a. GEMINI (google-genai SDK) ────────────────────────────────────────────
/**
 * Calls Gemini using the new `google-genai` SDK.
 *
 * Install: npm install @google/genai
 *
 * The new SDK uses `GoogleGenAI` (not `GoogleGenerativeAI`).
 * generateContent now lives on `ai.models.generateContent(...)`.
 */
async function callGemini({ apiKey, model, userPrompt, signal }) {
  // Dynamic import keeps the SDK optional — won't crash if not installed
  let GoogleGenAI;
  try {
    ({ GoogleGenAI } = await import("@google/genai"));
  } catch {
    throw new AIServiceError(
      'The @google/genai package is not installed. Run: npm install @google/genai',
      ERROR_CODES.PROVIDER_ERROR,
      PROVIDERS.GEMINI,
      false
    );
  }

  const ai = new GoogleGenAI({ apiKey });

  const requestConfig = {
    model,
    contents: [
      {
        role: "user",
        parts: [{ text: userPrompt }],
      },
    ],
    config: {
      systemInstruction: SYSTEM_PROMPT,
      // Gemini 2.0+ supports JSON response mime type — enforce structured output
      responseMimeType: "application/json",
      temperature: 0.2,      // Low temp for deterministic code generation
      maxOutputTokens: 8192,
    },
  };

  let response;
  try {
    response = await ai.models.generateContent(requestConfig);
  } catch (err) {
    // Map Gemini SDK-specific errors
    const msg = err?.message || String(err);

    if (msg.includes("API_KEY_INVALID") || msg.includes("API key not valid")) {
      throw new AIServiceError(
        `Invalid Gemini API key. Please check your key in Settings.`,
        ERROR_CODES.INVALID_API_KEY,
        PROVIDERS.GEMINI,
        false
      );
    }
    if (msg.includes("RESOURCE_EXHAUSTED") || msg.includes("quota")) {
      throw new AIServiceError(
        `Gemini quota exceeded. Check your Google AI Studio dashboard.`,
        ERROR_CODES.QUOTA_EXCEEDED,
        PROVIDERS.GEMINI,
        true
      );
    }
    if (msg.includes("SAFETY") || msg.includes("blocked")) {
      throw new AIServiceError(
        `Gemini blocked this request due to safety filters. Try rephrasing your prompt.`,
        ERROR_CODES.SAFETY_BLOCKED,
        PROVIDERS.GEMINI,
        false
      );
    }
    if (signal?.aborted) return null; // Caller cancelled
    throw new AIServiceError(
      `Gemini SDK error: ${msg}`,
      ERROR_CODES.PROVIDER_ERROR,
      PROVIDERS.GEMINI,
      false
    );
  }

  const rawText = response?.candidates?.[0]?.content?.parts?.[0]?.text ?? "";
  return rawText;
}

// ── 5b. GROQ (OpenAI-compatible REST) ────────────────────────────────────────
async function callGroq({ apiKey, model, userPrompt, signal }) {
  const config = PROVIDER_CONFIG[PROVIDERS.GROQ];

  const body = {
    model,
    messages: [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user",   content: userPrompt },
    ],
    temperature: 0.2,
    max_tokens: 8192,
    // Groq supports OpenAI-style JSON mode
    response_format: { type: "json_object" },
  };

  let res;
  try {
    res = await fetch(config.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") return null;
    throw new AIServiceError(
      `Network error contacting Groq: ${err.message}. Check your internet connection.`,
      ERROR_CODES.NETWORK_ERROR,
      PROVIDERS.GROQ,
      true
    );
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw mapHttpError(res.status, data, PROVIDERS.GROQ);
  }

  return data?.choices?.[0]?.message?.content ?? "";
}

// ── 5c. OPENROUTER (OpenAI-compatible REST, multi-model gateway) ─────────────
async function callOpenRouter({ apiKey, model, userPrompt, signal }) {
  const config = PROVIDER_CONFIG[PROVIDERS.OPENROUTER];

  const body = {
    model,
    messages: [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user",   content: userPrompt },
    ],
    temperature: 0.2,
    max_tokens: 8192,
    response_format: { type: "json_object" },
  };

  let res;
  try {
    res = await fetch(config.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
        ...config.extraHeaders,
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") return null;
    throw new AIServiceError(
      `Network error contacting OpenRouter: ${err.message}. Check your internet connection.`,
      ERROR_CODES.NETWORK_ERROR,
      PROVIDERS.OPENROUTER,
      true
    );
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw mapHttpError(res.status, data, PROVIDERS.OPENROUTER);
  }

  return data?.choices?.[0]?.message?.content ?? "";
}

// ─────────────────────────────────────────────────────────────────────────────
// 6. PROVIDER DISPATCHER
//    Routes a generation request to the correct provider caller.
// ─────────────────────────────────────────────────────────────────────────────

const PROVIDER_CALLERS = {
  [PROVIDERS.GEMINI]:     callGemini,
  [PROVIDERS.GROQ]:       callGroq,
  [PROVIDERS.OPENROUTER]: callOpenRouter,
};

// ─────────────────────────────────────────────────────────────────────────────
// 7. THE HOOK — useAIService
// ─────────────────────────────────────────────────────────────────────────────

/**
 * useAIService — Core AI generation hook for Ethrix-Forge.
 *
 * @param {Object}  [options]
 * @param {string}  [options.initialProvider="gemini"]   - Starting provider key
 * @param {string}  [options.initialApiKey=""]           - Starting API key
 * @param {string}  [options.initialModel]               - Override default model
 * @param {number}  [options.retryAttempts=2]            - Auto-retry count on retryable errors
 * @param {number}  [options.retryDelayMs=1500]          - Base delay between retries (doubles each attempt)
 *
 * @returns {AIServiceHookResult}
 */
export function useAIService({
  initialProvider = PROVIDERS.GEMINI,
  initialApiKey = "",
  initialModel = null,
  retryAttempts = 2,
  retryDelayMs = 1500,
} = {}) {

  // ── State ──────────────────────────────────────────────────────────────────
  const [activeProvider, setActiveProviderState] = useState(initialProvider);
  const [apiKey, setApiKey] = useState(initialApiKey);
  const [activeModel, setActiveModel] = useState(
    initialModel || PROVIDER_CONFIG[initialProvider]?.defaultModel
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);               // AIServiceError | null
  const [lastRawResponse, setLastRawResponse] = useState(null);
  const [lastGeneratedFiles, setLastGeneratedFiles] = useState([]);
  const [requestCount, setRequestCount] = useState(0);   // Useful for analytics/rate tracking

  // AbortController ref — allows cancellation of in-flight requests
  const abortControllerRef = useRef(null);

  // Store the last prompt for retry functionality
  const lastPromptRef = useRef(null);

  // ── Provider Switcher ──────────────────────────────────────────────────────
  /**
   * Switch the active provider. Automatically resets the model to the
   * new provider's default so you never end up with a model/provider mismatch.
   */
  const setActiveProvider = useCallback((providerKey) => {
    if (!PROVIDER_CONFIG[providerKey]) {
      console.warn(`[Ethrix-Forge] Unknown provider: "${providerKey}". Ignoring.`);
      return;
    }
    setActiveProviderState(providerKey);
    setActiveModel(PROVIDER_CONFIG[providerKey].defaultModel);
    setError(null);
  }, []);

  // ── Core Generator ────────────────────────────────────────────────────────
  /**
   * Generates files from a natural language prompt.
   *
   * @param {string} userPrompt - The user's coding request
   * @param {Object} [overrides] - Optional per-call overrides
   * @param {string} [overrides.provider] - Use a different provider for this call
   * @param {string} [overrides.model]    - Use a different model for this call
   * @param {string} [overrides.apiKey]   - Use a different key for this call
   *
   * @returns {Promise<Array<{id, filename, language, code}>>} Parsed file array
   */
  const generate = useCallback(
    async (userPrompt, overrides = {}) => {
      const provider = overrides.provider ?? activeProvider;
      const model    = overrides.model    ?? activeModel;
      const key      = overrides.apiKey   ?? apiKey;

      // ── Pre-flight validation ──────────────────────────────────────────
      if (!key || key.trim().length === 0) {
        const err = new AIServiceError(
          `No API key provided for ${PROVIDER_CONFIG[provider]?.label || provider}. Please add your key in Settings.`,
          ERROR_CODES.NO_API_KEY,
          provider,
          false
        );
        setError(err);
        throw err;
      }

      if (!userPrompt || userPrompt.trim().length === 0) {
        const err = new AIServiceError(
          "Prompt cannot be empty.",
          ERROR_CODES.UNKNOWN,
          provider,
          false
        );
        setError(err);
        throw err;
      }

      // ── Cancel any running request ─────────────────────────────────────
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();
      const { signal } = abortControllerRef.current;

      lastPromptRef.current = { userPrompt, overrides };

      setIsLoading(true);
      setError(null);
      setLastRawResponse(null);

      const caller = PROVIDER_CALLERS[provider];
      if (!caller) {
        const err = new AIServiceError(
          `Provider "${provider}" is not registered in PROVIDER_CALLERS.`,
          ERROR_CODES.UNKNOWN,
          provider,
          false
        );
        setIsLoading(false);
        setError(err);
        throw err;
      }

      // ── Retry loop ──────────────────────────────────────────────────────
      let lastErr = null;
      for (let attempt = 0; attempt <= retryAttempts; attempt++) {
        if (signal.aborted) {
          setIsLoading(false);
          return null;
        }

        if (attempt > 0) {
          // Exponential backoff: 1.5s → 3s → 6s...
          const delay = retryDelayMs * Math.pow(2, attempt - 1);
          console.info(
            `[Ethrix-Forge] Retry ${attempt}/${retryAttempts} in ${delay}ms for provider ${provider}...`
          );
          await sleep(delay);
        }

        try {
          const rawText = await caller({ apiKey: key, model, userPrompt, signal });

          if (rawText === null) {
            // Request was aborted
            setIsLoading(false);
            return null;
          }

          setLastRawResponse(rawText);
          setRequestCount((c) => c + 1);

          const files = parseAIResponse(rawText, provider);

          setLastGeneratedFiles(files);
          setError(null);
          setIsLoading(false);
          return files;

        } catch (err) {
          lastErr = err;

          // Don't retry non-retryable errors (bad key, safety block, etc.)
          if (err instanceof AIServiceError && !err.retryable) {
            break;
          }

          // Don't retry if caller was aborted
          if (signal.aborted || err.name === "AbortError") {
            setIsLoading(false);
            return null;
          }

          console.warn(
            `[Ethrix-Forge] Attempt ${attempt + 1} failed:`,
            err.message
          );
        }
      }

      // All attempts exhausted
      const finalError =
        lastErr instanceof AIServiceError
          ? lastErr
          : new AIServiceError(
              `Unexpected error: ${lastErr?.message ?? String(lastErr)}`,
              ERROR_CODES.UNKNOWN,
              provider,
              false
            );

      setError(finalError);
      setIsLoading(false);
      throw finalError;
    },
    [activeProvider, activeModel, apiKey, retryAttempts, retryDelayMs]
  );

  // ── Retry Last Request ─────────────────────────────────────────────────────
  /**
   * Re-runs the exact same prompt and overrides as the last generate() call.
   * Useful for a "Retry" button shown alongside error messages.
   */
  const retryLastRequest = useCallback(() => {
    if (!lastPromptRef.current) return null;
    const { userPrompt, overrides } = lastPromptRef.current;
    return generate(userPrompt, overrides);
  }, [generate]);

  // ── Cancel ─────────────────────────────────────────────────────────────────
  /**
   * Aborts any in-flight API request immediately.
   */
  const cancelRequest = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsLoading(false);
  }, []);

  // ── Expose helpers ─────────────────────────────────────────────────────────
  const currentProviderConfig = PROVIDER_CONFIG[activeProvider] ?? null;
  const availableModels = currentProviderConfig?.availableModels ?? [];

  return {
    // Core action
    generate,
    retryLastRequest,
    cancelRequest,

    // State
    isLoading,
    error,
    lastRawResponse,
    lastGeneratedFiles,
    requestCount,

    // Provider management
    activeProvider,
    setActiveProvider,
    currentProviderConfig,

    // Model management
    activeModel,
    setActiveModel,
    availableModels,

    // API key management
    apiKey,
    setApiKey,

    // Utilities
    PROVIDERS,
    PROVIDER_CONFIG,
    ERROR_CODES,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 8. MONACO FILE INJECTOR UTILITY
//    A pure helper you can use to inject parsed files into your Monaco state.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Merges newly generated files into an existing Monaco file state array.
 *
 * USAGE IN App.jsx:
 *   const files = await generate(prompt);
 *   setMonacoFiles(prev => injectFilesIntoEditor(prev, files));
 *
 * @param {Array}  existingFiles - Current files[] state from your editor
 * @param {Array}  newFiles      - Parsed files from generate()
 * @param {string} [strategy="replace-all"] - Merge strategy:
 *   "replace-all"   — Wipe existing files, insert only new ones
 *   "merge-by-name" — Update files with matching names; add new ones
 *   "append"        — Add all new files (may create duplicates)
 * @returns {Array} New files array to set as editor state
 */
export function injectFilesIntoEditor(existingFiles = [], newFiles = [], strategy = "replace-all") {
  if (!Array.isArray(newFiles) || newFiles.length === 0) return existingFiles;

  switch (strategy) {
    case "replace-all":
      return newFiles;

    case "merge-by-name": {
      const existingMap = new Map(existingFiles.map((f) => [f.filename, f]));
      for (const newFile of newFiles) {
        existingMap.set(newFile.filename, newFile);
      }
      return Array.from(existingMap.values());
    }

    case "append":
      return [...existingFiles, ...newFiles];

    default:
      console.warn(`[Ethrix-Forge] Unknown injection strategy: "${strategy}". Using "replace-all".`);
      return newFiles;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 9. USAGE EXAMPLE — Minimal App.jsx Integration
// ─────────────────────────────────────────────────────────────────────────────
/*

// App.jsx (abbreviated integration example):

import { useState } from "react";
import { useAIService, injectFilesIntoEditor, PROVIDERS } from "./useAIService";
import Editor from "@monaco-editor/react";

export default function App() {
  const [monacoFiles, setMonacoFiles] = useState([]);
  const [activeFile, setActiveFile] = useState(null);
  const [prompt, setPrompt] = useState("");

  const {
    generate,
    isLoading,
    error,
    retryLastRequest,
    cancelRequest,
    activeProvider,
    setActiveProvider,
    apiKey,
    setApiKey,
    activeModel,
    setActiveModel,
    availableModels,
    PROVIDERS,
  } = useAIService({
    initialProvider: PROVIDERS.GEMINI,
    retryAttempts: 2,
  });

  const handleGenerate = async () => {
    try {
      const files = await generate(prompt);
      if (files) {
        setMonacoFiles(prev => injectFilesIntoEditor(prev, files, "replace-all"));
        setActiveFile(files[0]);
      }
    } catch (err) {
      // error is also set in hook state — render err.message in your UI
      console.error(err);
    }
  };

  return (
    <div>
      // Provider selector
      <select value={activeProvider} onChange={(e) => setActiveProvider(e.target.value)}>
        <option value={PROVIDERS.GEMINI}>Gemini</option>
        <option value={PROVIDERS.GROQ}>Groq</option>
        <option value={PROVIDERS.OPENROUTER}>OpenRouter</option>
      </select>

      // Model selector
      <select value={activeModel} onChange={(e) => setActiveModel(e.target.value)}>
        {availableModels.map(m => (
          <option key={m.id} value={m.id}>{m.label}</option>
        ))}
      </select>

      // API Key input
      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder="Enter API Key..."
      />

      // Prompt area
      <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      <button onClick={handleGenerate} disabled={isLoading}>
        {isLoading ? "Generating..." : "Generate"}
      </button>
      {isLoading && <button onClick={cancelRequest}>Cancel</button>}

      // Error display
      {error && (
        <div>
          <p>{error.message}</p>
          {error.retryable && <button onClick={retryLastRequest}>Retry</button>}
        </div>
      )}

      // File tabs
      {monacoFiles.map(file => (
        <button key={file.id} onClick={() => setActiveFile(file)}>
          {file.filename}
        </button>
      ))}

      // Monaco Editor
      {activeFile && (
        <Editor
          language={activeFile.language}
          value={activeFile.code}
          theme="vs-dark"
          options={{ fontSize: 14 }}
        />
      )}
    </div>
  );
}

*/

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
