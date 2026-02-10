import os
import time
import secrets
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

app = Flask(__name__)

# Database configuration
DB_URL = os.getenv("DATABASE_URL", "postgresql://key_dyli_p_new_user:ZzG0MiuxZ4TN04IP22Ae7g750eCgLxAp@dpg-d658hpe3jp1c73ajnb3g-a.oregon-postgres.render.com/key_dyli_p_new")

def get_db_connection():
    """Get database connection with SSL fallback"""
    try:
        conn = psycopg2.connect(DB_URL, sslmode='prefer', connect_timeout=10)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"[DB] Connection attempt 1 failed: {e}")
        try:
            conn = psycopg2.connect(DB_URL, connect_timeout=10)
            conn.autocommit = True
            return conn
        except Exception as e2:
            print(f"[DB] Connection attempt 2 failed: {e2}")
            conn = psycopg2.connect(DB_URL, sslmode='allow', connect_timeout=10)
            conn.autocommit = True
            return conn

def return_db_connection(conn):
    """Close database connection"""
    try:
        conn.close()
    except:
        pass

def init_database():
    """Initialize database tables and settings"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Create licenses table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                id SERIAL PRIMARY KEY,
                license_key VARCHAR(255) UNIQUE NOT NULL,
                key_type VARCHAR(50) DEFAULT 'standard',
                hwid VARCHAR(255),
                expiry_date TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used TIMESTAMP,
                status VARCHAR(20) DEFAULT 'active',
                telegram_id BIGINT,
                telegram_username VARCHAR(255)
            )
        """)
        
        # Create server_settings table with correct structure
        cur.execute("""
            CREATE TABLE IF NOT EXISTS server_settings (
                key VARCHAR(255) PRIMARY KEY,
                value VARCHAR(255) NOT NULL
            )
        """)
        
        # Insert default settings
        cur.execute("""
            INSERT INTO server_settings (key, value) VALUES
                ('server_enabled', '1'),
                ('key_validation_enabled', '1'),
                ('key_creation_enabled', '1')
            ON CONFLICT (key) DO NOTHING
        """)
        
        print("✅ Database initialized successfully.")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
    finally:
        if conn:
            return_db_connection(conn)

# Initialize database on startup
init_database()

def get_status(conn, key):
    """Get server setting status"""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM server_settings WHERE key = %s LIMIT 1", (key,))
            row = cur.fetchone()
        if not row:
            return True
        return str(row[0]) == "1"
    except Exception as e:
        print(f"[ERROR] get_status: {e}")
        return True

@app.before_request
def check_server_enabled():
    """Check if server is enabled before processing requests"""
    path = request.path
    if path in ("/health", "/telegram-webhook", "/"):
        return None
    conn = None
    try:
        conn = get_db_connection()
        if not get_status(conn, "server_enabled"):
            return jsonify({"error": "Server temporarily disabled by admin"}), 503
    except Exception as e:
        print(f"[ERROR] check_server_enabled: {e}")
    finally:
        if conn:
            return_db_connection(conn)
    return None

@app.get("/")
@app.get("/health")
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "ST FAMILY License Server"})

@app.post("/validate")
def validate_key():
    """Validate license key"""
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
            # Check if key exists and is valid
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
                  )
                """,
                (key, hwid)
            )
            row = cur.fetchone()

            if not row:
                print(f"[VALIDATE] ❌ Key {key} not found or invalid")
                return jsonify({"valid": False, "message": "Invalid or expired key"})

            # Bind HWID if not bound yet
            if row['hwid'] is None and not str(row['key_type']).startswith('global_'):
                cur.execute(
                    "UPDATE licenses SET hwid = %s WHERE license_key = %s",
                    (hwid, key)
                )
                print(f"[VALIDATE] Bound key {key} to HWID {hwid}")

            # Update last_used
            cur.execute(
                "UPDATE licenses SET last_used = NOW() WHERE license_key = %s",
                (key,)
            )

            elapsed = time.time() - start_time
            print(f"[VALIDATE] ✅ Valid key: {key} | HWID: {hwid} | Time: {elapsed:.3f}s")

            return jsonify({
                "valid": True,
                "message": "Key activated successfully!",
                "expiry_date": row['expiry_date'].isoformat() if row['expiry_date'] else None,
                "key_type": row['key_type']
            })

    except Exception as e:
        print(f"[VALIDATE] ❌ Error: {e}")
        return jsonify({"valid": False, "message": f"Server error: {str(e)}"})
    finally:
        if conn:
            return_db_connection(conn)

@app.get("/generate")
def generate_keys():
    """Generate license keys"""
    conn = None
    try:
        conn = get_db_connection()
        if not get_status(conn, "key_creation_enabled"):
            return jsonify({"success": False, "message": "Key creation temporarily disabled"}), 503

        count = int(request.args.get("count", 1))
        days = int(request.args.get("days", 30))
        key_type = request.args.get("type", "standard")

        if count > 100:
            return jsonify({"success": False, "message": "Maximum 100 keys per request"}), 400

        keys = []
        expiry_date = datetime.now() + timedelta(days=days)

        with conn.cursor() as cur:
            for _ in range(count):
                key = '-'.join([''.join(secrets.choice('0123456789ABCDEF') for _ in range(4)) for _ in range(4)])
                cur.execute(
                    """
                    INSERT INTO licenses (license_key, key_type, expiry_date, status)
                    VALUES (%s, %s, %s, 'active')
                    """,
                    (key, key_type, expiry_date)
                )
                keys.append({"key": key, "expiry_date": expiry_date.isoformat()})

        print(f"[GENERATE] Created {count} keys, valid for {days} days")
        return jsonify({"success": True, "message": f"{count} keys generated", "keys": keys})

    except Exception as e:
        print(f"[GENERATE] ❌ Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if conn:
            return_db_connection(conn)

@app.delete("/revoke/<key>")
def revoke_key(key):
    """Revoke a license key"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("UPDATE licenses SET status = 'revoked' WHERE license_key = %s", (key,))
            if cur.rowcount > 0:
                print(f"[REVOKE] Key revoked: {key}")
                return jsonify({"success": True, "message": f"Key {key} revoked"})
            else:
                return jsonify({"success": False, "message": "Key not found"}), 404
    except Exception as e:
        print(f"[REVOKE] ❌ Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if conn:
            return_db_connection(conn)

@app.get("/stats")
def get_stats():
    """Get server statistics"""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) as total FROM licenses")
            total = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) as active FROM licenses WHERE status = 'active' AND expiry_date > NOW()")
            active = cur.fetchone()['active']

            cur.execute("SELECT COUNT(*) as expired FROM licenses WHERE expiry_date <= NOW()")
            expired = cur.fetchone()['expired']

            cur.execute("SELECT COUNT(DISTINCT telegram_id) as users FROM licenses WHERE telegram_id IS NOT NULL")
            users = cur.fetchone()['users']

        return jsonify({
            "total_keys": total,
            "active_keys": active,
            "expired_keys": expired,
            "total_users": users
        })
    except Exception as e:
        print(f"[STATS] ❌ Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            return_db_connection(conn)

@app.get("/settings")
def get_settings():
    """Get server settings"""
    conn = None
    try:
        conn = get_db_connection()
        server = get_status(conn, "server_enabled")
        validation = get_status(conn, "key_validation_enabled")
        creation = get_status(conn, "key_creation_enabled")

        return jsonify({
            "server_enabled": server,
            "key_validation_enabled": validation,
            "key_creation_enabled": creation
        })
    except Exception as e:
        print(f"[SETTINGS] ❌ Error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            return_db_connection(conn)

@app.post("/settings/<key>")
def update_setting(key):
    """Update server setting"""
    conn = None
    try:
        if key not in ["server_enabled", "key_validation_enabled", "key_creation_enabled"]:
            return jsonify({"success": False, "message": "Invalid setting key"}), 400

        new_value = request.json.get("value", "1")
        conn = get_db_connection()

        with conn.cursor() as cur:
            cur.execute("UPDATE server_settings SET value = %s WHERE key = %s", (new_value, key))

        print(f"[SETTINGS] Updated {key} = {new_value}")
        return jsonify({"success": True, "message": f"Setting {key} updated"})
    except Exception as e:
        print(f"[SETTINGS] ❌ Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if conn:
            return_db_connection(conn)

@app.post("/telegram-webhook")
def telegram_webhook():
    """Telegram bot webhook endpoint"""
    try:
        data = request.get_json()
        print(f"[TELEGRAM] Webhook received: {data}")
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[TELEGRAM] ❌ Error: {e}")
        return jsonify({"ok": False}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
