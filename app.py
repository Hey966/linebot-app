# app.py
# -*- coding: utf-8 -*-
import os, hmac, hashlib, base64, json, logging
from flask import Flask, request, jsonify, abort

# ==== LINE SDK v3 ====
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---- 環境變數 ----
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "")
VERIFY_SIGNATURE = os.environ.get("VERIFY_SIGNATURE", "1") == "1"
TO_USER_ID = os.environ.get("TO_USER_ID", "")  # /push 用

# OMP 安全設定（避免 OpenMP 衝突）
os.environ.setdefault("OMP_NUM_THREADS", "1")

# ---- 建立 MessagingApi ----
if not CHANNEL_ACCESS_TOKEN:
    app.logger.warning("缺少 CHANNEL_ACCESS_TOKEN（無法回覆/推播）")

config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

def verify_line_signature(raw_body: bytes, signature_header: str) -> bool:
    if not CHANNEL_SECRET:
        app.logger.warning("CHANNEL_SECRET 未設，無法驗簽；可設 VERIFY_SIGNATURE=0 跳過")
        return False
    mac = hmac.new(CHANNEL_SECRET.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature_header or "")

@app.get("/healthz")
def healthz():
    return jsonify(status="ok", service="linebot", version="1"), 200

@app.post("/webhook")
def webhook():
    raw = request.get_data()
    sig = request.headers.get("X-Line-Signature", "")

    if VERIFY_SIGNATURE and not verify_line_signature(raw, sig):
        return "signature invalid", 403

    body = request.get_json(silent=True) or {}
    app.logger.info("Webhook body: %s", json.dumps(body, ensure_ascii=False))

    # 回覆文字訊息（message.text）
    if not CHANNEL_ACCESS_TOKEN:
        return "no access token", 200  # 收到但無法回覆

    events = body.get("events", [])
    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        for ev in events:
            if ev.get("type") == "message" and ev.get("message", {}).get("type") == "text":
                reply_token = ev.get("replyToken")
                user_text = ev["message"]["text"]
                reply = f"我收到：{user_text}"
                try:
                    api.reply_message(
                        ReplyMessageRequest(
                            reply_token=reply_token,
                            messages=[TextMessage(text=reply)]
                        )
                    )
                except Exception as e:
                    app.logger.error(f"reply_message 失敗：{e}")
    return "OK", 200

@app.post("/push")
def push():
    """以環境變數 TO_USER_ID 推播一則文字（可用 Postman/curl 測試）"""
    if not CHANNEL_ACCESS_TOKEN or not TO_USER_ID:
        return "缺 CHANNEL_ACCESS_TOKEN 或 TO_USER_ID", 400
    data = request.get_json(silent=True) or {}
    text = data.get("text", "Hello from /push")
    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        try:
            api.push_message(
                PushMessageRequest(
                    to=TO_USER_ID,
                    messages=[TextMessage(text=text)]
                )
            )
            return "OK", 200
        except Exception as e:
            app.logger.error(f"push_message 失敗：{e}")
            return f"push failed: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
