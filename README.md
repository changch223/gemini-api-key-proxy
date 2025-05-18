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
## 📦 Endpoint

### `POST /`  
**Headers**:
```http
Authorization: Bearer YOUR_SECRET_TOKEN
Content-Type: application/json
```

### 📝 Example Request

```json
{
  "model_name": "gemini-2.0-flash",
  "contents": [
    {
      "parts": [
        { "text": "Are we a good match? Here's our conversation..." }
      ]
    }
  ],
  "generationConfig": {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 256
  }
}
```

## 📄 License

This project is licensed under the **MIT License**.  
Feel free to use, modify, and distribute as needed.

---

## 🙋 Author

Developed by **[Chia-Wei Chang](https://github.com/changch223)**  
💡 Feel free to fork the repo, open issues, or contribute improvements!

If you have questions or collaboration ideas, don’t hesitate to reach out.
