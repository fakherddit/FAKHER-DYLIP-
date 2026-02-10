#!/usr/bin/env python3
"""
ST FAMILY - Bypass Offset Distribution Bot
Telegram bot for managing and distributing OB52 bypass offsets
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from cryptography.fernet import Fernet

# Configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8216359066:AAEt2GFGgTBp3hh_znnJagH3h1nN5A_XQf0')
ADMIN_IDS = [7210704553]  # Admin Telegram user ID
DB_PATH = 'bypass_server.db'
OFFSETS_FILE = 'ob52_offsets.json'
ENCRYPTION_KEY = Fernet.generate_key()  # Generate once and save

# Initialize encryption
cipher = Fernet(ENCRYPTION_KEY)

# Database initialization
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # License keys table
    c.execute('''CREATE TABLE IF NOT EXISTS license_keys (
        key TEXT PRIMARY KEY,
        created_at TEXT,
        expires_at TEXT,
        device_id TEXT,
        status TEXT,
        last_used TEXT,
        request_count INTEGER DEFAULT 0
    )''')
    
    # Offsets history table
    c.execute('''CREATE TABLE IF NOT EXISTS offset_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT,
        offsets TEXT,
        uploaded_by INTEGER,
        uploaded_at TEXT,
        status TEXT
    )''')
    
    # Access logs
    c.execute('''CREATE TABLE IF NOT EXISTS access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_key TEXT,
        device_id TEXT,
        ip_address TEXT,
        timestamp TEXT,
        action TEXT
    )''')
    
    conn.commit()
    conn.close()

# License key generation
def generate_license_key(days=30):
    """Generate a unique license key"""
    timestamp = str(datetime.now().timestamp())
    random_str = os.urandom(16).hex()
    key = hashlib.sha256(f"{timestamp}{random_str}".encode()).hexdigest()[:16].upper()
    formatted_key = f"ST-{key[:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created = datetime.now().isoformat()
    expires = datetime.fromtimestamp(datetime.now().timestamp() + (days * 86400)).isoformat()
    c.execute('INSERT INTO license_keys VALUES (?, ?, ?, ?, ?, ?, ?)',
              (formatted_key, created, expires, None, 'active', None, 0))
    conn.commit()
    conn.close()
    
    return formatted_key

# Load current offsets
def load_offsets():
    """Load offsets from JSON file"""
    try:
        with open(OFFSETS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "version": "OB52",
            "last_update": datetime.now().isoformat(),
            "offsets": {
                "BAN_CHECK_1": "0x671CB8C",
                "BAN_CHECK_2": "0x0",
                "BAN_REPORT": "0x0",
                "DETECT_CHEAT_1": "0x0",
                "DETECT_CHEAT_2": "0x0",
                "DETECT_MEMORY": "0x0",
                "REPORT_PLAYER": "0x0",
                "REPORT_SEND": "0x0",
                "SECURITY_CHECK_1": "0x671CB8C",
                "SECURITY_CHECK_2": "0x0"
            }
        }

# Save offsets
def save_offsets(offsets_data, admin_id):
    """Save offsets to file and log to database"""
    with open(OFFSETS_FILE, 'w') as f:
        json.dump(offsets_data, f, indent=2)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO offset_history VALUES (?, ?, ?, ?, ?, ?)',
              (None, offsets_data['version'], json.dumps(offsets_data['offsets']),
               admin_id, datetime.now().isoformat(), 'active'))
    conn.commit()
    conn.close()

# Encrypt offsets for distribution
def encrypt_offsets(offsets_data):
    """Encrypt offsets for secure distribution"""
    offsets_json = json.dumps(offsets_data)
    encrypted = cipher.encrypt(offsets_json.encode())
    return encrypted.hex()

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Access denied. Admin only.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Server Status", callback_data='status')],
        [InlineKeyboardButton("🔑 Generate Key", callback_data='generate_key')],
        [InlineKeyboardButton("📝 View Keys", callback_data='view_keys')],
        [InlineKeyboardButton("⚙️ Manage Offsets", callback_data='manage_offsets')],
        [InlineKeyboardButton("📈 Statistics", callback_data='stats')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎮 *ST FAMILY Bypass Server*\n\n"
        "Admin Control Panel\n"
        "Select an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show server status"""
    query = update.callback_query
    await query.answer()
    
    offsets = load_offsets()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM license_keys WHERE status="active"')
    active_keys = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM access_logs WHERE date(timestamp) = date("now")')
    today_requests = c.fetchone()[0]
    conn.close()
    
    # Count valid offsets
    valid_offsets = sum(1 for v in offsets['offsets'].values() if v != "0x0")
    total_offsets = len(offsets['offsets'])
    
    status_text = (
        f"📊 *Server Status*\n\n"
        f"🔐 Active Keys: {active_keys}\n"
        f"📡 Today's Requests: {today_requests}\n"
        f"🎯 Offset Version: {offsets['version']}\n"
        f"✅ Valid Offsets: {valid_offsets}/{total_offsets}\n"
        f"📅 Last Update: {offsets['last_update'][:10]}\n"
        f"🟢 Status: Online"
    )
    
    await query.edit_message_text(status_text, parse_mode='Markdown')

async def generate_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate new license key"""
    query = update.callback_query
    await query.answer()
    
    key = generate_license_key(days=30)
    
    await query.edit_message_text(
        f"🔑 *New License Key Generated*\n\n"
        f"`{key}`\n\n"
        f"✅ Valid for: 30 days\n"
        f"📋 Copy and share with user",
        parse_mode='Markdown'
    )

async def view_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all license keys"""
    query = update.callback_query
    await query.answer()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT key, status, expires_at, request_count FROM license_keys ORDER BY created_at DESC LIMIT 10')
    keys = c.fetchall()
    conn.close()
    
    if not keys:
        await query.edit_message_text("No license keys found.")
        return
    
    text = "🔑 *Recent License Keys*\n\n"
    for key, status, expires, count in keys:
        status_emoji = "✅" if status == "active" else "❌"
        text += f"{status_emoji} `{key}`\n"
        text += f"   Expires: {expires[:10]} | Uses: {count}\n\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def manage_offsets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show offset management menu"""
    query = update.callback_query
    await query.answer()
    
    offsets = load_offsets()
    
    text = "⚙️ *Current Offsets*\n\n"
    for name, value in offsets['offsets'].items():
        status = "✅" if value != "0x0" else "⚠️"
        text += f"{status} `{name}`: `{value}`\n"
    
    text += f"\n📝 Version: {offsets['version']}\n"
    text += f"🔄 Last Update: {offsets['last_update'][:19]}\n\n"
    text += "Use /setoffset <name> <value> to update"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def set_offset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a specific offset value"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Access denied.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /setoffset <name> <value>\n"
            "Example: /setoffset BAN_CHECK_1 0x1234567"
        )
        return
    
    offset_name = context.args[0].upper()
    offset_value = context.args[1]
    
    # Validate hex format
    if not offset_value.startswith('0x'):
        await update.message.reply_text("❌ Value must start with 0x")
        return
    
    offsets = load_offsets()
    
    if offset_name not in offsets['offsets']:
        await update.message.reply_text(f"❌ Unknown offset: {offset_name}")
        return
    
    offsets['offsets'][offset_name] = offset_value
    offsets['last_update'] = datetime.now().isoformat()
    save_offsets(offsets, user_id)
    
    await update.message.reply_text(
        f"✅ Updated!\n"
        f"`{offset_name}` = `{offset_value}`",
        parse_mode='Markdown'
    )

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed statistics"""
    query = update.callback_query
    await query.answer()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Total keys
    c.execute('SELECT COUNT(*) FROM license_keys')
    total_keys = c.fetchone()[0]
    
    # Active keys
    c.execute('SELECT COUNT(*) FROM license_keys WHERE status="active"')
    active_keys = c.fetchone()[0]
    
    # Total requests
    c.execute('SELECT COUNT(*) FROM access_logs')
    total_requests = c.fetchone()[0]
    
    # Today's requests
    c.execute('SELECT COUNT(*) FROM access_logs WHERE date(timestamp) = date("now")')
    today_requests = c.fetchone()[0]
    
    # Most active key
    c.execute('SELECT key, request_count FROM license_keys ORDER BY request_count DESC LIMIT 1')
    top_key = c.fetchone()
    
    conn.close()
    
    text = (
        f"📈 *Detailed Statistics*\n\n"
        f"🔑 Total Keys: {total_keys}\n"
        f"✅ Active Keys: {active_keys}\n"
        f"❌ Inactive Keys: {total_keys - active_keys}\n\n"
        f"📡 Total Requests: {total_requests}\n"
        f"📅 Today's Requests: {today_requests}\n\n"
    )
    
    if top_key:
        text += f"🏆 Most Active Key:\n`{top_key[0]}` ({top_key[1]} uses)"
    
    await query.edit_message_text(text, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    
    handlers = {
        'status': status,
        'generate_key': generate_key_callback,
        'view_keys': view_keys,
        'manage_offsets': manage_offsets,
        'stats': get_stats
    }
    
    handler = handlers.get(query.data)
    if handler:
        await handler(update, context)

def main():
    """Start the bot"""
    print("🚀 Initializing ST FAMILY Bypass Server Bot...")
    
    # Initialize database
    init_db()
    print("✅ Database initialized")
    
    # Create default offsets file if not exists
    if not os.path.exists(OFFSETS_FILE):
        save_offsets(load_offsets(), 0)
        print("✅ Default offsets created")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setoffset", set_offset))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Bot is running...")
    print(f"📋 Encryption key: {ENCRYPTION_KEY.decode()}")
    print("⚠️  Save this key for the API server!")
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
