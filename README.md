# Gemini API Key Proxy (Flask Version)

A lightweight, secure proxy built with **Flask** for safely invoking the [Google Gemini API](https://ai.google.dev/) from frontend clients (mobile/web) without exposing your API key.

Supports custom **response schema**, model selection, and secret token authentication.

---

## 🚀 Features

- **Protects Gemini API Key** — never expose keys in frontend apps  
- **Supports model switching** (e.g., `gemini-1.5-pro`, `gemini-2.0-flash`)  
- **Supports response schema** — enables structured JSON output  
- **Token-based authorization**  
- Ready for deployment on **Google Cloud Run**, **Render**, etc.

---

## 🔧 Tech Stack

- Python 3 + Flask
- Google Gemini API 
- Secret token validation (via `Authorization` header)
- Advanced response schema for AI outputs

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

---

## 📤 Output Format (Schema Enforced)

This proxy injects a schema for relationship AI use cases.  
Example response:

```json
{
  "couple_possibility": 85,
  "judgment_reason": "You both communicate openly and with humor.",
  "improvement_suggestion": "Try spending more quality time together.",
  "encouragement_message": "You're on a good path. Stay positive!"
}
```

## 🎯 JSON Schema
```json
{
  "type": "object",
  "properties": {
    "couple_possibility": { "type": "integer" },
    "judgment_reason": { "type": "string" },
    "improvement_suggestion": { "type": "string" },
    "encouragement_message": { "type": "string" }
  },
  "required": [
    "couple_possibility",
    "judgment_reason",
    "improvement_suggestion",
    "encouragement_message"
  ]
}
```

## 📄 License

This project is licensed under the **MIT License**.  
Feel free to use, modify, and distribute as needed.

---

## 🙋 Author

Developed by **[Chia-Wei Chang](https://github.com/changch223)**  
If you have questions or collaboration ideas, don’t hesitate to reach out.
