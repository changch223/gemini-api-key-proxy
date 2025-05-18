# 🔐 Gemini API Key Proxy (Flask Version)

A lightweight, secure proxy built with **Flask** for safely invoking the [Google Gemini API](https://ai.google.dev/) from frontend clients (mobile/web) without exposing your API key.

Supports custom **response schema**, model selection, and secret token authentication.

---

## 🚀 Features

- ✅ **Protects Gemini API Key** — never expose keys in frontend apps  
- 🔄 **Supports model switching** (e.g., `gemini-1.5-pro`, `gemini-2.0-flash`)  
- 🧩 **Supports response schema** — enables structured JSON output  
- 🔐 **Token-based authorization**  
- ☁️ Ready for deployment on **Google Cloud Run**, **Render**, etc.

---

## 🔧 Tech Stack

- 🧪 Python 3 + Flask
- 🌐 Google Gemini API v1beta
- 🔐 Secret token validation (via `Authorization` header)
- 🧠 Advanced response schema for AI outputs

---
