// ✨ TUMHARA CLOUD BACKEND URL ✨
const BACK_URL = "https://shantanupathak94-ai-code-editor.hf.space";

export const api = {
  // 1. AI Generation (Secure Gateway)
  // apiService.js ke andar bas yeh function update karna hai
  generateCode: async (prompt, existingFiles, provider) => {
    // Yahan tumne jo apna Hugging Face space url dala hai, wahi rehne dena
    const API_URL = "https://YOUR-HUGGINGFACE-SPACE-URL.hf.space"; 
    
    try {
      // DHYAAN DO: Naya endpoint aur naya body format
      const response = await fetch(`${API_URL}/api/agent/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: prompt,
          existing_files: existingFiles, // Ab AI ko tumhari files dikhengi!
          model_preference: provider || "gemini"
        })
      });
      
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || "AI Gateway Error");
      }
      
      const data = await response.json();
      return data.files; // Naya return format
    } catch (error) {
      throw error;
    }
  },

  // 2. MongoDB Workspace Sync
  saveWorkspace: async (name, filesObject) => {
    // React files state ko backend format mein convert karna
    const filesArray = Object.values(filesObject).map(f => ({
      filename: f.name, language: f.language, code: f.value
    }));
    const res = await fetch(`${BACK_URL}/workspace/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: "shantanu_founder", name, files: filesArray })
    });
    return await res.json();
  },

  loadWorkspaces: async () => {
    const res = await fetch(`${BACK_URL}/workspace/user/shantanu_founder`);
    return await res.json();
  },

  loadSingleWorkspace: async (workspaceId) => {
    const res = await fetch(`${BACK_URL}/workspace/${workspaceId}`);
    return await res.json();
  },

  // 3. GitHub Logic
  githubClone: async (repoUrl) => {
    const res = await fetch(`${BACK_URL}/github/clone`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl, branch: "main" })
    });
    if (!res.ok) throw new Error("Failed to clone repo");
    return await res.json();
  },

  githubPush: async (repoFullName, commitMessage, filesObject, token) => {
    const filesArray = Object.values(filesObject).map(f => ({
      filename: f.name, language: f.language, code: f.value
    }));
    const res = await fetch(`${BACK_URL}/github/commit-push`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_full_name: repoFullName, commit_message: commitMessage, files: filesArray, token })
    });
    if (!res.ok) throw new Error("GitHub Push Failed");
    return await res.json();
  }
};