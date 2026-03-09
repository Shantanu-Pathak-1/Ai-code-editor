# 🛠️ Ethrix-Forge : AI Auto-Coding Agent

Welcome to the official cloud workspace of **Ethrix-Forge**, a next-generation AI-powered Code Editor and autonomous development environment. 

## 🚀 The Vision
Ethrix-Forge is not just another IDE; it is your AI co-founder. Designed to generate, execute, and sync code autonomously, it empowers developers to build and scale projects at lightning speed—perfect for high-stakes hackathons and fast-paced tech startups.

## ✨ Key Features
* **🧠 Multi-API AI Engine**: Seamlessly switch between Google Gemini (2.0 Flash), Groq, and OpenRouter for uninterrupted auto-coding.
* **💻 VS Code Experience**: Deep integration with Monaco Editor for professional syntax highlighting and file management.
* **⚡ Live Preview**: Instantly render and test HTML/CSS/JS combinations with a single click.
* **☁️ Auto-Save & Cloud Sync**: Powered by MongoDB to ensure zero data loss, automatically saving files and chat history every few seconds.
* **🛠️ Hackathon Ready**: Built-in 1-click GitHub repo cloning/pushing and Google Drive ZIP exports to beat strict deadlines.

## 🧰 Tech Stack
* **Frontend**: React (Vite) + Monaco Editor
* **Backend**: Python (FastAPI) + Uvicorn
* **Database**: MongoDB (Async Motor)
* **Cloud Platform**: Hugging Face Spaces (Docker) + GitHub

## 🔐 Environment Variables (Hugging Face Secrets)
To securely run this space without exposing credentials, the following variables must be set in the Space Settings:
* `GEMINI_API_KEY`: Google Gemini API Key
* `GROQ_API_KEY`: Groq API Key
* `MONGO_URI`: MongoDB Connection String
* `GITHUB_TOKEN`: Personal Access Token for Repo operations

---
*Built with ❤️ by Shantanu | Scaling towards the future of AI Engineering.*