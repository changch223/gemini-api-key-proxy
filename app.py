from flask import Flask, request, jsonify
from collections import deque
import hmac
import os
import threading
import time
import requests

app = Flask(__name__)
# 画像3枚（各1MB未満）＋テキストで十分な上限。巨大なリクエストは受け付けない
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 受け付けるトークン。SECRET_TOKENS（カンマ区切り）で複数指定でき、
# 旧 SECRET_TOKEN も併用できる（トークン切り替えの移行期間用）。
ACCEPTED_TOKENS = [
    t.strip()
    for t in (os.getenv("SECRET_TOKENS", "") + "," + os.getenv("SECRET_TOKEN", "")).split(",")
    if t.strip()
]


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# 回数制限（インスタンスごとのメモリ上で数える簡易なもの。0 で無効）
RATE_LIMIT_WINDOW_SECONDS = 600
RATE_LIMIT_PER_10MIN = _env_int("RATE_LIMIT_PER_10MIN", 20)   # 1つのIPから10分あたり
RATE_LIMIT_PER_DAY = _env_int("RATE_LIMIT_PER_DAY", 100)      # 1つのIPから24時間あたり
GLOBAL_DAILY_LIMIT = _env_int("GLOBAL_DAILY_LIMIT", 5000)     # 全体で24時間あたり（課金の上限ガード）
DAY_SECONDS = 24 * 60 * 60

_hits_by_ip = {}
_hits_global = deque()
_rate_lock = threading.Lock()

# 通知用のログ。Cloud Logging のログベースのアラートが "PROXY_ALERT" を含む行を拾い、
# メールで知らせる（設定は Google Cloud 側。宛先はここには書かない）。
# 攻撃中にログが溢れないよう、同じ種類は ALERT_LOG_INTERVAL 秒に1行だけ出す。
ALERT_LOG_INTERVAL = 60
_last_alert = {}
_alert_lock = threading.Lock()


def log_alert(kind, detail):
    now = time.time()
    with _alert_lock:
        if now - _last_alert.get(kind, 0) < ALERT_LOG_INTERVAL:
            return
        _last_alert[kind] = now
    print(f"PROXY_ALERT service=myakuari kind={kind} {detail}", flush=True)


def is_authorized():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[len("Bearer "):].encode()
    return any(hmac.compare_digest(token, accepted.encode()) for accepted in ACCEPTED_TOKENS)


def client_ip():
    """
    Cloud Run では X-Forwarded-For の末尾が実際の接続元。
    先頭側はクライアントが自由に書けるので使わない。
    """
    forwarded = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    return forwarded[-1] if forwarded else (request.remote_addr or "unknown")


def check_rate_limit(ip):
    """制限内なら None、超えていたら再試行までの秒数を返す。"""
    retry_after, alert = _check_rate_limit(ip)
    if alert:
        log_alert(*alert)
    return retry_after


def _check_rate_limit(ip):
    """(再試行までの秒数 or None, 通知 (kind, detail) or None) を返す。"""
    now = time.time()
    with _rate_lock:
        while _hits_global and now - _hits_global[0] > DAY_SECONDS:
            _hits_global.popleft()
        hits = _hits_by_ip.setdefault(ip, deque())
        while hits and now - hits[0] > DAY_SECONDS:
            hits.popleft()

        if GLOBAL_DAILY_LIMIT and len(_hits_global) >= GLOBAL_DAILY_LIMIT:
            return (int(DAY_SECONDS - (now - _hits_global[0])) + 1,
                    ("global_day_limit", f"limit={GLOBAL_DAILY_LIMIT} ip={ip}"))
        if RATE_LIMIT_PER_DAY and len(hits) >= RATE_LIMIT_PER_DAY:
            return (int(DAY_SECONDS - (now - hits[0])) + 1,
                    ("ip_day_limit", f"limit={RATE_LIMIT_PER_DAY} ip={ip}"))
        if RATE_LIMIT_PER_10MIN:
            recent = [t for t in hits if now - t <= RATE_LIMIT_WINDOW_SECONDS]
            if len(recent) >= RATE_LIMIT_PER_10MIN:
                return (int(RATE_LIMIT_WINDOW_SECONDS - (now - recent[0])) + 1,
                        ("ip_10min_limit", f"limit={RATE_LIMIT_PER_10MIN} ip={ip}"))

        hits.append(now)
        _hits_global.append(now)
        # 使われなくなったIPの記録を掃除する
        if len(_hits_by_ip) > 20000:
            for key in [k for k, v in _hits_by_ip.items() if not v or now - v[-1] > DAY_SECONDS]:
                del _hits_by_ip[key]
        # 全体の上限の 80% に達したら、止まる前に知らせる
        if GLOBAL_DAILY_LIMIT and len(_hits_global) == (GLOBAL_DAILY_LIMIT * 4 + 4) // 5:
            return None, ("global_day_80pct", f"count={len(_hits_global)} limit={GLOBAL_DAILY_LIMIT}")
        return None, None

# モデルはサーバー側で決める（先頭から順に試し、提供終了(404)なら次へフォールバック）。
# 配布済みアプリが古い model_name を送ってきても壊れないよう、クライアント指定は使わない。
GEMINI_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-3.8-flash").split(",")
    if m.strip()
]

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

@app.route("/whoami", methods=["GET"])
def whoami():
    """設定確認用。認証済みの呼び出し元に、回数制限で使うIPと現在の制限値を返す。"""
    if not is_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "ip": client_ip(),
        "limits": {
            "per_10min": RATE_LIMIT_PER_10MIN,
            "per_day": RATE_LIMIT_PER_DAY,
            "global_per_day": GLOBAL_DAILY_LIMIT,
        },
        "accepted_tokens": len(ACCEPTED_TOKENS),
    })


@app.route("/", methods=["POST"])
def proxy_to_gemini():
    # 1) Auth
    if not is_authorized():
        return jsonify({"error": "Unauthorized"}), 401

    # 1.5) 回数制限（認証を通ったリクエストだけ数える）
    retry_after = check_rate_limit(client_ip())
    if retry_after is not None:
        response = jsonify({"error": "Too Many Requests"})
        response.headers["Retry-After"] = str(retry_after)
        return response, 429

    # 2) Body
    try:
        data = request.get_json()
        if data is None:
            raise ValueError("Missing JSON payload")
    except Exception as e:
        return jsonify({"error": f"Bad Request: {str(e)}"}), 400

    # 3) クライアントの model_name は無視する（提供終了モデルを固定で送る旧バージョン対策）
    data.pop("model_name", None)

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

    response = None
    for model_name in GEMINI_MODELS:
        gemini_api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={GEMINI_API_KEY}"
        )
        try:
            response = requests.post(gemini_api_url, headers=headers, json=payload, timeout=60)
        except requests.RequestException as e:
            log_alert("gemini_error", f"status={type(e).__name__}")
            return jsonify({"error": f"Failed to call Gemini API: {type(e).__name__}"}), 502
        # 404 = モデル提供終了。次の候補で再試行する
        if response.status_code != 404:
            break
        app.logger.warning("Gemini model unavailable: %s", model_name)
        log_alert("model_unavailable", f"model={model_name}")

    if response is None:
        return jsonify({"error": "No Gemini model configured"}), 500

    if response.status_code != 200:
        log_alert("gemini_error", f"status={response.status_code}")
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
