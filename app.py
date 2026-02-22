from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

MY_SECRET_TOKEN = os.getenv("SECRET_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

@app.route("/", methods=["POST"])
def proxy_to_gemini():
    # 1. 認証
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {MY_SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    # 2. データの取得
    data = request.get_json()
    if not data:
        return jsonify({"error": "Bad Request: Missing JSON payload"}), 400

    # 3. モデル名の決定 (2.5-flash を優先)
    # メールにある通り、将来的に 2.0 は廃止されるため 2.5 を指定します
    model_name = "gemini-2.5-flash"
    
    # 4. API URL
    GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"

    # 5. 🔥 重要：全ての parts を一つの user ロールにまとめる
    # iOSから送られてくる複数の contents を結合して、APIエラーを回避します
    merged_parts = []
    if "contents" in data:
        for content in data["contents"]:
            if "parts" in content:
                merged_parts.extend(content["parts"])

    # 6. ペイロードの構築
    payload = {
        "contents": [{
            "role": "user",
            "parts": merged_parts
        }],
        "system_instruction": data.get("system_instruction"),
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.3, # 解析精度を上げるため低めに設定
            "maxOutputTokens": 1024,
            "response_schema": {
                "type": "object",
                "properties": {
                    "couple_possibility": {"type": "integer"},
                    "judgment_reason": {"type": "string"},
                    "improvement_suggestion": {"type": "string"},
                    "encouragement_message": {"type": "string"}
                },
                "required": [
                    "couple_possibility", "judgment_reason",
                    "improvement_suggestion", "encouragement_message"
                ]
            }
        }
    }

    # 7. API 呼び出し
    headers = {"Content-Type": "application/json"}
    try:
        # タイムアウトを少し長めに設定
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            return jsonify({
                "error": f"Gemini API error: {response.status_code}",
                "detail": response.text
            }), response.status_code

        return jsonify(response.json())

    except requests.RequestException as e:
        return jsonify({"error": f"Failed to call Gemini API: {str(e)}"}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
