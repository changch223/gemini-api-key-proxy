from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

MY_SECRET_TOKEN = os.getenv("SECRET_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def normalize_system_instruction(si):
    """
    iOS 側が string を送ってくる可能性もあるので、
    REST の systemInstruction(Content形式) に合わせる最小ガード。
    既に dict(Content) ならそのまま返す。
    """
    if si is None:
        return None
    if isinstance(si, dict):
        return si
    if isinstance(si, str) and si.strip():
        return {"parts": [{"text": si}]}
    return None

@app.route("/", methods=["POST"])
def proxy_to_gemini():
    # 1) Auth
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {MY_SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    # 2) Body
    try:
        data = request.get_json()
        if data is None:
            raise ValueError("Missing JSON payload")
    except Exception as e:
        return jsonify({"error": f"Bad Request: {str(e)}"}), 400

    # 3) model_name default を 2.5 にする（★ここだけでアップグレード目的は達成）
    model_name = data.get("model_name", "gemini-2.5-flash")  # CHANGE
    data.pop("model_name", None)

    GEMINI_API_URL = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {}

    # 4) contents を今まで通りマージ（ただし role を付ける：2.5で安定）
    if "contents" in data:
        merged_parts = []
        for content in data["contents"]:
            if isinstance(content, dict) and "parts" in content:
                merged_parts.extend(content["parts"])
        if merged_parts:
            payload["contents"] = [{
                "role": "user",          # CHANGE（2.5で安定）
                "parts": merged_parts
            }]

    # 5) その他は今まで通りコピー
    if "generationConfig" in data:
        payload["generationConfig"] = data["generationConfig"]

    # system_instruction は REST では systemInstruction（camelCase）
    if "system_instruction" in data:
        si = normalize_system_instruction(data["system_instruction"])
        if si:
            payload["systemInstruction"] = si  # CHANGE

    if "tools" in data:
        payload["tools"] = data["tools"]
    if "safetySettings" in data:
        payload["safetySettings"] = data["safetySettings"]

    # 6) Structured Output を generationConfig に付与（REST は camelCase）
    if "generationConfig" not in payload:
        payload["generationConfig"] = {}

    # CHANGE: snake_case → camelCase
    payload["generationConfig"]["responseMimeType"] = "application/json"
    payload["generationConfig"]["responseSchema"] = {
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
        ],
        "propertyOrdering": [
            "couple_possibility",
            "judgment_reason",
            "improvement_suggestion",
            "encouragement_message"
        ]
    }

    # CHANGE: 2.5で「思考」混入を避けたいので最小でOFF
    payload["generationConfig"]["thinkingConfig"] = {
        "includeThoughts": False,
        "thinkingBudget": 0
    }

    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        return jsonify({"error": f"Failed to call Gemini API: {str(e)}"}), 502

    if response.status_code != 200:
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

    try:
        result = response.json()
    except Exception:
        return jsonify({"error": "Failed to parse Gemini API response"}), 500

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
