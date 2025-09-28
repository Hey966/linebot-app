# -*- coding: utf-8 -*-
import os, json
from pathlib import Path
from flask import Flask, request, abort

from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
try:
    from linebot.v3.messaging.exceptions import ApiException
except Exception:
    try:
        from linebot.v3.exceptions import ApiException
    except Exception:
        ApiException = Exception

BASE_DIR = Path(__file__).resolve().parent
USERS_JSON = BASE_DIR / "users.json"

def load_users():
    try:
        with open(USERS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"_by_user_id": {}, "_by_name": {}}

def save_users(data):
    try:
        with open(USERS_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("[USERS][ERROR] 寫入失敗", e)
        return False

# Render 會把 PORT 設在環境變數；本地測試預設 10000
PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN", "").strip()
CHANNEL_SECRET       = os.environ.get("CHANNEL_SECRET", "").strip()
if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise SystemExit("[FATAL] 缺少 CHANNEL_SECRET 或 CHANNEL_ACCESS_TOKEN")

app = Flask(__name__)
handler = WebhookHandler(CHANNEL_SECRET)
config  = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK", 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = getattr(event.source, "user_id", None)
    text = (event.message.text or "").strip()
    users = load_users()
    by_uid  = users.setdefault("_by_user_id", {})
    by_name = users.setdefault("_by_name", {})
    reply_text = None

    # 指令：查詢
    if text.startswith("查詢"):
        bound_name = by_uid.get(user_id, {}).get("name")
        if bound_name:
            reply_text = f"目前已綁定 {bound_name} ✅"
        else:
            reply_text = "目前尚未綁定 請先進行綁定"

    # 指令：連結 <姓名>
    elif text.startswith("連結 "):
        new_name = text[3:].strip()
        if new_name and user_id:
            old_name = by_uid.get(user_id, {}).get("name")
            # 移除舊名字在 _by_name 的映射（若存在）
            if old_name and old_name != new_name and by_name.get(old_name) == user_id:
                del by_name[old_name]
            # 寫入最新綁定
            by_uid[user_id] = {"name": new_name}
            by_name[new_name] = user_id
            if save_users(users):
                status_word = "已更新綁定" if (old_name and old_name != new_name) else "已綁定"
                confirm = f"{status_word}：{new_name} ✅\n你的 userId 是：{user_id}"
                reply_text = confirm
            else:
                reply_text = "❌ 連結失敗，檔案寫入錯誤。"
        else:
            reply_text = "❌ 請輸入格式：連結 您的全名"

    # 其他訊息
    else:
        bound_name = by_uid.get(user_id, {}).get("name")
        if bound_name:
            reply_text = "抱歉 目前尚未有其他功能"
        else:
            reply_text = '請輸入"連結 您的全名"進行綁定'

    try:
        with ApiClient(config) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    except ApiException as e:
        print("[LINE][ERROR] 回覆失敗:", getattr(e, "status", None), getattr(e, "body", None))

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
