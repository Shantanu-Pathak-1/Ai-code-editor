import { useState, useCallback } from "react";

// ✨ TUMHARA CLOUD BACKEND URL ✨
const BACKEND_URL = "https://shantanupathak94-ai-code-editor.hf.space";

export const PROVIDERS = {
  GEMINI: "gemini",
  GROQ: "groq",
  OPENROUTER: "openrouter"
};

export function useAIService({ initialProvider = PROVIDERS.GEMINI } = {}) {
  const [activeProvider, setActiveProvider] = useState(initialProvider);
  const [isLoading, setIsLoading] = useState(false);
  const [apiKey, setApiKey] = useState(""); // Ab API key frontend mein zaroori nahi, par purane UI ke liye state rakh li hai

  const generate = useCallback(async (userPrompt) => {
    setIsLoading(true);
    try {
      // 🚀 Direct tumhare FastAPI server ko request bhej rahe hain!
      const response = await fetch(`${BACKEND_URL}/ai/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: userPrompt,
          provider: activeProvider
        })
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Backend server error 🥺");
      }

      const data = await response.json();
      setIsLoading(false);
      
      // Backend ne already JSON parse karke files array de diya hai! ✨
      return data.files; 
    } catch (error) {
      setIsLoading(false);
      throw error;
    }
  }, [activeProvider]);

  return { 
    generate, 
    isLoading, 
    activeProvider, 
    setActiveProvider,
    apiKey, // UI break na ho isliye rakha hai
    setApiKey
  };
}