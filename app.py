import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# 設定：App 打 API 時要帶上這個 Token
MY_SECRET_TOKEN = os.getenv("SECRET_TOKEN")
# 設定：Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- 例外時（解析失敗や安全フィルター発動時）に返すデフォルト回答 ---
# iOS側の JSONDecoder が正しくパースできるように、Gemini APIの正規レスポンス構造を模倣します
DEFAULT_ERROR_RESPONSE = {
    "candidates": [{
        "content": {
            "parts": [{
                "text": json.dumps({
                    "couple_possibility": 0,
                    "judgment_reason": "送信された内容から恋愛分析を行うことができませんでした。画像やテキストが安全基準に満たなかったか、解析不能なデータです。",
                    "improvement_suggestion": "もっと具体的な二人の関係性や、顔がはっきりわかる写真を送ってみてください。",
                    "encouragement_message": "次はきっとうまく分析できるはずです！"
                })
            }]
        },
        "finishReason": "STOP"
    }]
}

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

    # 3. 強制使用 Gemini 2.5 Flash
    model_name = "gemini-2.5-flash"
    GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"

    # 4. 🔥 重要：iOSから送られた全ての parts を 1つの user ロールに統合する
    # これにより、API側でのフォーマットエラー（Roleの連続エラー）を防ぎます
    merged_parts = []
    if "contents" in data:
        for content in data["contents"]:
            if "parts" in content:
                merged_parts.extend(content["parts"])

    # 5. Gemini API へのペイロード構築（Gemini 2.5 用に最適化）
    payload = {
        "contents": [{
            "role": "user",
            "parts": merged_parts
        }],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.3, # 安定した出力を得るため少し低めに設定
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
                    "couple_possibility",
                    "judgment_reason",
                    "improvement_suggestion",
                    "encouragement_message"
                ]
            }
        }
    }

    # system_instruction があれば追加
    if "system_instruction" in data:
        payload["system_instruction"] = data["system_instruction"]

    # 6. API 呼び出し実行
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
        
        # もしGemini API自体がエラー（500や400等）を返したら、デフォルト回答でフェイルセーフ
        if response.status_code != 200:
            print(f"Gemini API Error: {response.status_code} - {response.text}")
            return jsonify(DEFAULT_ERROR_RESPONSE)

        result = response.json()

        # 7. 🔥 AI回答の検証（デコードエラー・空っぽ対策）
        try:
            # 応答に有効なデータが含まれているかチェック
            if "candidates" in result and len(result["candidates"]) > 0:
                candidate = result["candidates"][0]
                
                # 安全フィルター(Safety)でブロックされた場合などは content が無い
                if "content" not in candidate or "parts" not in candidate["content"]:
                    print("Block Info:", candidate.get("finishReason", "Unknown block"))
                    return jsonify(DEFAULT_ERROR_RESPONSE)
                
                # AIが返したテキストを取得
                ai_text = candidate["content"]["parts"][0].get("text", "")
                if not ai_text:
                    return jsonify(DEFAULT_ERROR_RESPONSE)
                
                # JSONとしてパースできるかテスト（ここで失敗すれば except ブロックへ）
                json.loads(ai_text)
                
                # 全てのチェックを通過したら、正常な結果をそのままiOSへ返す
                return jsonify(result)
            else:
                return jsonify(DEFAULT_ERROR_RESPONSE)

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            # AIが変な回答をしたり、JSONが壊れている場合はクラッシュを防ぐためデフォルトを返す
            print(f"Validation Error: {str(e)}")
            return jsonify(DEFAULT_ERROR_RESPONSE)

    except requests.RequestException as e:
        # ネットワークタイムアウトなどの場合
        print(f"Request Exception: {str(e)}")
        return jsonify(DEFAULT_ERROR_RESPONSE)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
