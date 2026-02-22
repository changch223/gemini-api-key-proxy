import os
import json
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

MY_SECRET_TOKEN = os.getenv("SECRET_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL_NAME = "gemini-2.5-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GEMINI_API_KEY}"

REQUIRED_KEYS = {
    "couple_possibility",
    "judgment_reason",
    "improvement_suggestion",
    "encouragement_message",
}

# JSON Schema (Gemini Structured Output 用)
RESPONSE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "couple_possibility": {"type": "integer"},
        "judgment_reason": {"type": "string"},
        "improvement_suggestion": {"type": "string"},
        "encouragement_message": {"type": "string"},
    },
    "required": [
        "couple_possibility",
        "judgment_reason",
        "improvement_suggestion",
        "encouragement_message",
    ],
}

def make_failsafe_response(
    judgment_reason: str = "送信された内容から恋愛分析を行うことができませんでした。画像/テキストが解析不能、または安全フィルターによりブロックされた可能性があります。",
    improvement_suggestion: str = "二人の関係性が分かる具体的なエピソード、または顔がはっきり写った写真を送ってみてください。",
    encouragement_message: str = "次はきっとうまく分析できるはずです！",
):
    payload = {
        "couple_possibility": 0,
        "judgment_reason": judgment_reason,
        "improvement_suggestion": improvement_suggestion,
        "encouragement_message": encouragement_message,
    }
    return {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": json.dumps(payload, ensure_ascii=False)
                }]
            },
            "finishReason": "STOP"
        }]
    }

FAILSAFE = make_failsafe_response()

def strip_code_fences(text: str) -> str:
    t = text.strip()
    # ```json ... ``` を剥がす
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()

def try_parse_json(text: str):
    """
    1) そのまま JSON parse
    2) code fence除去して parse
    3) 最初の { と最後の } を抜き出して parse
    """
    if not isinstance(text, str):
        return None

    candidates = [text, strip_code_fences(text)]
    for t in candidates:
        t = t.strip()
        if not t:
            continue
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            pass

        # JSON 部分だけ抽出（雑だけど現場で効く）
        l = t.find("{")
        r = t.rfind("}")
        if 0 <= l < r:
            sub = t[l:r+1]
            try:
                return json.loads(sub)
            except json.JSONDecodeError:
                pass

    return None

def normalize_and_validate(parsed):
    """
    Swift Codable が落ちないように必須キーの存在チェック＋型を軽く正規化。
    """
    if not isinstance(parsed, dict):
        return None
    if not REQUIRED_KEYS.issubset(parsed.keys()):
        return None

    # couple_possibility を int に寄せる（"80" みたいな文字列対策）
    try:
        parsed["couple_possibility"] = int(parsed["couple_possibility"])
    except Exception:
        return None

    # 文字列フィールドが文字列でない場合は stringify
    for k in ["judgment_reason", "improvement_suggestion", "encouragement_message"]:
        if not isinstance(parsed.get(k), str):
            parsed[k] = str(parsed.get(k, ""))

    return parsed

def merge_parts_from_ios(data: dict):
    """
    iOS から contents が複数（text, image が別 content）で来る前提。
    parts を 1つに統合して Gemini 側の role 重複/分割問題を回避。
    """
    merged_parts = []
    for c in data.get("contents", []) or []:
        parts = c.get("parts")
        if isinstance(parts, list):
            merged_parts.extend(parts)
    return merged_parts

@app.route("/", methods=["POST"])
def proxy_to_gemini():
    # 1) Auth
    auth_header = request.headers.get("Authorization", "")
    if not MY_SECRET_TOKEN or auth_header != f"Bearer {MY_SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    # 2) Body
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Bad Request: Missing JSON payload"}), 400

    merged_parts = merge_parts_from_ios(data)
    if not merged_parts:
        # 入力自体が空なら即 failsafe（iOSクラッシュ防止）
        return jsonify(FAILSAFE)

    # system_instruction は iOS 側が snake_case で送ってくる想定なので拾う
    system_instruction = data.get("system_instruction") or data.get("systemInstruction")

    # クライアントの generationConfig を活かしつつ、Structured Output を強制
    client_gc = data.get("generationConfig") or {}
    temperature = client_gc.get("temperature", 0.3)
    top_p = client_gc.get("topP", client_gc.get("top_p", 0.95))
    top_k = client_gc.get("topK", client_gc.get("top_k", 10))
    max_tokens = client_gc.get("maxOutputTokens", 1024)

    payload = {
        "contents": [{
            "role": "user",
            "parts": merged_parts
        }],
        "generationConfig": {
            # クライアント値
            "temperature": temperature,
            "topP": top_p,
            "topK": top_k,
            "maxOutputTokens": max_tokens,

            # 🔥 JSON 強制（Structured Output）
            "responseMimeType": "application/json",
            "responseJsonSchema": RESPONSE_JSON_SCHEMA,

            # 🔥 2.5 Flash の thinking 混入対策（正しい場所は generationConfig 内）
            "thinkingConfig": {
                "includeThoughts": False
                # thinkingBudget は未指定でもOK。必要なら整数で設定。
            }
        }
    }

    if system_instruction:
        payload["systemInstruction"] = system_instruction

    # safety / tools が来たらそのまま通す（ただし空なら送らない）
    safety = data.get("safetySettings")
    if safety:
        payload["safetySettings"] = safety
    tools = data.get("tools")
    if tools:
        payload["tools"] = tools

    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        print(f"[Proxy] RequestException: {e}")
        return jsonify(FAILSAFE)

    if resp.status_code != 200:
        # ここで常に 0点に落ちてるなら、Cloud Run logs にこの行が出てるはず
        print(f"[Proxy] Gemini API error {resp.status_code}: {resp.text}")
        return jsonify(FAILSAFE)

    try:
        result = resp.json()
    except Exception as e:
        print(f"[Proxy] Failed to parse Gemini response JSON: {e} / raw={resp.text[:500]}")
        return jsonify(FAILSAFE)

    # --- 応答検証（iOS decode crash 防止）---
    try:
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            print("[Proxy] No candidates")
            return jsonify(FAILSAFE)

        cand0 = candidates[0]

        content = cand0.get("content")
        if not isinstance(content, dict):
            print(f"[Proxy] Missing content. finishReason={cand0.get('finishReason')}")
            return jsonify(FAILSAFE)

        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            print(f"[Proxy] Missing parts. finishReason={cand0.get('finishReason')}")
            return jsonify(FAILSAFE)

        # text を結合（まれに複数 parts で返る）
        texts = []
        for p in parts:
            if isinstance(p, dict) and "text" in p and isinstance(p["text"], str):
                texts.append(p["text"])
        ai_text = "\n".join(texts).strip()

        if not ai_text:
            print(f"[Proxy] Empty ai_text. finishReason={cand0.get('finishReason')}")
            return jsonify(FAILSAFE)

        parsed = try_parse_json(ai_text)
        parsed = normalize_and_validate(parsed)
        if not parsed:
            print(f"[Proxy] Not valid JSON output. ai_text(head)={ai_text[:200]}")
            return jsonify(FAILSAFE)

        # iOS 側の安定のため、正規化した JSON を必ず返す（Gemini形式を模倣）
        normalized_text = json.dumps(parsed, ensure_ascii=False)
        return jsonify({
            "candidates": [{
                "content": {
                    "parts": [{"text": normalized_text}]
                },
                "finishReason": cand0.get("finishReason", "STOP")
            }]
        })

    except Exception as e:
        print(f"[Proxy] Validation unexpected error: {e}")
        return jsonify(FAILSAFE)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
