from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# 設定一個 SECRET，App 打 API 時要帶上這個 Token
MY_SECRET_TOKEN = os.getenv("SECRET_TOKEN")

# 這是你的 Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini API Endpoint
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

@app.route("/", methods=["POST"])
def proxy_to_gemini():
    # 1. 驗證 App 傳來的 Secret Token
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {MY_SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    # 2. 取得 App 傳來的請求內容
    try:
        data = request.get_json()
        if data is None:
            raise ValueError("Missing JSON payload")
    except Exception as e:
        return jsonify({"error": f"Bad Request: {str(e)}"}), 400

    # 3. 發送請求到 Gemini API
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=data)
    except requests.RequestException as e:
        # 如果無法連到 Gemini（網路錯、timeout等）
        return jsonify({"error": f"Failed to call Gemini API: {str(e)}"}), 502  # 502 Bad Gateway

    # 4. 判斷 Gemini 回應是否成功
    if response.status_code != 200:
        # ❗這裡加上你要的 try/except
        try:
            return jsonify({
                "error": f"Gemini API error: {response.status_code}",
                "detail": response.json()
            }), response.status_code
        except Exception:
            return jsonify({
                "error": f"Gemini API error: {response.status_code}",
                "detail": response.text
            }), response.status_code

    # 5. 正常回傳 Gemini 回來的結果
    try:
        result = response.json()
    except Exception:
        return jsonify({"error": "Failed to parse Gemini API response"}), 500

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
