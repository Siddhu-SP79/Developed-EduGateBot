
import os
import base64
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from dotenv import load_dotenv
import psycopg2
from contextlib import contextmanager
from waitress import serve

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
BOT_USERNAME = "Potter_model_Bot"
WEBSITE_LINK = os.getenv("WEBSITE_LINK")
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
CORS(app)

@contextmanager
def get_db_connection():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        sslmode='require'
    )
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            file_path TEXT,
            token TEXT UNIQUE,
            description TEXT,
            expiry TIMESTAMP,
            access_count INTEGER DEFAULT 0,
            last_access TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS user_access (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            token TEXT,
            access_expiry TIMESTAMP,
            usage_count INTEGER DEFAULT 0 
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS backup_channels (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS refresh_links (
            id SERIAL PRIMARY KEY,
            url TEXT UNIQUE NOT NULL
        )''')
        conn.commit()
init_db()

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

def generate_token(user_id):
    raw = f"{user_id}:{int(datetime.now().timestamp())}"
    token = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return token

def delete_message_after_24h(chat_id, message_id):
    def delete():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception as e:
            print(f"❌ Failed to delete message {message_id}: {e}")
    threading.Timer(3600, delete).start()

def get_all_backup_channels():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT username FROM backup_channels")
        return [row[0] for row in c.fetchall()]

def get_any_refresh_link():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT url FROM refresh_links ORDER BY RANDOM() LIMIT 1")
        row = c.fetchone()
        return row[0] if row else WEBSITE_LINK

def check_channel_membership(user_id):
    for channel in get_all_backup_channels():
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status in ["member", "administrator", "creator"]:
                return True
        except:
            continue
    return False

# Background task to clean up old files (older than 3 days)
def cleanup_old_files():
    while True:
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                now = datetime.now()
                c.execute("SELECT file_path, token FROM files WHERE expiry < %s", (now,))
                expired_files = c.fetchall()
                
                for path, token in expired_files:
                    if os.path.exists(path):
                        os.remove(path)
                    c.execute("DELETE FROM files WHERE token = %s", (token,))
                
                if expired_files:
                    conn.commit()
                    print(f"🧹 Cleaned up {len(expired_files)} expired files.")
        except Exception as e:
            print(f"Cleanup Error: {e}")
        
        time.sleep(3600)

threading.Thread(target=cleanup_old_files, daemon=True).start()

# ==========================================
# 3. CORE LOGIC (Access & Limit)
# ==========================================

def send_token_expired_ui(msg, reason="expired"): 
    markup = InlineKeyboardMarkup()
    refresh_link = get_any_refresh_link()
    markup.add(InlineKeyboardButton("🔄 Verify Access (Unlock Files)", url=refresh_link)) 
    markup.add(InlineKeyboardButton("📖 How To Open Links?", url="https://t.me/how_to_open_the"))
    
    text = f"👋 Hello {msg.from_user.first_name},\n\n"
    if reason == "limit":
        text += "⚠️ File Limit Reached!!\nYou have accessed your  files. Please refresh to get  more."
    else:
        text += "⚠️ Token Expired or Not Activated.\nPlease refresh to continue."

    sent = bot.send_message(msg.chat.id, text, parse_mode="Markdown", reply_markup=markup)
    delete_message_after_24h(sent.chat.id, sent.message_id)

def send_file_and_increment(user_id, path, desc, file_token, current_usage):
    # 1. Update Database (Increment Usage)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE user_access SET usage_count = usage_count + 1 WHERE user_id = %s", (user_id,))
        c.execute("UPDATE files SET access_count = access_count + 1, last_access = NOW() WHERE token = %s", (file_token,))
        conn.commit()

    # 2. Send File
    notice = bot.send_message(user_id, f"✅ Identity verified. Accessing file... ({current_usage + 1}/4)")
    delete_message_after_24h(user_id, notice.message_id)
    
    with open(path, "rb") as f:
        caption = f"{desc}\n\n📉 Usage: {current_usage + 1}/4 files."
        if path.endswith(".mp4"):
            msg = bot.send_video(user_id, f, caption=caption, protect_content=True)
        elif path.endswith((".jpg", ".jpeg", ".png")):
            msg = bot.send_photo(user_id, f, caption=caption, protect_content=True)
        else:
            msg = bot.send_document(user_id, f, caption=caption, protect_content=True)
            
    delete_message_after_24h(user_id, msg.message_id)
    warning_msg = bot.send_message(user_id, "⏳ This content will be auto-deleted in 3600 Sec.")
    delete_message_after_24h(user_id, warning_msg.message_id)

# ==========================================
# 4. HANDLERS
# ==========================================

@bot.message_handler(commands=["start"])
def handle_start(msg):
    args = msg.text.split(" ")[1:] if len(msg.text.split(" ")) > 1 else []
    if not args:
        send_token_expired_ui(msg)
        return
        
    token_arg = args[0]
    if not token_arg.startswith("token_"):
        bot.reply_to(msg, "⚠️ Invalid token.")
        return
        
    encoded_token = token_arg.replace("token_", "")
    user_id = msg.from_user.id

    # 1. Join Check
    if not check_channel_membership(user_id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Join Backup Channel", url="https://t.me/BACKUP_FAP_KINGDOM"))
        bot.send_message(msg.chat.id, "❗ *Please join the backup channel first.*", parse_mode="Markdown", reply_markup=markup)
        return

    # 2. Database Check
    with get_db_connection() as conn:
        c = conn.cursor()
        
        c.execute("SELECT file_path, description FROM files WHERE token = %s", (encoded_token,))
        file_row = c.fetchone()
        
        if not file_row:
            bot.reply_to(msg, "❌ File not found or expired (Files are deleted after 3 days).")
            return
            
        path, desc = file_row

        # Check User Access Limit
        c.execute("SELECT usage_count, access_expiry FROM user_access WHERE user_id = %s", (user_id,))
        user_row = c.fetchone()

        if user_row:
            usage_count, expiry = user_row
            now = datetime.now()
            
            if expiry < now:
                send_token_expired_ui(msg, reason="expired")
            elif usage_count >= 4:
                send_token_expired_ui(msg, reason="limit")
            else:
                # SUCCESS: Send file & Increment usage only (No Cooldown)
                send_file_and_increment(user_id, path, desc, encoded_token, usage_count)
        else:
            send_token_expired_ui(msg, reason="expired")

@bot.message_handler(content_types=["video", "photo", "document"])
def handle_upload(msg):
    if str(msg.from_user.id) != OWNER_ID:
        return
    prompt = bot.reply_to(msg, "📄 Send file description:")
    bot.register_next_step_handler(prompt, save_file, msg)

def save_file(desc_msg, original_msg):
    desc = desc_msg.text
    file_id = (
        original_msg.video.file_id if original_msg.video else
        original_msg.photo[-1].file_id if original_msg.photo else
        original_msg.document.file_id
    )
    file_info = bot.get_file(file_id)
    data = bot.download_file(file_info.file_path)
    ext = os.path.splitext(file_info.file_path)[-1] or ".bin"
    path = os.path.join(UPLOAD_FOLDER, f"{file_id}{ext}")
    
    with open(path, "wb") as f:
        f.write(data)

    token = generate_token(original_msg.from_user.id)
    
    # Expiry set to 3 DAYS
    expiry = datetime.now() + timedelta(days=3)

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO files (file_path, token, expiry, description)
                     VALUES (%s, %s, %s, %s)''', (path, token, expiry, desc))
        conn.commit()

    share_link = f"https://t.me/{BOT_USERNAME}?start=token_{token}"
    bot.reply_to(original_msg, f"✅ Uploaded! (Auto-deletes in 3 days)\n📄 {desc}\n🔗 Link:\n{share_link}")

# ==========================================
# 5. ADMIN COMMANDS
# ==========================================

@bot.message_handler(commands=["add_backup"])
def add_backup_channel(msg):
    if str(msg.from_user.id) != OWNER_ID: return
    args = msg.text.split(" ")
    if len(args) < 2:
        bot.reply_to(msg, "Usage: /add_backup @channel_username")
        return
    with get_db_connection() as conn:
        conn.cursor().execute("INSERT INTO backup_channels (username) VALUES (%s) ON CONFLICT DO NOTHING", (args[1],))
        conn.commit()
    bot.reply_to(msg, f"✅ Added {args[1]}")

@bot.message_handler(commands=["remove_backup"])
def remove_backup_channel(msg):
    if str(msg.from_user.id) != OWNER_ID: return
    args = msg.text.split(" ")
    if len(args) < 2: return
    with get_db_connection() as conn:
        conn.cursor().execute("DELETE FROM backup_channels WHERE username = %s", (args[1],))
        conn.commit()
    bot.reply_to(msg, f"🗑️ Removed {args[1]}")

@bot.message_handler(commands=["list_backup"])
def list_backup_channels(msg):
    if str(msg.from_user.id) != OWNER_ID: return
    channels = get_all_backup_channels()
    bot.reply_to(msg, "Backup Channels:\n" + "\n".join(channels) if channels else "None")

@bot.message_handler(commands=["add_refresh"])
def add_refresh_link(msg):
    if str(msg.from_user.id) != OWNER_ID: return
    args = msg.text.split(" ", 1)
    if len(args) < 2: return
    with get_db_connection() as conn:
        conn.cursor().execute("INSERT INTO refresh_links (url) VALUES (%s) ON CONFLICT DO NOTHING", (args[1].strip(),))
        conn.commit()
    bot.reply_to(msg, "✅ Link added")

@bot.message_handler(commands=["get_access"])
def handle_get_access(msg):
    webapp_url = get_any_refresh_link()
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔓 Unlock Now (Auto-ID)", web_app=WebAppInfo(url=webapp_url)))
    bot.send_message(msg.chat.id, "🔐 Click below to unlock access.", reply_markup=markup)

# ==========================================
# 6. FLASK SERVER (REFRESH LOGIC)
# ==========================================

@app.route("/refresh", methods=["POST"])
def refresh_token():
    data = request.get_json()
    user_id = data.get("user_id")
    full_token = data.get("token")
    
    if not user_id:
        return jsonify({"status": "error", "message": "Missing user_id"}), 400

    token = full_token.replace("token_", "") if full_token else "web_verification"
    expiry = datetime.now() + timedelta(hours=24)
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            # Reset usage to 0 for the user
            c.execute("""
                INSERT INTO user_access (user_id, token, access_expiry, usage_count)
                VALUES (%s, %s, %s, 0)
                ON CONFLICT (user_id) 
                DO UPDATE SET usage_count = 0, access_expiry = %s, token = %s
            """, (user_id, token, expiry, expiry, token))
            conn.commit()
            
        bot.send_message(int(user_id), "✅ **Verification Successful!**\n\nYou have unlocked 4 new file downloads for the next 24 hours.", parse_mode="Markdown")
        return jsonify({"status": "success", "message": "Limit reset to 0"}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def run_bot():
    bot.infinity_polling()

def run_flask():
    print("🌍 Starting Production Server with Waitress on port 5050...")
    serve(app, host="0.0.0.0", port=5050)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    run_flask()
