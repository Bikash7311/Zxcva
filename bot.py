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
REQUESTED_CHANNEL_ID = os.getenv("REQUESTED_CHANNEL_ID", "")  # Optional: e.g. -1001234567890

JOIN_GROUP_URL = "https://t.me/chatgctest"
JOIN_GROUP_REF = os.getenv("JOIN_GROUP_REF", "@chatgctest")

PARTNER_BOT_URL = "https://t.me/Nobita_banbot"

REFERRALS_REQUIRED_FOR_PREMIUM = 10
PREMIUM_DURATION_SECONDS = 30 * 24 * 60 * 60  # 1 Month (30 days)
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))

# ---------------- STYLED TYPOGRAPHY ----------------
def bold_mono(text: str) -> str:
    return f"<b><code>{text}</code></b>"


def make_banner(title: str, subtitle: str) -> str:
    return (
        f"⚡ <b>{title}</b> ⚡\n"
        f"<i>✦ {subtitle} ✦</i>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━</code>"
    )


# ---------------- STORAGE HELPERS ----------------
def load_db() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return {
            "users": {},
            "join_requests": [],
            "tg_ban_cases": [],
            "support_tickets": [],
        }
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("users", {})
            data.setdefault("join_requests", [])
            data.setdefault("tg_ban_cases", [])
            data.setdefault("support_tickets", [])
            return data
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read database file; initializing fresh state.")
        return {
            "users": {},
            "join_requests": [],
            "tg_ban_cases": [],
            "support_tickets": [],
        }


def save_db(data: dict[str, Any]) -> None:
    tmp_path = DATA_FILE.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(DATA_FILE)


def get_user(db: dict[str, Any], user_id: int, full_name: str = "User", username: str = "") -> dict[str, Any]:
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
            "awaiting_mode": None,  # "tg_ban" | "support" | None
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
        return f"👑 <b>ACTIVE PREMIUM</b> (<code>{remaining_days}d</code> left)"
    return "🔹 <b>STANDARD ACCESS</b> (<code>Unlock 1M Free</code>)"


# ---------------- KEEP-ALIVE WEB SERVER FOR RENDER ----------------
flask_app = Flask(__name__)


@flask_app.route("/")
def health_check():
    return f"{BOT_NAME} ({BOT_USERNAME}) is running.", 200


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


async def check_all_requirements(bot, user_id: int, db: dict[str, Any]) -> dict[str, bool]:
    channel_ok = await is_member_of(bot, MANDATORY_CHANNEL_REF, user_id)
    group_ok = await is_member_of(bot, JOIN_GROUP_REF, user_id)

    requested_ok = str(user_id) in {str(x) for x in db.get("join_requests", [])}
    if not requested_ok and REQUESTED_CHANNEL_ID:
        requested_ok = await is_member_of(bot, REQUESTED_CHANNEL_ID, user_id)

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
                InlineKeyboardButton("🔐 Requested Channel", url=REQUESTED_CHANNEL_URL),
            ],
            [
                InlineKeyboardButton("👥 Join Support Group", url=JOIN_GROUP_URL),
                InlineKeyboardButton("🤖 Start Partner Bot", url=PARTNER_BOT_URL),
            ],
            [
                InlineKeyboardButton("✅ Verify Membership & Unlock", callback_data="verify_join"),
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
        logger.warning("send_video failed, falling back to send_message: %s", exc)
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
    logger.info("Recorded join request from user %s in chat %s", req.from_user.id, req.chat.id)


# ---------------- COMMANDS & CALLBACKS ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    db = load_db()
    user_rec = get_user(db, user.id, user.full_name, user.username or "")

    # Process referral payload: /start ref_<user_id>
    if context.args and user_rec.get("referred_by") is None:
        arg = context.args[0].strip()
        if arg.startswith("ref_"):
            referrer_id_str = arg.replace("ref_", "", 1).strip()
            if referrer_id_str.isdigit() and int(referrer_id_str) != user.id:
                if referrer_id_str in db["users"]:
                    user_rec["referred_by"] = int(referrer_id_str)
                    ref_user = db["users"][referrer_id_str]
                    ref_user["referrals"] = int(ref_user.get("referrals", 0)) + 1

                    # Auto-grant 1 month premium every 10 referrals
                    if ref_user["referrals"] >= REFERRALS_REQUIRED_FOR_PREMIUM:
                        now = int(time.time())
                        current_exp = max(now, int(ref_user.get("premium_until", 0)))
                        ref_user["premium_until"] = current_exp + PREMIUM_DURATION_SECONDS

                    try:
                        await context.bot.send_message(
                            chat_id=int(referrer_id_str),
                            text=(
                                f"🎉 <b>NEW REFERRAL UNLOCKED!</b>\n"
                                f"<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
                                f"👤 User: <b>{user.full_name}</b>\n"
                                f"📈 Total Referrals: <code>{ref_user['referrals']}</code>\n"
                                f"💎 Status: {format_premium_status(ref_user)}"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramError:
                        pass

    save_db(db)

    status = await check_all_requirements(context.bot, user.id, db)

    if not status["all_ok"]:
        gate_caption = (
            f"{make_banner(BOT_NAME, 'EXCLUSIVE ACCESS GATEWAY')}\n"
            f"🤖 Bot: {bold_mono(BOT_USERNAME)}\n"
            f"👑 Owner: <b>{OWNER_USERNAME}</b> | ID: <code>{OWNER_ID}</code>\n\n"
            f"<b>Required Access Steps:</b>\n"
            f"{'✅' if status['channel'] else '❌'} Mandatory Channel\n"
            f"{'✅' if status['requested'] else '⏳'} Requested Channel (Request join)\n"
            f"{'✅' if status['group'] else '❌'} Join Group\n"
            f"🔹 Partner Bot: <a href=\"{PARTNER_BOT_URL}\">Start Nobita BanBot</a>\n\n"
            f"<i>Pehle teeno requirements complete karein, phir</i> <b>Verify Membership</b> <i>dabayein.</i>"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=gate_caption,
            reply_markup=build_gate_keyboard(),
        )
        return

    welcome_caption = (
        f"{make_banner(BOT_NAME, 'NEXT-GEN MODERATION & REFERRAL SUITE')}\n"
        f"👋 Welcome, <b>{user.full_name}</b>!\n"
        f"🤖 Handle: {bold_mono(BOT_USERNAME)}\n"
        f"👑 Owner: <b>{OWNER_USERNAME}</b> (<code>{OWNER_ID}</code>)\n"
        f"{format_premium_status(user_rec)}\n\n"
        f"<b>Core Modules:</b>\n"
        f"⚔️ <b>TG BAN</b> — Submit & track moderation/ban action tickets\n"
        f"💎 <b>Referral & Premium</b> — <code>10 Referrals = 1 Month Free Premium</code>\n"
        f"🎧 <b>Support</b> — Direct ticket & owner assistance\n"
        f"🤖 <b>Partner Bot</b> — <a href=\"{PARTNER_BOT_URL}\">Nobita BanBot</a>"
    )
    await send_stylish_video_message(
        context.bot,
        chat_id=chat_id,
        caption=welcome_caption,
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
            missing_lines = []
            if not status["channel"]:
                missing_lines.append(f"• Join Mandatory Channel: {MANDATORY_CHANNEL_URL}")
            if not status["requested"]:
                missing_lines.append(f"• Send Join Request to Channel: {REQUESTED_CHANNEL_URL}")
            if not status["group"]:
                missing_lines.append(f"• Join Group: {JOIN_GROUP_URL}")

            await query.message.reply_text(
                "⚠️ <b>Verification Incomplete!</b>\n\n" + "\n".join(missing_lines),
                parse_mode=ParseMode.HTML,
                reply_markup=build_gate_keyboard(),
            )
            return

        welcome_text = (
            f"{make_banner(BOT_NAME, 'ACCESS VERIFIED & UNLOCKED')}\n"
            f"✅ All requirements verified for <b>{user.full_name}</b>!\n"
            f"{format_premium_status(user_rec)}\n\n"
            f"Neeche diye gaye modules mein se koi bhi option chunein:"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=welcome_text,
            reply_markup=build_main_menu_keyboard(),
        )
        return

    if data == "menu_tg_ban":
        user_rec["awaiting_mode"] = "tg_ban"
        save_db(db)
        msg = (
            f"{make_banner('TG BAN MODULE', 'MODERATION & REPORT CASE SUBMISSION')}\n"
            f"{format_premium_status(user_rec)}\n\n"
            f"Kripya target username/ID aur reason ek message mein bhejein:\n"
            f"<code>@target_username | Reason for report/action</code>\n\n"
            f"<i>Example:</i> <code>@spammer_id | Repeated scam links in groups</code>"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=msg,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")]]
            ),
        )
        return

    if data == "menu_referral":
        user_rec["awaiting_mode"] = None
        save_db(db)
        ref_count = int(user_rec.get("referrals", 0))
        left_for_prem = max(0, REFERRALS_REQUIRED_FOR_PREMIUM - ref_count)
        bot_clean = BOT_USERNAME.lstrip("@")
        invite_link = f"https://t.me/{bot_clean}?start=ref_{user.id}"

        msg = (
            f"{make_banner('REFERRAL & PREMIUM VAULT', '10 REFERRALS = 1 MONTH FREE PREMIUM')}\n"
            f"🔗 Your Invite Link:\n<code>{invite_link}</code>\n\n"
            f"📈 Current Referrals: <code>{ref_count}</code>\n"
            f"🎯 Remaining for 1 Month Free: <code>{left_for_prem}</code>\n"
            f"👑 Premium Status: {format_premium_status(user_rec)}\n\n"
            f"<i>Direct premium ke liye owner</i> <b>{OWNER_USERNAME}</b> <i>se contact karein.</i>"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=msg,
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
        msg = (
            f"{make_banner('PREMIUM SUPPORT DESK', 'DIRECT ASSISTANCE & TICKETS')}\n"
            f"👑 Owner: <b>{OWNER_USERNAME}</b> | ID: <code>{OWNER_ID}</code>\n"
            f"🤖 Partner Bot: <a href=\"{PARTNER_BOT_URL}\">Nobita BanBot</a>\n\n"
            f"Apna support message yahan type karein—wo owner tak forward kar diya jayega, "
            f"ya direct <b>{OWNER_USERNAME}</b> par message karein."
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=msg,
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
        msg = (
            f"{make_banner('USER PROFILE & STATS', 'LIVE ACCOUNT TELEMETRY')}\n"
            f"👤 Name: <b>{user.full_name}</b>\n"
            f"🆔 User ID: <code>{user.id}</code>\n"
            f"📈 Referrals: <code>{user_rec.get('referrals', 0)}</code> / <code>{REFERRALS_REQUIRED_FOR_PREMIUM}</code>\n"
            f"💎 Status: {format_premium_status(user_rec)}"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=msg,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")]]
            ),
        )
        return

    if data == "back_home":
        user_rec["awaiting_mode"] = None
        save_db(db)
        home_msg = (
            f"{make_banner(BOT_NAME, 'MAIN CONTROL PANEL')}\n"
            f"🤖 {bold_mono(BOT_USERNAME)} | 👑 <b>{OWNER_USERNAME}</b>\n"
            f"{format_premium_status(user_rec)}"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=home_msg,
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
            f"⚔️ <b>TG BAN TICKET LOGGED</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
            f"🎫 Case ID: <code>{case_id}</code>\n"
            f"📝 Details: <code>{text}</code>\n"
            f"📌 Status: <b>Queued for Review</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_menu_keyboard(),
        )

        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"🚨 <b>NEW TG BAN CASE</b> ({case_id})\n"
                    f"From: <b>{user.full_name}</b> (<code>{user.id}</code>)\n"
                    f"Details: <code>{text}</code>"
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
            f"🎧 <b>SUPPORT TICKET SENT</b>\n"
            f"🎫 Ticket: <code>{ticket_id}</code>\n"
            f"👑 Owner <b>{OWNER_USERNAME}</b> ko aapka message bhej diya gaya hai.",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_menu_keyboard(),
        )

        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"📩 <b>SUPPORT MESSAGE</b> ({ticket_id})\n"
                    f"User: <b>{user.full_name}</b> (<code>{user.id}</code>)\n"
                    f"Message: {text}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    await update.message.reply_text(
        f"⚡ <b>{BOT_NAME}</b>\nMenu kholne ke liye /start dabayein ya neeche buttons use karein.",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_menu_keyboard(),
    )


async def cmd_grant_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command: /grant <user_id> [days]"""
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /grant <user_id> [days=30]")
        return

    target_id = context.args[0].strip()
    days = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 30

    db = load_db()
    if target_id not in db["users"]:
        db["users"][target_id] = {
            "user_id": int(target_id) if target_id.isdigit() else 0,
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
        f"✅ Granted <b>{days} days</b> premium to <code>{target_id}</code>.",
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                f"👑 <b>PREMIUM ACTIVATED!</b>\n"
                f"Aapko <b>{days} din</b> ka Premium access mil gaya hai."
            ),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command: /stats"""
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    db = load_db()
    total_users = len(db["users"])
    active_prem = sum(1 for u in db["users"].values() if has_active_premium(u))
    total_cases = len(db["tg_ban_cases"])
    total_tickets = len(db["support_tickets"])

    await update.message.reply_text(
        f"📊 <b>{BOT_NAME} STATS</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"👥 Total Users: <code>{total_users}</code>\n"
        f"👑 Active Premium: <code>{active_prem}</code>\n"
        f"⚔️ TG Ban Cases: <code>{total_cases}</code>\n"
        f"🎧 Support Tickets: <code>{total_tickets}</code>",
        parse_mode=ParseMode.HTML,
    )


def main() -> None:
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("grant", cmd_grant_premium))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(ChatJoinRequestHandler(track_join_request))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    logger.info("Starting %s (%s)...", BOT_NAME, BOT_USERNAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
