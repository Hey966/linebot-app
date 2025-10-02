# -*- coding: utf-8 -*-
import os, json, atexit, subprocess, time, requests, shutil
from pathlib import Path
from urllib.parse import urljoin
from flask import Flask, request, abort

# === 以此檔所在資料夾為工作目錄（.env / users.json 同層） ===
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# === 讀取 .env（若存在）＋偵錯 ===
def _safe_len(v): return 0 if not v else len(v)
def _mask(v, keep=4):
    if not v: return "(empty)"
    return v[:keep] + "*" * max(0, len(v) - keep)

dotenv_loaded = False
try:
    from dotenv import load_dotenv, dotenv_values
    dotenv_path = BASE_DIR / ".env"
    print(f"[ENV] target: {dotenv_path} exists={dotenv_path.exists()}")
    if dotenv_path.exists():
        print("[ENV] keys in .env:", list(dotenv_values(dotenv_path, encoding="utf-8").keys()))
    load_dotenv(dotenv_path, override=True, encoding="utf-8")
    dotenv_loaded = True
    print("[ENV] loaded .env =", dotenv_loaded)
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
try:
    from linebot.v3.messaging.exceptions import ApiException
except Exception:
    try:
        from linebot.v3.exceptions import ApiException
    except Exception:
        ApiException = Exception

# ===== 自動啟動 ngrok（本機用；Render 自動停用） =====
def _env_bool(name, default=False):
    v = os.environ.get(name, str(int(default))).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

def _find_ngrok_exe():
    p = (os.environ.get("NGROK") or "").strip().strip('"')
    if p and os.path.isfile(p): return p
    p2 = shutil.which("ngrok")
    if p2: return p2
    for cand in (r"C:\tools\ngrok\ngrok.exe", r"C:\ngrok\ngrok.exe", "/usr/local/bin/ngrok", "/usr/bin/ngrok"):
        if os.path.isfile(cand): return cand
    return None

def _kill_ngrok_silent():
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-f", "ngrok"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _probe_public_url(timeout=25):
    api = "http://127.0.0.1:4040/api/tunnels"
    end = time.time() + timeout
    last_err = None
    while time.time() < end:
        try:
            r = requests.get(api, timeout=2)
            if r.ok:
                data = r.json()
                for t in data.get("tunnels", []):
                    pub = t.get("public_url", "")
                    if pub.startswith("https://"):
                        return pub
                for t in data.get("tunnels", []):
                    pub = t.get("public_url", "")
                    if pub: return pub
        except Exception as e:
            last_err = e
        time.sleep(0.8)
    raise RuntimeError(f"無法從 4040 取得 public URL：{last_err}")

def start_ngrok_if_needed(local_host="127.0.0.1", port=5000, webhook_path="/webhook"):
    """
    本機：START_NGROK=1 則啟動 ngrok
    Render：若偵測到 RENDER=true/1，則強制停用 ngrok
    """
    on_render = _env_bool("RENDER", False) or bool(os.environ.get("RENDER_EXTERNAL_URL"))
    start_ngrok = _env_bool("START_NGROK", True) and not on_render
    if not start_ngrok:
        reason = "Render 環境" if on_render else "START_NGROK=0"
        print(f"[NGROK] 跳過啟動（{reason}）")
        return None

    exe = _find_ngrok_exe()
    if not exe:
        print("[NGROK][ERROR] 找不到 ngrok，可在 .env 設 NGROK=完整路徑")
        return None

    region = (os.environ.get("NGROK_REGION") or "").strip() or None
    extra  = (os.environ.get("NGROK_ARGS") or "").strip() or None

    _kill_ngrok_silent()
    cmd = [exe, "http", f"http://{local_host}:{port}"]
    if region: cmd += ["--region", region]
    if extra:  cmd += extra.split()

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags)
    atexit.register(lambda: (proc.poll() is None) and proc.terminate())

    try:
        public_url = _probe_public_url(timeout=25)
        full = urljoin(public_url + "/", webhook_path.lstrip("/"))
        print(f"[NGROK] public url: {public_url}")
        print(f"[NGROK] Webhook：{full}")
        try:
            if os.name == "nt":
                subprocess.run(f'echo {full}| clip', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[NGROK] 已將 Webhook URL 複製到剪貼簿。")
        except Exception:
            pass
        return public_url
    except Exception as e:
        print("[NGROK][WARN]", e)
        print("[NGROK][HINT] 打開 http://127.0.0.1:4040 檢查 ngrok 狀態。")
        return None
# ===== /自動啟動 ngrok =====

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
# Render 會提供 PORT，否則本機用 5000
PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "0.0.0.0")
CHANNEL_ACCESS_TOKEN = (os.environ.get("CHANNEL_ACCESS_TOKEN") or "").strip()
CHANNEL_SECRET       = (os.environ.get("CHANNEL_SECRET") or "").strip()

print("[CONFIG] SECRET len =", _safe_len(CHANNEL_SECRET), "value:", _mask(CHANNEL_SECRET))
print("[CONFIG] TOKEN  len =", _safe_len(CHANNEL_ACCESS_TOKEN), "value:", _mask(CHANNEL_ACCESS_TOKEN))

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    print("[HINT] 檢查：1) .env 與 app.py 同層、不是 .env.txt；2) 無空格/引號/Bearer；3) UTF-8；4) 已安裝 python-dotenv")
    raise SystemExit("[FATAL] 缺少 CHANNEL_SECRET 或 CHANNEL_ACCESS_TOKEN。")

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

    if text.startswith("查詢"):
        bound_name = by_uid.get(user_id, {}).get("name")
        reply_text = f"目前已綁定 {bound_name} ✅" if bound_name else "目前尚未綁定 請先進行綁定"

    elif text.startswith("連結 "):
        new_name = text[3:].strip()
        if new_name and user_id:
            old_name = by_uid.get(user_id, {}).get("name")
            if old_name and old_name != new_name and by_name.get(old_name) == user_id:
                del by_name[old_name]
            by_uid[user_id] = {"name": new_name}
            by_name[new_name] = user_id
            if save_users(users):
                status_word = "已更新綁定" if (old_name and old_name != new_name) else "已綁定"
                confirm = f"{status_word}：{new_name} ✅\n你的 userId 是：{user_id}"
                reply_text = "已透過推播發送綁定資訊 ✅"
                try:
                    with ApiClient(config) as api_client:
                        MessagingApi(api_client).push_message(
                            PushMessageRequest(to=user_id, messages=[TextMessage(text=confirm)])
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

    else:
        bound_name = by_uid.get(user_id, {}).get("name")
        reply_text = "抱歉 目前尚未有其他功能" if bound_name else '請輸入"連結 您的全名"進行綁定'

    try:
        with ApiClient(config) as api_client:
            api = MessagingApi(api_client)
            try:
                api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
                )
                print(f"[LINE] Reply 成功 → {user_id}: {reply_text}")
            except ApiException as e:
                print("[LINE][ERROR][reply] status=", getattr(e,"status",None), "body=", getattr(e,"body",None))
                if user_id:
                    try:
                        api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=f"(fallback) {reply_text}")]))
                        print(f"[LINE] Push 成功 → {user_id}: {reply_text}")
                    except ApiException as e2:
                        print("[LINE][ERROR][push] status=", getattr(e2,"status",None), "body=", getattr(e2,"body",None))
    except Exception as e:
        print("[LINE][ERROR] 外層錯誤:", e)

# ===== 進入點 =====
if __name__ == "__main__":
    public_url = start_ngrok_if_needed(local_host="127.0.0.1", port=PORT, webhook_path="/webhook")
    if public_url:
        print("[提示] 到 LINE Developers 貼上：", f"{public_url}/webhook")
        print("      並確保 Use webhook = ON，再按 Verify。")
    print(f"[FLASK] http://127.0.0.1:{PORT}  /  http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT)
