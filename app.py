import os
import telebot
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta

# Configuration
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Get from @BotFather
DB_URL = "postgresql://key_dyli_p_new_user:ZzG0MiuxZ4TN04IP22Ae7g750eCgLxAp@dpg-d658hpe3jp1c73ajnb3g-a.oregon-postgres.render.com/key_dyli_p_new"
ADMIN_IDS = [123456789]  # Replace with your Telegram user ID

bot = telebot.TeleBot(BOT_TOKEN)

# Database connection
def get_db():
    return psycopg2.connect(DB_URL, sslmode='prefer')

# Check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Start command
@bot.message_handler(commands=['start'])
def start(message):
    welcome = """
🔐 **ST FAMILY License Bot**

**Available Commands:**
👤 User Commands:
/getkey - Get your license key
/checkkey <key> - Check key status
/mykeys - View all your keys

🔧 Admin Commands:
/generate <days> - Generate key
/genkeys <count> <days> - Generate multiple keys
/revoke <key> - Revoke a key
/stats - Server statistics
/listkeys - List all active keys
/extend <key> <days> - Extend key expiry

Need help? Contact @STXFAMILY
"""
    bot.reply_to(message, welcome, parse_mode='Markdown')

# Get key for user
@bot.message_handler(commands=['getkey'])
def get_key(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Check if user already has an active key
        cur.execute("""
            SELECT license_key, expiry_date FROM licenses 
            WHERE telegram_id = %s AND status = 'active' AND expiry_date > NOW()
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        
        existing = cur.fetchone()
        if existing:
            expiry = existing['expiry_date'].strftime('%Y-%m-%d %H:%M')
            bot.reply_to(message, f"✅ You already have an active key:\n\n`{existing['license_key']}`\n\nExpires: {expiry}", parse_mode='Markdown')
            conn.close()
            return
        
        # Generate new key
        import secrets
        key = '-'.join([''.join(secrets.choice('0123456789ABCDEF') for _ in range(4)) for _ in range(4)])
        expiry = datetime.now() + timedelta(days=30)
        
        cur.execute("""
            INSERT INTO licenses (license_key, key_type, expiry_date, telegram_id, telegram_username, status)
            VALUES (%s, 'standard', %s, %s, %s, 'active')
        """, (key, expiry, user_id, username))
        
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"""
🎉 **Key Generated Successfully!**

`{key}`

📅 Valid until: {expiry.strftime('%Y-%m-%d %H:%M')}
👤 Bound to your Telegram account

✅ **How to use:**
1. Open the game
2. Paste this key when prompted
3. Enjoy!

⚠️ Keep this key private!
""", parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Check key status
@bot.message_handler(commands=['checkkey'])
def check_key(message):
    try:
        key = message.text.split(maxsplit=1)[1].strip()
    except IndexError:
        bot.reply_to(message, "Usage: /checkkey <YOUR-KEY-HERE>")
        return
    
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("SELECT * FROM licenses WHERE license_key = %s", (key,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            bot.reply_to(message, "❌ Key not found")
            return
        
        status = "✅ Active" if row['status'] == 'active' and row['expiry_date'] > datetime.now() else "❌ Inactive/Expired"
        hwid = row['hwid'] or "Not bound yet"
        expiry = row['expiry_date'].strftime('%Y-%m-%d %H:%M')
        
        info = f"""
📊 **Key Information**

Key: `{key}`
Status: {status}
Type: {row['key_type']}
HWID: `{hwid}`
Expires: {expiry}
Created: {row['created_at'].strftime('%Y-%m-%d %H:%M')}
"""
        bot.reply_to(message, info, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# My keys
@bot.message_handler(commands=['mykeys'])
def my_keys(message):
    user_id = message.from_user.id
    
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT license_key, expiry_date, status FROM licenses 
            WHERE telegram_id = %s 
            ORDER BY created_at DESC LIMIT 10
        """, (user_id,))
        
        keys = cur.fetchall()
        conn.close()
        
        if not keys:
            bot.reply_to(message, "❌ You don't have any keys yet. Use /getkey to get one!")
            return
        
        response = "📋 **Your Keys:**\n\n"
        for k in keys:
            status = "✅" if k['status'] == 'active' and k['expiry_date'] > datetime.now() else "❌"
            expiry = k['expiry_date'].strftime('%Y-%m-%d')
            response += f"{status} `{k['license_key']}` - Expires: {expiry}\n"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Admin: Generate key
@bot.message_handler(commands=['generate'])
def admin_generate(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only command")
        return
    
    try:
        days = int(message.text.split()[1])
    except (IndexError, ValueError):
        bot.reply_to(message, "Usage: /generate <days>")
        return
    
    try:
        import secrets
        key = '-'.join([''.join(secrets.choice('0123456789ABCDEF') for _ in range(4)) for _ in range(4)])
        expiry = datetime.now() + timedelta(days=days)
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO licenses (license_key, key_type, expiry_date, status)
            VALUES (%s, 'admin_generated', %s, 'active')
        """, (key, expiry))
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"✅ Generated:\n\n`{key}`\n\nValid for {days} days", parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Admin: Generate multiple keys
@bot.message_handler(commands=['genkeys'])
def admin_gen_keys(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only command")
        return
    
    try:
        parts = message.text.split()
        count = int(parts[1])
        days = int(parts[2])
    except (IndexError, ValueError):
        bot.reply_to(message, "Usage: /genkeys <count> <days>")
        return
    
    if count > 50:
        bot.reply_to(message, "❌ Maximum 50 keys at once")
        return
    
    try:
        import secrets
        conn = get_db()
        cur = conn.cursor()
        keys = []
        expiry = datetime.now() + timedelta(days=days)
        
        for _ in range(count):
            key = '-'.join([''.join(secrets.choice('0123456789ABCDEF') for _ in range(4)) for _ in range(4)])
            cur.execute("""
                INSERT INTO licenses (license_key, key_type, expiry_date, status)
                VALUES (%s, 'bulk_admin', %s, 'active')
            """, (key, expiry))
            keys.append(key)
        
        conn.commit()
        conn.close()
        
        response = f"✅ Generated {count} keys (Valid for {days} days):\n\n"
        response += '\n'.join([f"`{k}`" for k in keys])
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Admin: Revoke key
@bot.message_handler(commands=['revoke'])
def admin_revoke(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only command")
        return
    
    try:
        key = message.text.split(maxsplit=1)[1].strip()
    except IndexError:
        bot.reply_to(message, "Usage: /revoke <key>")
        return
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE licenses SET status = 'revoked' WHERE license_key = %s", (key,))
        
        if cur.rowcount > 0:
            conn.commit()
            bot.reply_to(message, f"✅ Key revoked: `{key}`", parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ Key not found")
        
        conn.close()
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Admin: Stats
@bot.message_handler(commands=['stats'])
def admin_stats(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only command")
        return
    
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("SELECT COUNT(*) as total FROM licenses")
        total = cur.fetchone()['total']
        
        cur.execute("SELECT COUNT(*) as active FROM licenses WHERE status = 'active' AND expiry_date > NOW()")
        active = cur.fetchone()['active']
        
        cur.execute("SELECT COUNT(*) as expired FROM licenses WHERE expiry_date <= NOW()")
        expired = cur.fetchone()['expired']
        
        cur.execute("SELECT COUNT(DISTINCT telegram_id) as users FROM licenses WHERE telegram_id IS NOT NULL")
        users = cur.fetchone()['users']
        
        conn.close()
        
        stats = f"""
📊 **Server Statistics**

Total Keys: {total}
Active Keys: {active}
Expired Keys: {expired}
Total Users: {users}

🕒 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
        bot.reply_to(message, stats, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Admin: List keys
@bot.message_handler(commands=['listkeys'])
def admin_list(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only command")
        return
    
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("""
            SELECT license_key, telegram_username, expiry_date, status 
            FROM licenses 
            WHERE status = 'active' AND expiry_date > NOW()
            ORDER BY expiry_date DESC LIMIT 20
        """)
        
        keys = cur.fetchall()
        conn.close()
        
        if not keys:
            bot.reply_to(message, "❌ No active keys")
            return
        
        response = "📋 **Active Keys (Last 20):**\n\n"
        for k in keys:
            user = k['telegram_username'] or "Anonymous"
            expiry = k['expiry_date'].strftime('%Y-%m-%d')
            response += f"`{k['license_key']}` - @{user} - {expiry}\n"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Admin: Extend key
@bot.message_handler(commands=['extend'])
def admin_extend(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only command")
        return
    
    try:
        parts = message.text.split()
        key = parts[1]
        days = int(parts[2])
    except (IndexError, ValueError):
        bot.reply_to(message, "Usage: /extend <key> <days>")
        return
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE licenses 
            SET expiry_date = expiry_date + INTERVAL '%s days'
            WHERE license_key = %s
        """, (days, key))
        
        if cur.rowcount > 0:
            conn.commit()
            bot.reply_to(message, f"✅ Extended `{key}` by {days} days", parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ Key not found")
        
        conn.close()
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

# Start polling
if __name__ == '__main__':
    print("🤖 Bot started successfully!")
    bot.infinity_polling()
