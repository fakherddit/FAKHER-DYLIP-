import os
import re
import json
import random
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import time
from functools import wraps

import psycopg2
import psycopg2.extras
import psycopg2.pool
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Connection pool to prevent blocking
db_pool = None

DEFAULT_DB_URL = (
    "postgresql://dylip_key_user:TwbqpTuAggFaAXhIX7Q7pMmJIih5vEQe@"
    "dpg-d5v88bl6ubrc73c8tlqg-a.oregon-postgres.render.com/dylip_key"
)

DB_URL = os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", DEFAULT_DB_URL))
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8216359066:AAEt2GFGgTBp3hh_znnJagH3h1nN5A_XQf0",
)
TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "7210704553"))

KEY_REGEX = re.compile(r"^[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$", re.I)
GLOBAL_KEY_REGEX = re.compile(r"^GLB-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$", re.I)


def get_db_connection():
    """Get database connection with SSL fallback"""
    try:
        # Try with prefer SSL (most compatible)
        conn = psycopg2.connect(DB_URL, sslmode='prefer', connect_timeout=10)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"[DB] Connection attempt 1 failed: {e}")
        try:
            # Try without SSL
            conn = psycopg2.connect(DB_URL, connect_timeout=10)
            conn.autocommit = True
            return conn
        except Exception as e2:
            print(f"[DB] Connection attempt 2 failed: {e2}")
            # Try with allow SSL
            conn = psycopg2.connect(DB_URL, sslmode='allow', connect_timeout=10)
            conn.autocommit = True
            return conn

def return_db_connection(conn):
    """Close database connection"""
    try:
        conn.close()
    except:
        pass
def get_status(conn, key):
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM server_settings WHERE key = %s LIMIT 1", (key,))
            row = cur.fetchone()
        if not row:
            return True
        return str(row[0]) == "1"  # Fix: use row[0] not row[1]
    except Exception as e:
        print(f"[ERROR] get_status: {e}")
        return True

def get_status(conn, key):
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM server_settings WHERE key = %s LIMIT 1", (key,))
        row = cur.fetchone()
    if not row:
        return True
    return str(row[0]) == "1"


@app.before_request
def check_server_enabled():
    path = request.path
    if path in ("/health", "/telegram-webhook"):
        return None
    conn = None
    try:
        conn = get_db_connection()
        if not get_status(conn, "server_enabled"):
            return jsonify({"error": "Server temporarily disabled by admin"}), 503
    finally:
        if conn:
            return_db_connection(conn)
    return None


@app.get("/")
@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "ST FAMILY License Server"})


@app.post("/validate")
def validate_key():
    start_time = time.time()
    payload = request.get_json(silent=True) or {}
    key = payload.get("key", "").strip()
    hwid = payload.get("hwid", "").strip()

    if not key or not hwid:
        return jsonify({"valid": False, "message": "Invalid request: Missing key or HWID"})

    conn = None
    try:
        conn = get_db_connection()
        if not get_status(conn, "key_validation_enabled"):
            return jsonify({"valid": False, "message": "Key validation temporarily disabled"})

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM licenses
                WHERE license_key = %s
                  AND expiry_date > NOW()
                  AND status = 'active'
                  AND (
                    key_type LIKE 'global_%'
                    OR hwid = %s
                    OR hwid IS NULL
                    OR hwid = ''
                  )
                LIMIT 1
                """,
                (key, hwid),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"valid": False, "message": "Invalid key or already bound to another device"})

        is_global = str(row.get("key_type", ""))
        is_global = is_global.startswith("global_")

        with conn.cursor() as cur:
            if not is_global and not row.get("hwid"):
                cur.execute(
                    "UPDATE licenses SET hwid = %s, last_used = NOW() WHERE license_key = %s",
                    (hwid, key),
                )
            else:
                cur.execute(
                    "UPDATE licenses SET last_used = NOW() WHERE license_key = %s",
                    (key,),
                )

        elapsed = time.time() - start_time
        print(f"[VALIDATE] Key validated in {elapsed:.2f}s")
        
        return jsonify(
            {
                "valid": True,
                "message": "Key activated successfully!",
                "expiry_date": row.get("expiry_date"),
            }
        )
    except Exception as e:
        print(f"[ERROR] Validation failed: {str(e)}")
        return jsonify({"valid": False, "message": "Server error"}), 500
    finally:
        if conn:
            return_db_connection(conn)


@app.get("/generate")
def generate_api():
    count = max(1, int(request.args.get("count", 1)))
    days = max(1, int(request.args.get("days", 30)))

    conn = None
    try:
        conn = get_db_connection()
        if not get_status(conn, "key_creation_enabled"):
            return jsonify({"success": False, "message": "Key creation disabled"}), 403

        keys = []
        expiry = datetime.now(timezone.utc) + timedelta(days=days)
        with conn.cursor() as cur:
            for _ in range(count):
                key = "{:04X}-{:04X}-{:04X}-{:04X}".format(
                    random.randint(0, 0xFFFF),
                    random.randint(0, 0xFFFF),
                    random.randint(0, 0xFFFF),
                    random.randint(0, 0xFFFF),
                )
                cur.execute(
                    "INSERT INTO licenses (license_key, expiry_date, key_type) VALUES (%s, %s, %s)",
                    (key, expiry, "standard"),
                )
                keys.append({"key": key, "expiry_date": expiry.isoformat()})

        return jsonify({"success": True, "message": f"{len(keys)} keys generated", "keys": keys})
    except Exception as e:
        print(f"[ERROR] Generate failed: {str(e)}")
        return jsonify({"success": False, "message": "Server error"}), 500
    finally:
        if conn:
            return_db_connection(conn)


@app.post("/telegram-webhook")
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    if not update:
        return "", 200

    message = update.get("message")
    callback_query = update.get("callback_query")

    conn = None
    try:
        conn = get_db_connection()
        if callback_query:
            chat_id = callback_query["message"]["chat"]["id"]
            data = callback_query.get("data", "")

            if data.startswith("gen_"):
                _, count, days = data.split("_")
                generate_keys(chat_id, int(count), int(days), "standard", conn)
            elif data.startswith("global_"):
                _, key_type = data.split("_")
                generate_global_key(chat_id, key_type, conn)
            elif data == "server_toggle":
                toggle_status(chat_id, "server_enabled", "Server", conn)
            elif data == "validation_toggle":
                toggle_status(chat_id, "key_validation_enabled", "Validation", conn)
            elif data == "creation_toggle":
                toggle_status(chat_id, "key_creation_enabled", "Creation", conn)
            elif data == "delete_expired":
                delete_expired(chat_id, conn)

            answer_callback_query(callback_query["id"])
            return "", 200

        if message:
            chat_id = message["chat"]["id"]
            text = (message.get("text") or "").strip()
            user_id = message["from"]["id"]

            if user_id != TELEGRAM_ADMIN_ID:
                send_message(chat_id, "⛔ Unauthorized")
                return "", 200

            if text == "/start":
                send_main_menu(chat_id)
            elif text == "/generate":
                send_generate_menu(chat_id)
            elif text == "/global":
                send_global_menu(chat_id)
            elif text == "/control":
                send_control_menu(chat_id, conn)
            elif text == "/stats":
                send_stats(chat_id, conn)
            elif text == "/list":
                list_active_keys(chat_id, conn)
            elif KEY_REGEX.match(text) or GLOBAL_KEY_REGEX.match(text):
                lookup_key(chat_id, text, conn)

        return "", 200
    except Exception as e:
        print(f"[ERROR] Webhook failed: {str(e)}")
        return "", 200
    finally:
        if conn:
            return_db_connection(conn)


# Telegram helpers

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    requests.post(url, data=data, timeout=10)


def answer_callback_query(callback_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    requests.post(url, data={"callback_query_id": callback_id}, timeout=10)


def send_main_menu(chat_id):
    text = "🎮 <b>ST FAMILY License Bot</b>\n\n"
    text += "/generate - Standard keys\n"
    text += "/global - Global keys (unlimited users)\n"
    text += "/control - Server controls\n"
    text += "/stats - Statistics\n"
    text += "/list - List keys"
    send_message(chat_id, text)


def send_generate_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "1 Key - 7 Days", "callback_data": "gen_1_7"},
                {"text": "1 Key - 30 Days", "callback_data": "gen_1_30"},
            ],
            [
                {"text": "5 Keys - 30 Days", "callback_data": "gen_5_30"},
                {"text": "10 Keys - 30 Days", "callback_data": "gen_10_30"},
            ],
            [
                {"text": "1 Key - Lifetime", "callback_data": "gen_1_3650"},
                {"text": "5 Keys - Lifetime", "callback_data": "gen_5_3650"},
            ],
        ]
    }
    send_message(chat_id, "🔑 Generate Standard Keys", keyboard)


def send_global_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🌍 Global Day", "callback_data": "global_day"}],
            [{"text": "🌍 Global Week", "callback_data": "global_week"}],
            [{"text": "🌍 Global Month", "callback_data": "global_month"}],
        ]
    }
    send_message(chat_id, "🌐 Global Keys (Unlimited Users)", keyboard)


def send_control_menu(chat_id, conn):
    server = get_status(conn, "server_enabled")
    validation = get_status(conn, "key_validation_enabled")
    creation = get_status(conn, "key_creation_enabled")

    text = "⚙️ <b>Control Panel</b>\n\n"
    text += ("🟢" if server else "🔴") + " Server\n"
    text += ("🟢" if validation else "🔴") + " Validation\n"
    text += ("🟢" if creation else "🔴") + " Creation"

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔴 Stop Server" if server else "🟢 Start Server",
                    "callback_data": "server_toggle",
                }
            ],
            [
                {
                    "text": "🔴 Disable Validation" if validation else "🟢 Enable Validation",
                    "callback_data": "validation_toggle",
                }
            ],
            [
                {
                    "text": "🔴 Disable Creation" if creation else "🟢 Enable Creation",
                    "callback_data": "creation_toggle",
                }
            ],
            [{"text": "🗑️ Delete Expired", "callback_data": "delete_expired"}],
        ]
    }
    send_message(chat_id, text, keyboard)


def generate_keys(chat_id, count, days, key_type, conn):
    if not get_status(conn, "key_creation_enabled"):
        send_message(chat_id, "❌ Creation disabled")
        return

    keys = []
    expiry = datetime.now(timezone.utc) + timedelta(days=days)
    with conn.cursor() as cur:
        for _ in range(count):
            key = "{:04X}-{:04X}-{:04X}-{:04X}".format(
                random.randint(0, 0xFFFF),
                random.randint(0, 0xFFFF),
                random.randint(0, 0xFFFF),
                random.randint(0, 0xFFFF),
            )
            cur.execute(
                "INSERT INTO licenses (license_key, expiry_date, key_type) VALUES (%s, %s, %s)",
                (key, expiry, key_type),
            )
            keys.append(key)

    duration = "Lifetime" if days >= 3650 else f"{days} Days"
    text = f"✅ Generated {count} Key(s) - {duration}\n\n<code>" + "\n".join(keys) + "</code>"
    send_message(chat_id, text)


def generate_global_key(chat_id, key_type, conn):
    if not get_status(conn, "key_creation_enabled"):
        send_message(chat_id, "❌ Creation disabled")
        return

    days = {"day": 1, "week": 7, "month": 30}.get(key_type, 1)
    key = "GLB-{:04X}-{:04X}-{:04X}".format(
        random.randint(0, 0xFFFF),
        random.randint(0, 0xFFFF),
        random.randint(0, 0xFFFF),
    )
    expiry = datetime.now(timezone.utc) + timedelta(days=days)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO licenses (license_key, expiry_date, key_type) VALUES (%s, %s, %s)",
            (key, expiry, f"global_{key_type}"),
        )

    text = (
        f"🌐 Global {key_type} Key\n\n<code>{key}</code>\n\n✅ Unlimited users\n⏰ {days} day(s)"
    )
    send_message(chat_id, text)


def toggle_status(chat_id, key, name, conn):
    current = get_status(conn, key)
    new_value = "0" if current else "1"
    with conn.cursor() as cur:
        cur.execute("UPDATE server_settings SET value = %s WHERE key = %s", (new_value, key))
    state = "enabled" if new_value == "1" else "disabled"
    send_message(chat_id, ("🟢" if new_value == "1" else "🔴") + f" {name} {state}")


def delete_expired(chat_id, conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM licenses WHERE expiry_date < NOW()")
        deleted = cur.rowcount
    send_message(chat_id, f"🗑️ Deleted {deleted} expired keys")


def send_stats(chat_id, conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM licenses")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM licenses WHERE status = 'active' AND expiry_date > NOW()")
        active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM licenses WHERE hwid IS NOT NULL")
        used = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM licenses WHERE key_type LIKE 'global_%'")
        global_keys = cur.fetchone()[0]

    text = (
        "📊 <b>Statistics</b>\n\n"
        f"📦 Total: {total}\n"
        f"✅ Active: {active}\n"
        f"🔗 Used: {used}\n"
        f"🌐 Global: {global_keys}"
    )
    send_message(chat_id, text)


def list_active_keys(chat_id, conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT license_key, hwid, expiry_date, key_type
            FROM licenses
            WHERE status = 'active' AND expiry_date > NOW()
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()

    text = "🔑 Active Keys (Last 20)\n\n"
    for row in rows:
        is_global = str(row.get("key_type", "")).startswith("global_")
        status = "🌐 Global" if is_global else ("🔗 Bound" if row.get("hwid") else "⚪ Available")
        text += f"<code>{row['license_key']}</code> {status}\n"

    send_message(chat_id, text)


def lookup_key(chat_id, key, conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM licenses WHERE license_key = %s", (key,))
        row = cur.fetchone()

    if not row:
        send_message(chat_id, "❌ Key not found")
        return

    is_global = str(row.get("key_type", "")).startswith("global_")
    text = f"🔍 Key: <code>{key}</code>\n"
    text += "Type: " + ("🌐 Global" if is_global else "Standard") + "\n"
    text += "Status: " + ("✅" if row.get("status") == "active" else "❌") + f" {row.get('status')}\n"
    text += "Expires: " + row.get("expiry_date").strftime("%Y-%m-%d %H:%M")
    send_message(chat_id, text)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
