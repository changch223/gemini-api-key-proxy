from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# 設定：App 打 API 時要帶上這個 Token
MY_SECRET_TOKEN = os.getenv("SECRET_TOKEN")
# 設定：Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

@app.route("/", methods=["POST"])
def proxy_to_gemini():
    # 1. 驗證 App 傳來的 Secret Token
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {MY_SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    # 2. 取得 App 傳來的請求內容
    data = request.get_json()
    if not data:
        return jsonify({"error": "Bad Request: Missing JSON payload"}), 400

    # 3. 從 App JSON 裡讀取 model_name (預設改為 2.5)
    model_name = data.get("model_name", "gemini-2.5-flash")
    data.pop("model_name", None)

    # 4. 組成 API URL (使用 v1beta 以支援 Gemini 2.5)
    GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"

    # 5. 生成設定の構築（Gemini 2.5 用に最適化）
    # クライアントからの設定を活かしつつ、JSON出力を強制する
    generation_config = data.get("generationConfig", {})
    generation_config.update({
        "response_mime_type": "application/json",
        "maxOutputTokens": 1024, # 余裕を持たせる
        "response_schema": {
            "type": "object",
            "properties": {
                "couple_possibility": {"type": "integer"},
                "judgment_reason": {"type": "string"},
                "improvement_suggestion": {"type": "string"},
                "encouragement_message": {"type": "string"}
            },
            "required": [
                "couple_possibility",
                "judgment_reason",
                "improvement_suggestion",
                "encouragement_message"
            ]
        }
    })

    # 6. 🔥 Gemini 2.5 特有の「思考プロセス」をオフにする設定を注入
    # これがないと、回答に「考えた過程」が混じり、iOS側でのパースに失敗します
    payload = {
        "contents": data.get("contents", []),
        "system_instruction": data.get("system_instruction"),
        "generationConfig": generation_config,
        "thinkingConfig": {
            "includeThoughts": False,
            "thinkingBudget": 0
        },
        "safetySettings": data.get("safetySettings", []),
        "tools": data.get("tools", [])
    }

    # API 呼び出し実行
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
        
        # 7. 判斷 Gemini 回應是否成功
        if response.status_code != 200:
            return jsonify({
                "error": f"Gemini API error: {response.status_code}",
                "detail": response.text
            }), response.status_code

        # 8. 正常回傳結果
        return jsonify(response.json())

    except requests.RequestException as e:
        return jsonify({"error": f"Failed to call Gemini API: {str(e)}"}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
