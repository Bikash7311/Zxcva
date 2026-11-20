import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask
from telegram import (
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("TGBanBotXPremium")

# ---------------- CONFIGURATION ----------------
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "9246030449:AAGEvtVyfUwWPhQcGr7t6tRoi-euwbEs0e8",
)
BOT_NAME = "TG BAN BOT X PREMIUM"
BOT_USERNAME = "@Tgbanpremium_bot"

OWNER_USERNAME = "@Znonsence"
OWNER_ID = int(os.getenv("OWNER_ID", "6132146801"))

VIDEO_URL = os.getenv(
    "VIDEO_URL",
    "https://videotourl.com/videos/1795175824226-44c0555f-6901-45f7-893b-2f65d04b6dc7.mp4",
)

MANDATORY_CHANNEL_URL = "https://t.me/nobitabanxunban"
MANDATORY_CHANNEL_REF = os.getenv("MANDATORY_CHANNEL_REF", "@nobitabanxunban")

REQUESTED_CHANNEL_URL = "https://t.me/+972zYAr5L1BjMmM1"
REQUESTED_CHANNEL_ID = os.getenv("REQUESTED_CHANNEL_ID", "")

JOIN_GROUP_URL = "https://t.me/chatgctest"
JOIN_GROUP_REF = os.getenv("JOIN_GROUP_REF", "@chatgctest")

PARTNER_BOT_URL = "https://t.me/Nobita_banbot"

REFERRALS_REQUIRED_FOR_PREMIUM = 10
PREMIUM_DURATION_SECONDS = 30 * 24 * 60 * 60  # 30 days
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))
DB_LOCK = threading.Lock()


# ---------------- STYLED TYPOGRAPHY & QUOTES ----------------
def bold_mono(text: str) -> str:
    return f"<b><code>{text}</code></b>"


def make_header(title: str, subtitle: str) -> str:
    return (
        f"⚡ <b>{title}</b> ⚡\n"
        f"<i>✦ {subtitle} ✦</i>\n\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
    )


def make_quote(text: str) -> str:
    return f"<blockquote>“{text}”</blockquote>\n"


def is_owner(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)


# ---------------- STORAGE HELPERS ----------------
def load_db() -> dict[str, Any]:
    default_data: dict[str, Any] = {
        "users": {},
        "join_requests": [],
        "tg_ban_cases": [],
        "support_tickets": [],
    }
    with DB_LOCK:
        if not DATA_FILE.exists():
            return default_data
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in default_data.items():
                    data.setdefault(k, v)
                return data
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to read database file; using fresh state.")
            return default_data


def save_db(data: dict[str, Any]) -> None:
    with DB_LOCK:
        tmp_path = DATA_FILE.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(DATA_FILE)


def get_user(
    db: dict[str, Any],
    user_id: int,
    full_name: str = "User",
    username: str = "",
) -> dict[str, Any]:
    uid = str(user_id)
    now = int(time.time())
    if uid not in db["users"]:
        db["users"][uid] = {
            "user_id": user_id,
            "full_name": full_name,
            "username": username,
            "referrals": 0,
            "referred_by": None,
            "premium_until": 0,
            "joined_at": now,
            "awaiting_mode": None,
        }
    else:
        db["users"][uid]["full_name"] = full_name or db["users"][uid].get("full_name", "User")
        db["users"][uid]["username"] = username
    return db["users"][uid]


def has_active_premium(user_rec: dict[str, Any]) -> bool:
    return int(user_rec.get("premium_until", 0)) > int(time.time())


def format_premium_status(user_rec: dict[str, Any]) -> str:
    if has_active_premium(user_rec):
        remaining_days = max(1, (int(user_rec["premium_until"]) - int(time.time())) // 86400)
        return f"👑 <b>ACTIVE PREMIUM</b>  •  <code>{remaining_days} Days Left</code>"
    return "🔹 <b>STANDARD ACCESS</b>  •  <code>10 Refs = 1 Month Free</code>"


# ---------------- KEEP-ALIVE WEB SERVER FOR RENDER ----------------
flask_app = Flask(__name__)


@flask_app.route("/")
def health_check():
    return f"{BOT_NAME} ({BOT_USERNAME}) is live.", 200


def run_flask() -> None:
    port = int(os.getenv("PORT", "10000"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ---------------- ACCESS & MEMBERSHIP CHECKS ----------------
async def is_member_of(bot, chat_ref: str, user_id: int) -> bool:
    if not chat_ref:
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_ref, user_id=user_id)
        return member.status in {
            ChatMember.OWNER,
            ChatMember.ADMINISTRATOR,
            ChatMember.MEMBER,
        }
    except TelegramError as exc:
        logger.warning("Membership check failed for %s (%s): %s", chat_ref, user_id, exc)
        return False


async def has_requested_or_joined(bot, user_id: int, db: dict[str, Any]) -> bool:
    """Returns True as soon as user sends a join request (or is already a member)."""
    if str(user_id) in {str(x) for x in db.get("join_requests", [])}:
        return True
    if REQUESTED_CHANNEL_ID:
        return await is_member_of(bot, REQUESTED_CHANNEL_ID, user_id)
    return False


async def check_all_requirements(bot, user_id: int, db: dict[str, Any]) -> dict[str, bool]:
    channel_ok = await is_member_of(bot, MANDATORY_CHANNEL_REF, user_id)
    group_ok = await is_member_of(bot, JOIN_GROUP_REF, user_id)
    requested_ok = await has_requested_or_joined(bot, user_id, db)

    return {
        "channel": channel_ok,
        "requested": requested_ok,
        "group": group_ok,
        "all_ok": channel_ok and requested_ok and group_ok,
    }


def build_gate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📢 Mandatory Channel", url=MANDATORY_CHANNEL_URL),
                InlineKeyboardButton("🔐 Request Channel", url=REQUESTED_CHANNEL_URL),
            ],
            [
                InlineKeyboardButton("👥 Join Group", url=JOIN_GROUP_URL),
                InlineKeyboardButton("🤖 Start Partner Bot", url=PARTNER_BOT_URL),
            ],
            [
                InlineKeyboardButton("✅ Verify & Unlock Access", callback_data="verify_join"),
            ],
        ]
    )


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚔️ TG BAN", callback_data="menu_tg_ban"),
                InlineKeyboardButton("💎 Referral & Premium", callback_data="menu_referral"),
            ],
            [
                InlineKeyboardButton("🎧 Support", callback_data="menu_support"),
                InlineKeyboardButton("👑 Owner Contact", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}"),
            ],
            [
                InlineKeyboardButton("📊 My Status", callback_data="menu_status"),
                InlineKeyboardButton("🤖 Partner Bot", url=PARTNER_BOT_URL),
            ],
        ]
    )


async def send_stylish_video_message(
    bot,
    chat_id: int,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await bot.send_video(
            chat_id=chat_id,
            video=VIDEO_URL,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            supports_streaming=True,
        )
    except TelegramError as exc:
        logger.warning("send_video fallback to text message: %s", exc)
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=False,
        )


# ---------------- JOIN REQUEST TRACKER ----------------
async def track_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    req = update.chat_join_request
    if not req:
        return

    db = load_db()
    uid_str = str(req.from_user.id)
    if uid_str not in db["join_requests"]:
        db["join_requests"].append(uid_str)
        save_db(db)

    logger.info("Join request verified for user %s in chat %s", req.from_user.id, req.chat.id)
    try:
        await context.bot.send_message(
            chat_id=req.from_user.id,
            text=(
                f"{make_header(BOT_NAME, 'JOIN REQUEST RECORDED')}"
                f"{make_quote('Aapki channel join request verify ho chuki hai. Ab Verify button dabayein.')}"
            ),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


# ---------------- COMMANDS & CALLBACKS ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    db = load_db()
    user_rec = get_user(db, user.id, user.full_name, user.username or "")
    user_rec["awaiting_mode"] = None

    # Referral tracking: /start ref_<user_id>
    if context.args and user_rec.get("referred_by") is None:
        arg = context.args[0].strip()
        if arg.startswith("ref_"):
            referrer_id_str = arg.replace("ref_", "", 1).strip()
            if referrer_id_str.isdigit() and int(referrer_id_str) != user.id:
                if referrer_id_str in db["users"]:
                    user_rec["referred_by"] = int(referrer_id_str)
                    ref_user = db["users"][referrer_id_str]
                    ref_user["referrals"] = int(ref_user.get("referrals", 0)) + 1

                    if ref_user["referrals"] % REFERRALS_REQUIRED_FOR_PREMIUM == 0:
                        now = int(time.time())
                        current_exp = max(now, int(ref_user.get("premium_until", 0)))
                        ref_user["premium_until"] = current_exp + PREMIUM_DURATION_SECONDS

                    try:
                        await context.bot.send_message(
                            chat_id=int(referrer_id_str),
                            text=(
                                f"{make_header('NEW REFERRAL ADDED', 'REWARD PROGRESS UPDATED')}"
                                f"{make_quote('Ek naya member aapke invite link se jud gaya hai.')}"
                                f"👤 <b>Member:</b> {user.full_name}\n\n"
                                f"📈 <b>Total Referrals:</b> <code>{ref_user['referrals']}</code>\n\n"
                                f"💎 <b>Plan:</b> {format_premium_status(ref_user)}"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramError:
                        pass

    save_db(db)
    status = await check_all_requirements(context.bot, user.id, db)

    if not status["all_ok"]:
        gate_caption = (
            f"{make_header(BOT_NAME, 'ACCESS VERIFICATION GATEWAY')}"
            f"{make_quote('Precision, speed, aur structured control ke saath next-gen moderation suite.')}"
            f"🤖 <b>Bot:</b> {bold_mono(BOT_USERNAME)}\n\n"
            f"👑 <b>Owner:</b> <b>{OWNER_USERNAME}</b>  |  <code>{OWNER_ID}</code>\n\n"
            f"<b>Required Access Steps:</b>\n\n"
            f"{'✅' if status['channel'] else '❌'} <b>Mandatory Channel</b> — Join channel\n\n"
            f"{'✅' if status['requested'] else '⏳'} <b>Requested Channel</b> — Sirf join request bhejein\n\n"
            f"{'✅' if status['group'] else '❌'} <b>Join Group</b> — Join community group\n\n"
            f"🤖 <b>Partner Bot:</b> <a href=\"{PARTNER_BOT_URL}\">Nobita BanBot</a>\n\n"
            f"<i>Sabhi steps complete karke</i> <b>Verify & Unlock Access</b> <i>dabayein.</i>"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=gate_caption,
            reply_markup=build_gate_keyboard(),
        )
        return

    welcome_caption = (
        f"{make_header(BOT_NAME, 'ELITE MODERATION & REFERRAL SUITE')}"
        f"{make_quote('Built for high-impact workflows, 10-referral free premium, aur direct owner support.')}"
        f"👋 <b>Welcome,</b> <b>{user.full_name}</b>\n\n"
        f"🤖 <b>Handle:</b> {bold_mono(BOT_USERNAME)}\n\n"
        f"👑 <b>Owner:</b> <b>{OWNER_USERNAME}</b>  |  <code>{OWNER_ID}</code>\n\n"
        f"{format_premium_status(user_rec)}\n\n"
        f"<b>Core Modules:</b>\n\n"
        f"⚔️ <b>TG BAN</b> — Submit & track moderation cases\n\n"
        f"💎 <b>Referral & Premium</b> — <code>10 Referrals = 1 Month Free</code>\n\n"
        f"🎧 <b>Support</b> — Direct ticket & owner assistance\n\n"
        f"🤖 <b>Partner Bot</b> — <a href=\"{PARTNER_BOT_URL}\">Start Nobita BanBot</a>"
    )
    await send_stylish_video_message(
        context.bot,
        chat_id=chat_id,
        caption=welcome_caption,
        reply_markup=build_main_menu_keyboard(),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    db = load_db()
    user_rec = get_user(
        db,
        update.effective_user.id,
        update.effective_user.full_name,
        update.effective_user.username or "",
    )
    user_rec["awaiting_mode"] = None
    save_db(db)
    await update.message.reply_text(
        f"{make_quote('Current action cancel kar diya gaya hai. Main menu neeche diya gaya hai.')}",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu_keyboard(),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()

    user = query.from_user
    chat_id = query.message.chat_id if query.message else user.id
    db = load_db()
    user_rec = get_user(db, user.id, user.full_name, user.username or "")
    data = query.data or ""

    if data == "verify_join":
        status = await check_all_requirements(context.bot, user.id, db)
        if not status["all_ok"]:
            missing = []
            if not status["channel"]:
                missing.append(f"• <b>Mandatory Channel:</b> {MANDATORY_CHANNEL_URL}")
            if not status["requested"]:
                missing.append(f"• <b>Requested Channel (Sirf Request Bhejein):</b> {REQUESTED_CHANNEL_URL}")
            if not status["group"]:
                missing.append(f"• <b>Join Group:</b> {JOIN_GROUP_URL}")

            await query.message.reply_text(
                f"{make_header('VERIFICATION PENDING', 'COMPLETE REMAINING STEPS')}"
                f"{make_quote('Requested channel mein sirf join request bhejne par bhi verify ho jayega.')}"
                + "\n\n".join(missing),
                parse_mode=ParseMode.HTML,
                reply_markup=build_gate_keyboard(),
            )
            return

        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header(BOT_NAME, 'ACCESS UNLOCKED & VERIFIED')}"
                f"{make_quote('Aapki verification safaltapoorvak poori ho gayi hai.')}"
                f"✅ <b>Verified User:</b> <b>{user.full_name}</b>\n\n"
                f"{format_premium_status(user_rec)}"
            ),
            reply_markup=build_main_menu_keyboard(),
        )
        return

    if data == "menu_tg_ban":
        user_rec["awaiting_mode"] = "tg_ban"
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('TG BAN MODULE', 'MODERATION & REPORT CASE')}"
                f"{make_quote('Clear details aur reason ke saath case submit karein.')}"
                f"{format_premium_status(user_rec)}\n\n"
                f"<b>Format:</b>\n"
                f"<code>@target_username | Reason</code>\n\n"
                f"<i>Cancel karne ke liye /cancel bhejein.</i>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")]]
            ),
        )
        return

    if data == "menu_referral":
        user_rec["awaiting_mode"] = None
        save_db(db)
        refs = int(user_rec.get("referrals", 0))
        rem = REFERRALS_REQUIRED_FOR_PREMIUM - (refs % REFERRALS_REQUIRED_FOR_PREMIUM)
        if refs > 0 and refs % REFERRALS_REQUIRED_FOR_PREMIUM == 0:
            rem = REFERRALS_REQUIRED_FOR_PREMIUM
        bot_clean = BOT_USERNAME.lstrip("@")
        ref_link = f"https://t.me/{bot_clean}?start=ref_{user.id}"

        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('REFERRAL & PREMIUM VAULT', '10 REFERRALS = 1 MONTH FREE')}"
                f"{make_quote('10 referrals complete karke 1 month free premium payein ya direct owner se contact karein.')}"
                f"🔗 <b>Your Invite Link:</b>\n<code>{ref_link}</code>\n\n"
                f"📈 <b>Total Referrals:</b> <code>{refs}</code>\n\n"
                f"🎯 <b>Remaining For Next Reward:</b> <code>{rem}</code>\n\n"
                f"💎 <b>Status:</b> {format_premium_status(user_rec)}\n\n"
                f"👑 <b>Direct Owner:</b> <b>{OWNER_USERNAME}</b>  |  <code>{OWNER_ID}</code>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("👑 Contact Owner", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")],
                ]
            ),
        )
        return

    if data == "menu_support":
        user_rec["awaiting_mode"] = "support"
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('SUPPORT DESK', 'DIRECT OWNER & TICKET HELP')}"
                f"{make_quote('Kisi bhi query ya premium access ke liye apna message bhejein ya owner se sampark karein.')}"
                f"👑 <b>Owner:</b> <b>{OWNER_USERNAME}</b>  |  <code>{OWNER_ID}</code>\n\n"
                f"🤖 <b>Partner Bot:</b> <a href=\"{PARTNER_BOT_URL}\">Nobita BanBot</a>\n\n"
                f"<i>Apna support message yahan type karein.</i>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("💬 Direct Owner Chat", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}")],
                    [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")],
                ]
            ),
        )
        return

    if data == "menu_status":
        user_rec["awaiting_mode"] = None
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('ACCOUNT TELEMETRY', 'LIVE MEMBER STATUS')}"
                f"{make_quote('Aapke account, referrals, aur premium plan ki live summary.')}"
                f"👤 <b>Name:</b> <b>{user.full_name}</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n\n"
                f"📈 <b>Referrals:</b> <code>{user_rec.get('referrals', 0)}</code>\n\n"
                f"💎 <b>Plan:</b> {format_premium_status(user_rec)}"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")]]
            ),
        )
        return

    if data == "back_home":
        user_rec["awaiting_mode"] = None
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header(BOT_NAME, 'MAIN CONTROL PANEL')}"
                f"{make_quote('Select any module below to continue.')}"
                f"🤖 <b>Bot:</b> {bold_mono(BOT_USERNAME)}\n\n"
                f"👑 <b>Owner:</b> <b>{OWNER_USERNAME}</b>\n\n"
                f"{format_premium_status(user_rec)}"
            ),
            reply_markup=build_main_menu_keyboard(),
        )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()
    db = load_db()
    user_rec = get_user(db, user.id, user.full_name, user.username or "")
    mode = user_rec.get("awaiting_mode")

    if mode == "tg_ban":
        case_id = f"CASE-{len(db['tg_ban_cases']) + 1001}"
        db["tg_ban_cases"].append(
            {
                "case_id": case_id,
                "submitted_by": user.id,
                "payload": text,
                "timestamp": int(time.time()),
            }
        )
        user_rec["awaiting_mode"] = None
        save_db(db)

        await update.message.reply_text(
            f"{make_header('TG BAN CASE LOGGED', 'MODERATION QUEUE')}"
            f"{make_quote('Aapka case record kar liya gaya hai aur owner ko bhej diya gaya hai.')}"
            f"🎫 <b>Case ID:</b> <code>{case_id}</code>\n\n"
            f"📝 <b>Details:</b> <code>{text}</code>\n\n"
            f"📌 <b>Status:</b> <b>Submitted</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_menu_keyboard(),
        )
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"{make_header('NEW TG BAN CASE', case_id)}"
                    f"👤 <b>From:</b> <b>{user.full_name}</b> (<code>{user.id}</code>)\n\n"
                    f"📝 <b>Details:</b> <code>{text}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    if mode == "support":
        ticket_id = f"SUP-{len(db['support_tickets']) + 101}"
        db["support_tickets"].append(
            {
                "ticket_id": ticket_id,
                "user_id": user.id,
                "message": text,
                "timestamp": int(time.time()),
            }
        )
        user_rec["awaiting_mode"] = None
        save_db(db)

        await update.message.reply_text(
            f"{make_header('SUPPORT TICKET SENT', 'OWNER NOTIFIED')}"
            f"{make_quote('Aapka message owner tak pahuncha diya gaya hai.')}"
            f"🎫 <b>Ticket ID:</b> <code>{ticket_id}</code>\n\n"
            f"👑 <b>Owner:</b> <b>{OWNER_USERNAME}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_menu_keyboard(),
        )
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"{make_header('SUPPORT MESSAGE', ticket_id)}"
                    f"👤 <b>From:</b> <b>{user.full_name}</b> (<code>{user.id}</code>)\n\n"
                    f"{make_quote(text)}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    await update.message.reply_text(
        f"{make_header(BOT_NAME, 'QUICK NAVIGATION')}"
        f"{make_quote('Main menu kholne ke liye /start bhejein ya neeche buttons ka use karein.')}",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu_keyboard(),
    )


# ---------------- OWNER-ONLY COMMANDS ----------------
async def cmd_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner only: /addpremium <user_id> [days=30]"""
    if not is_owner(update) or not update.message:
        return
    if not context.args or not context.args[0].strip().isdigit():
        await update.message.reply_text(
            "Usage: <code>/addpremium &lt;user_id&gt; [days=30]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_id = context.args[0].strip()
    days = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 30
    if days <= 0:
        await update.message.reply_text("Days must be greater than 0.")
        return

    db = load_db()
    if target_id not in db["users"]:
        db["users"][target_id] = {
            "user_id": int(target_id),
            "full_name": "Member",
            "username": "",
            "referrals": 0,
            "referred_by": None,
            "premium_until": 0,
            "joined_at": int(time.time()),
            "awaiting_mode": None,
        }

    now = int(time.time())
    current_exp = max(now, int(db["users"][target_id].get("premium_until", 0)))
    db["users"][target_id]["premium_until"] = current_exp + (days * 86400)
    save_db(db)

    await update.message.reply_text(
        f"{make_header('PREMIUM GRANTED', 'OWNER ACTION')}"
        f"🆔 <b>User ID:</b> <code>{target_id}</code>\n\n"
        f"⏳ <b>Duration:</b> <b>{days} Days</b>",
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                f"{make_header('PREMIUM ACTIVATED', 'VIP ACCESS UNLOCKED')}"
                f"{make_quote(f'Owner {OWNER_USERNAME} ne aapko {days} din ka Premium access diya hai.')}"
            ),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


async def cmd_remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner only: /removepremium <user_id>"""
    if not is_owner(update) or not update.message:
        return
    if not context.args or not context.args[0].strip().isdigit():
        await update.message.reply_text(
            "Usage: <code>/removepremium &lt;user_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_id = context.args[0].strip()
    db = load_db()

    if target_id not in db["users"]:
        await update.message.reply_text(
            f"⚠️ User <code>{target_id}</code> database mein nahi mila.",
            parse_mode=ParseMode.HTML,
        )
        return

    db["users"][target_id]["premium_until"] = 0
    save_db(db)

    await update.message.reply_text(
        f"{make_header('PREMIUM REMOVED', 'OWNER ACTION')}"
        f"🆔 <b>User ID:</b> <code>{target_id}</code> ka premium access hata diya gaya hai.",
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                f"{make_header('PREMIUM UPDATED', 'STANDARD PLAN')}"
                f"{make_quote(f'Aapka premium access remove kar diya gaya hai. Contact: {OWNER_USERNAME}')}"
            ),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner only: /broadcast <message>"""
    if not is_owner(update) or not update.message:
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/broadcast &lt;your message&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    msg_text = " ".join(context.args).strip()
    db = load_db()
    sent, failed = 0, 0

    for uid_str in list(db["users"].keys()):
        if not uid_str.isdigit():
            continue
        try:
            await context.bot.send_message(
                chat_id=int(uid_str),
                text=(
                    f"{make_header(BOT_NAME, 'OFFICIAL BROADCAST')}"
                    f"{make_quote(msg_text)}"
                ),
                parse_mode=ParseMode.HTML,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            failed += 1

    await update.message.reply_text(
        f"{make_header('BROADCAST COMPLETE', 'DELIVERY REPORT')}"
        f"✅ <b>Delivered:</b> <code>{sent}</code>\n\n"
        f"❌ <b>Failed:</b> <code>{failed}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner only: /stats"""
    if not is_owner(update) or not update.message:
        return
    db = load_db()
    total_users = len(db["users"])
    active_prem = sum(1 for u in db["users"].values() if has_active_premium(u))
    total_cases = len(db["tg_ban_cases"])
    total_tickets = len(db["support_tickets"])

    await update.message.reply_text(
        f"{make_header(BOT_NAME, 'LIVE SYSTEM STATS')}"
        f"👥 <b>Total Users:</b> <code>{total_users}</code>\n\n"
        f"👑 <b>Active Premium:</b> <code>{active_prem}</code>\n\n"
        f"⚔️ <b>TG Ban Cases:</b> <code>{total_cases}</code>\n\n"
        f"🎧 <b>Support Tickets:</b> <code>{total_tickets}</code>",
        parse_mode=ParseMode.HTML,
    )


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("addpremium", cmd_add_premium))
    app.add_handler(CommandHandler("grant", cmd_add_premium))
    app.add_handler(CommandHandler("removepremium", cmd_remove_premium))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(ChatJoinRequestHandler(track_join_request))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    logger.info("Starting %s (%s)...", BOT_NAME, BOT_USERNAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
