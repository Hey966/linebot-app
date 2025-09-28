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
    mac = hmac.new(CHANNEL_SECRET.en# -*- coding: utf-8 -*-
import os, json, atexit, subprocess, time, requests
from pathlib import Path
from flask import Flask, request, abort

# === 以此檔所在資料夾為工作目錄（.env / users.json 同層） ===
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# === 讀取 .env（若存在） ===
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    print("[ENV] loaded .env")
except Exception as e:
    print("[ENV][WARN] python-dotenv 未載入：", e)

# === OpenMP 臨時設定（可留） ===
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("ORT_NUM_THREADS", "1")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")

# ===== LINE Bot v3 =====
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.exceptions import InvalidSignatureError
# ApiException 位置因版本不同做相容處理
try:
    from linebot.v3.messaging.exceptions import ApiException
except Exception:
    try:
        from linebot.v3.exceptions import ApiException
    except Exception:
        ApiException = Exception

# ===== 自動啟動 ngrok =====
def start_ngrok(port=5000):
    if os.environ.get("START_NGROK", "1") != "1":
        print("[NGROK] 跳過啟動（START_NGROK=0）"); return None, None
    ngrok_exe = os.environ.get("NGROK", "ngrok")
    try:
        proc = subprocess.Popen(
            [ngrok_exe, "http", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    except FileNotFoundError:
        print("[NGROK][ERROR] 找不到 ngrok，可在 .env 設 NGROK=完整路徑"); return None, None

    public_url = None
    for _ in range(60):
        try:
            j = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=0.5).json()
            for t in j.get("tunnels", []):
                if t.get("proto") == "https":
                    public_url = t.get("public_url"); break
            if public_url: break
        except Exception:
            pass
        time.sleep(0.5)

    if public_url:
        full = f"{public_url}/webhook"
        print(f"[NGROK] ✅ {full}")
        try:
            subprocess.run(f'echo {full}| clip', shell=True)
            print("[NGROK] 已將 /webhook URL 複製到剪貼簿。")
        except Exception:
            pass
    else:
        print("[NGROK][WARN] 逾時；請開 http://127.0.0.1:4040 查看")
    atexit.register(lambda: (proc.poll() is None) and proc.terminate())
    return proc, public_url

# ===== users.json 操作 =====
USERS_JSON = "users.json"
def load_users():
    try:
        with open(USERS_JSON, "r", encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError:
        return {"_by_user_id": {}, "_by_name": {}}
    except Exception as e:
        print("[USERS][ERROR] 讀取失敗", e); return {"_by_user_id": {}, "_by_name": {}}

def save_users(data):
    try:
        with open(USERS_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("[USERS][ERROR] 寫入失敗", e); return False

# ===== 設定 =====
PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "0.0.0.0")
CHANNEL_ACCESS_TOKEN = (os.environ.get("CHANNEL_ACCESS_TOKEN") or "").strip()
CHANNEL_SECRET       = (os.environ.get("CHANNEL_SECRET") or "").strip()

print("[CONFIG] SECRET len =", len(CHANNEL_SECRET or "0"))
print("[CONFIG] TOKEN  len =", len(CHANNEL_ACCESS_TOKEN or "0"))

# 缺金鑰直接中止
if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    raise SystemExit("[FATAL] 缺少 CHANNEL_SECRET 或 CHANNEL_ACCESS_TOKEN。請在 .env 或環境變數設定後再啟動。")

app = Flask(__name__)
handler = WebhookHandler(CHANNEL_SECRET)
config  = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

@app.route("/health", methods=["GET"])
def health(): return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK", 200

# ===== 測試用推播端點 =====
@app.route("/push", methods=["GET"])
def push_to_name():
    name = (request.args.get("name") or "").strip()
    text = (request.args.get("text") or "測試訊息").strip()
    if not name: return "缺少 ?name=參數", 400
    users = load_users()
    user_id = users.get("_by_name", {}).get(name)
    if not user_id: return f"找不到此姓名的綁定：{name}", 404
    try:
        with ApiClient(config) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
            )
        return f"Push 成功 → {name} ({user_id})：{text}", 200
    except ApiException as e:
        return f"Push 失敗 status={getattr(e,'status',None)}, body={getattr(e,'body',None)}", 500

# ===== 處理訊息事件 =====
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = getattr(event.source, "user_id", None)
    text = (event.message.text or "").strip()
    reply_text = None
    print(f"[EVENT] userId={user_id}, text={text}")

    users = load_users()
    by_uid  = users.setdefault("_by_user_id", {})
    by_name = users.setdefault("_by_name", {})

    # ---------- 指令：查詢 ----------
    if text.startswith("查詢"):
        bound_name = by_uid.get(user_id, {}).get("name")
        if bound_name:
            reply_text = f"目前已綁定 {bound_name} ✅"
        else:
            reply_text = "目前尚未綁定 請先進行綁定"

    # ---------- 指令：連結 <姓名> ----------
    elif text.startswith("連結 "):
        new_name = text[3:].strip()
        if new_name and user_id:
            old_name = by_uid.get(user_id, {}).get("name")

            # 1) 若此 user_id 之前已綁過其他名字，先把舊名字從 _by_name 移除
            if old_name and old_name != new_name and by_name.get(old_name) == user_id:
                del by_name[old_name]

            # 2) 以 user_id 為主綁定最新名字
            by_uid[user_id] = {"name": new_name}

            # 3) _by_name 以「最後一次連結」為準
            by_name[new_name] = user_id

            if save_users(users):
                status_word = "已更新綁定" if (old_name and old_name != new_name) else "已綁定"
                confirm = f"{status_word}：{new_name} ✅\n你的 userId 是：{user_id}"
                reply_text = "已透過推播發送綁定資訊 ✅"
                try:
                    with ApiClient(config) as api_client:
                        MessagingApi(api_client).push_message(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=confirm)]
                            )
                        )
                    print(f"[LINE] Push 綁定確認 → {user_id}: {confirm}")
                except ApiException as e_push:
                    print("[LINE][ERROR][push-confirm] status=", getattr(e_push,"status",None),
                          "body=", getattr(e_push,"body",None))
                    reply_text = confirm
            else:
                reply_text = "❌ 連結失敗，檔案寫入錯誤。"
        else:
            reply_text = '❌ 請輸入格式：連結 您的全名'

    # ---------- 其他內容 ----------
    else:
        # 已綁定與未綁定的不同提示
        bound_name = by_uid.get(user_id, {}).get("name")
        if bound_name:
            reply_text = "抱歉 目前尚未有其他功能"
        else:
            reply_text = '請輸入"連結 您的全名"進行綁定'

    # 送出 reply（若失敗再 fallback push）
    try:
        with ApiClient(config) as api_client:
            api = MessagingApi(api_client)
            try:
                api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    )
                )
                print(f"[LINE] Reply 成功 → {user_id}: {reply_text}")
            except ApiException as e:
                print("[LINE][ERROR][reply] status=", getattr(e,"status",None),
                      "body=", getattr(e,"body",None))
                if user_id:
                    try:
                        api.push_message(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=f"(fallback) {reply_text}")]
                            )
                        )
                        print(f"[LINE] Push 成功 → {user_id}: {reply_text}")
                    except ApiException as e2:
                        print("[LINE][ERROR][push] status=", getattr(e2,"status",None),
                              "body=", getattr(e2,"body",None))
    except Exception as e:
        print("[LINE][ERROR] 外層錯誤:", e)

# ===== 進入點 =====
if __name__ == "__main__":
    _, public_url = start_ngrok(port=PORT)
    if public_url:
        print("[提示] 到 LINE Developers 貼上：", f"{public_url}/webhook")
        print("      並確保 Use webhook = ON，再按 Verify。")
    print(f"[FLASK] http://127.0.0.1:{PORT}  /  http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT)
code("utf-8"), raw_body, hashlib.sha256).digest()
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
