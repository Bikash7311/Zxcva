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

JOIN_GROUP_URL = "https://t.me/chatgctest"
JOIN_GROUP_REF = os.getenv("JOIN_GROUP_REF", "@chatgctest")
SKIP_GROUP_CHECK = os.getenv("SKIP_GROUP_CHECK", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}

PARTNER_BOT_URL = "https://t.me/Nobita_banbot"

REFERRALS_REQUIRED_FOR_PREMIUM = 10
PREMIUM_DURATION_SECONDS = 30 * 24 * 60 * 60  # 30 days
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_data.json"))
DB_LOCK = threading.Lock()


# ---------------- STYLISH FONTS, ITALIC & QUOTES ----------------
_ITALIC_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "𝐴𝐵𝐶𝐷𝐸𝐹𝐺𝐻𝐼𝐽𝐾𝐿𝑀𝑁𝑂𝑃𝑄𝑅𝑆𝑇𝑈𝑉𝑊𝑋𝑌𝑍𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧",
)

_SANS_BOLD_MAP = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
)


def to_revue_italic(text: str) -> str:
    return text.translate(_ITALIC_MAP)


def to_stylish_bold(text: str) -> str:
    return text.translate(_SANS_BOLD_MAP)


def bold_mono(text: str) -> str:
    return f"<b><code>{text}</code></b>"


def make_header(title: str, subtitle: str) -> str:
    return (
        f"⚡ <b>{to_stylish_bold(title)}</b> ⚡\n"
        f"<i>✦ {to_revue_italic(subtitle)} ✦</i>\n\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
    )


def make_quote(text: str) -> str:
    return f"<blockquote><i>“{to_revue_italic(text)}”</i></blockquote>\n"


def format_user_identity(user_id: int, full_name: str) -> str:
    return f"👤 <b>{to_revue_italic(full_name)}</b>  •  🆔 <code>{user_id}</code>"


def is_owner(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)


# ---------------- STORAGE HELPERS ----------------
def load_db() -> dict[str, Any]:
    default_data: dict[str, Any] = {
        "users": {},
        "tg_ban_cases": [],
        "mass_report_jobs": [],
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
            logger.exception("Failed to read database file; initializing fresh state.")
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
        return f"👑 <b>{to_revue_italic('Active Premium')}</b>  •  <code>{remaining_days} Days Left</code>"
    return f"🔹 <b>{to_revue_italic('Standard Access')}</b>  •  <code>10 Refs = 1M Free</code>"


# ---------------- KEEP-ALIVE WEB SERVER FOR RENDER ----------------
flask_app = Flask(__name__)


@flask_app.route("/")
def health_check():
    return f"{BOT_NAME} ({BOT_USERNAME}) is operational.", 200


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


async def check_all_requirements(bot, user_id: int) -> dict[str, bool]:
    channel_ok = await is_member_of(bot, MANDATORY_CHANNEL_REF, user_id)
    group_ok = True if SKIP_GROUP_CHECK else await is_member_of(bot, JOIN_GROUP_REF, user_id)

    return {
        "channel": channel_ok,
        "group": group_ok,
        "all_ok": channel_ok and group_ok,
    }


def build_gate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📢 Mandatory Channel", url=MANDATORY_CHANNEL_URL),
                InlineKeyboardButton("🔐 Requested Channel", url=REQUESTED_CHANNEL_URL),
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
                InlineKeyboardButton("🚨 Mass Report", callback_data="menu_mass_report"),
            ],
            [
                InlineKeyboardButton("💎 Referral & Premium", callback_data="menu_referral"),
                InlineKeyboardButton("🎧 Support", callback_data="menu_support"),
            ],
            [
                InlineKeyboardButton("📊 My Status", callback_data="menu_status"),
                InlineKeyboardButton("👑 Owner Contact", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}"),
            ],
            [
                InlineKeyboardButton("🤖 Partner Bot", url=PARTNER_BOT_URL),
            ],
        ]
    )


def build_premium_ban_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Group Ban", callback_data="ban_type_group"),
                InlineKeyboardButton("📢 Channel Ban", callback_data="ban_type_channel"),
            ],
            [
                InlineKeyboardButton("🎯 TG ID Ban", callback_data="ban_type_id"),
            ],
            [
                InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home"),
            ],
        ]
    )


def build_unlock_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👑 Contact Owner", url=f"https://t.me/{OWNER_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("💎 Referral & Premium", callback_data="menu_referral")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")],
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


async def run_tg_ban_animation(
    bot,
    chat_id: int,
    case_id: str,
    ban_type_title: str,
    target: str,
    user_full_name: str,
    user_id: int,
) -> None:
    """Phased live progress animation for Group Ban, Channel Ban, and TG ID Ban."""
    stages = [
        (
            8,
            "<code>[████░░░░░░░░░░░░░░░░] 20%</code>",
            f"Resolving {ban_type_title.lower()} target metadata and verifying queue slot...",
            "⏳ <b>Estimated Time:</b> <code>24s remaining</code>",
            f"🟡 <b>{to_revue_italic('Stage 1/4')}:</b> Target Lookup & Queue Lock",
        ),
        (
            8,
            "<code>[█████████░░░░░░░░░░░] 48%</code>",
            "Compiling structured moderation packet and routing through control nodes...",
            "⏳ <b>Estimated Time:</b> <code>16s remaining</code>",
            f"🟠 <b>{to_revue_italic('Stage 2/4')}:</b> Packet Routing & Node Sync",
        ),
        (
            8,
            "<code>[███████████████░░░░░] 78%</code>",
            "Executing priority moderation action and verifying ticket receipt...",
            "⏳ <b>Estimated Time:</b> <code>8s remaining</code>",
            f"🔵 <b>{to_revue_italic('Stage 3/4')}:</b> Action Execution & Verification",
        ),
        (
            8,
            "<code>[████████████████████] 100%</code>",
            "Moderation case finalized, logged, and forwarded to the owner.",
            "✅ <b>Completed:</b> <code>32s Total Cycle</code>",
            f"🟢 <b>{to_revue_italic('Stage 4/4')}:</b> Case Logged & Finalized",
        ),
    ]

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{make_header(f'{ban_type_title} ENGINE', 'LIVE EXECUTION')}"
            f"{make_quote(f'Initializing {ban_type_title.lower()} sequence for submitted target.')}"
            f"{format_user_identity(user_id, user_full_name)}\n\n"
            f"🎫 <b>Case ID:</b> <code>{case_id}</code>\n\n"
            f"⚔️ <b>Mode:</b> <b><i>{to_revue_italic(ban_type_title)}</i></b>\n\n"
            f"🎯 <b>Target:</b> <code>{target}</code>\n\n"
            f"<code>[██░░░░░░░░░░░░░░░░░░] 8%</code>\n\n"
            f"<i>{to_revue_italic('Initializing ban engine...')}</i>"
        ),
        parse_mode=ParseMode.HTML,
    )

    for idx, (delay_sec, bar, step_quote, time_line, stage_label) in enumerate(stages):
        await asyncio.sleep(delay_sec)
        is_final = idx == len(stages) - 1
        body = (
            f"{make_header(f'{ban_type_title} ENGINE', 'EXECUTION COMPLETE' if is_final else 'LIVE TELEMETRY')}"
            f"{make_quote(step_quote)}"
            f"{format_user_identity(user_id, user_full_name)}\n\n"
            f"🎫 <b>Case ID:</b> <code>{case_id}</code>\n\n"
            f"⚔️ <b>Mode:</b> <b><i>{to_revue_italic(ban_type_title)}</i></b>\n\n"
            f"🎯 <b>Target:</b> <code>{target}</code>\n\n"
            f"{stage_label}\n\n"
            f"{bar}\n\n"
            f"{time_line}\n\n"
            f"📌 <b>Status:</b> <b><i>{to_revue_italic('Logged & Queued' if is_final else 'Processing')}</i></b>"
        )
        try:
            await status_msg.edit_text(
                text=body,
                parse_mode=ParseMode.HTML,
                reply_markup=build_main_menu_keyboard() if is_final else None,
            )
        except TelegramError:
            pass

    try:
        await bot.send_message(
            chat_id=OWNER_ID,
            text=(
                f"{make_header(f'PREMIUM {ban_type_title}', case_id)}"
                f"{format_user_identity(user_id, user_full_name)}\n\n"
                f"⚔️ <b>Mode:</b> <b>{ban_type_title}</b>\n\n"
                f"🎯 <b>Target:</b> <code>{target}</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        pass


async def run_mass_report_animation(
    bot,
    chat_id: int,
    job_id: str,
    target: str,
    user_full_name: str,
    user_id: int,
) -> None:
    """Realistic 60-second (1-minute) phased progress animation for Mass Report."""
    stages = [
        (
            15,
            "<code>[███░░░░░░░░░░░░░░░░░] 15%</code>",
            "Validating target link and initializing multi-node report queue...",
            "⏳ <b>Estimated Time:</b> <code>45s remaining</code>",
            f"🟡 <b>{to_revue_italic('Stage 1/4')}:</b> Target Handshake & Queue Sync",
        ),
        (
            15,
            "<code>[████████░░░░░░░░░░░░] 42%</code>",
            "Dispatching Wave #1 structured abuse and spam report packets...",
            "⏳ <b>Estimated Time:</b> <code>30s remaining</code>",
            f"🟠 <b>{to_revue_italic('Stage 2/4')}:</b> Wave #1 Dispatch Active",
        ),
        (
            15,
            "<code>[██████████████░░░░░░] 74%</code>",
            "Rotating relay nodes and executing Wave #2 verification batch...",
            "⏳ <b>Estimated Time:</b> <code>15s remaining</code>",
            f"🔵 <b>{to_revue_italic('Stage 3/4')}:</b> Wave #2 Relay & Telemetry Check",
        ),
        (
            15,
            "<code>[████████████████████] 100%</code>",
            "All report batches dispatched and logged under priority ticket.",
            "✅ <b>Duration:</b> <code>60s (1m 00s) Completed</code>",
            f"🟢 <b>{to_revue_italic('Stage 4/4')}:</b> Dispatch Finalized",
        ),
    ]

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{make_header('MASS REPORT ENGINE', 'REAL-TIME EXECUTION')}"
            f"{make_quote('Initializing 60-second high-priority mass report sequence.')}"
            f"{format_user_identity(user_id, user_full_name)}\n\n"
            f"🎫 <b>Job ID:</b> <code>{job_id}</code>\n\n"
            f"🎯 <b>Target:</b> <code>{target}</code>\n\n"
            f"<code>[█░░░░░░░░░░░░░░░░░░░] 5%</code>\n\n"
            f"<i>{to_revue_italic('Booting report dispatcher...')}</i>"
        ),
        parse_mode=ParseMode.HTML,
    )

    for idx, (delay_sec, bar, step_quote, time_line, stage_label) in enumerate(stages):
        await asyncio.sleep(delay_sec)
        is_final = idx == len(stages) - 1
        body = (
            f"{make_header('MASS REPORT ENGINE', 'EXECUTION COMPLETE' if is_final else 'LIVE TELEMETRY')}"
            f"{make_quote(step_quote)}"
            f"{format_user_identity(user_id, user_full_name)}\n\n"
            f"🎫 <b>Job ID:</b> <code>{job_id}</code>\n\n"
            f"🎯 <b>Target:</b> <code>{target}</code>\n\n"
            f"{stage_label}\n\n"
            f"{bar}\n\n"
            f"{time_line}\n\n"
            f"📌 <b>Status:</b> <b><i>{to_revue_italic('Dispatched & Logged' if is_final else 'Running')}</i></b>"
        )
        try:
            await status_msg.edit_text(
                text=body,
                parse_mode=ParseMode.HTML,
                reply_markup=build_main_menu_keyboard() if is_final else None,
            )
        except TelegramError:
            pass

    try:
        await bot.send_message(
            chat_id=OWNER_ID,
            text=(
                f"{make_header('MASS REPORT COMPLETED', job_id)}"
                f"{format_user_identity(user_id, user_full_name)}\n\n"
                f"🎯 <b>Target:</b> <code>{target}</code>\n\n"
                f"⏱️ <b>Cycle:</b> <code>60s (1 Minute)</code>"
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
                                f"{make_header('NEW REFERRAL REGISTERED', 'REWARD MILESTONE TRACKER')}"
                                f"{make_quote('A new member has joined using your personal referral link.')}"
                                f"{format_user_identity(user.id, user.full_name)}\n\n"
                                f"📈 <b>Total Referrals:</b> <code>{ref_user['referrals']}</code>\n\n"
                                f"💎 <b>Membership:</b> {format_premium_status(ref_user)}"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramError:
                        pass

    save_db(db)
    status = await check_all_requirements(context.bot, user.id)

    if not status["all_ok"]:
        gate_caption = (
            f"{make_header(BOT_NAME, 'VERIFICATION GATEWAY')}"
            f"{make_quote('Unlock precision moderation, mass reporting, and referral rewards.')}"
            f"{format_user_identity(user.id, user.full_name)}\n\n"
            f"🤖 <b>{to_revue_italic('Bot Handle')}:</b> {bold_mono(BOT_USERNAME)}  •  👑 <b>{OWNER_USERNAME}</b>\n\n"
            f"<b><i>{to_revue_italic('Access Requirements')}</i></b>\n\n"
            f"{'✅' if status['channel'] else '❌'} <b>{to_revue_italic('Mandatory Channel')}</b>\n\n"
            f"🔹 <b>{to_revue_italic('Requested Channel')}</b> <code>(Optional Link)</code>\n\n"
            f"🔹 <b>{to_revue_italic('Join Group')}</b> <code>(Optional Link)</code>\n\n"
            f"🤖 <b>{to_revue_italic('Partner Bot')}:</b> <a href=\"{PARTNER_BOT_URL}\">{to_revue_italic('Nobita BanBot')}</a>\n\n"
            f"<i>{to_revue_italic('Complete the required channel step and tap Verify & Unlock Access.')}</i>"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=gate_caption,
            reply_markup=build_gate_keyboard(),
        )
        return

    welcome_caption = (
        f"{make_header(BOT_NAME, 'ELITE CONTROL SUITE')}"
        f"{make_quote('Crafted for refined control, 10-referral free premium, and priority support.')}"
        f"{format_user_identity(user.id, user.full_name)}\n\n"
        f"🤖 <b>{to_revue_italic('Bot')}:</b> {bold_mono(BOT_USERNAME)}  •  👑 <b>{OWNER_USERNAME}</b>\n\n"
        f"{format_premium_status(user_rec)}\n\n"
        f"<b><i>{to_revue_italic('Suite Modules')}</i></b>\n\n"
        f"⚔️ <b>{to_revue_italic('TG Ban')}</b> — Group, channel, and TG ID controls\n\n"
        f"🚨 <b>{to_revue_italic('Mass Report')}</b> — 60s multi-wave report sequence\n\n"
        f"💎 <b>{to_revue_italic('Referral & Premium')}</b> — <code>10 Referrals = 1M Free</code>\n\n"
        f"🎧 <b>{to_revue_italic('Support')}</b> — Direct assistance & tickets"
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
        f"{make_quote('Current operation has been cancelled. Use the main menu below.')}",
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
        status = await check_all_requirements(context.bot, user.id)
        if not status["all_ok"]:
            missing = []
            if not status["channel"]:
                missing.append(f"• <b>{to_revue_italic('Mandatory Channel')}:</b> {MANDATORY_CHANNEL_URL}")

            await query.message.reply_text(
                f"{make_header('VERIFICATION REQUIRED', 'ACCESS STILL LOCKED')}"
                f"{make_quote('Please join the required channel to unlock all bot features.')}"
                + "\n\n".join(missing),
                parse_mode=ParseMode.HTML,
                reply_markup=build_gate_keyboard(),
            )
            return

        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header(BOT_NAME, 'ACCESS VERIFIED')}"
                f"{make_quote('Your membership has been verified. Welcome to the control suite.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"{format_premium_status(user_rec)}"
            ),
            reply_markup=build_main_menu_keyboard(),
        )
        return

    if data == "menu_tg_ban":
        user_rec["awaiting_mode"] = None
        save_db(db)

        if not has_active_premium(user_rec):
            unlock_caption = (
                f"{make_header('UNLOCK PREMIUM ACCESS', 'EXCLUSIVE MODERATION SUITE')}"
                f"{make_quote(f'Dm : {OWNER_USERNAME}')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"🔹 <b>{to_revue_italic('You have normal access.')}</b>\n\n"
                f"💎 To unlock premium access, complete <code>10 referrals</code> or if you want direct access, DM the owner <b>{OWNER_USERNAME}</b>.\n\n"
                f"👑 <b>{to_revue_italic('Owner')}:</b> <b>{OWNER_USERNAME}</b>"
            )
            await send_stylish_video_message(
                context.bot,
                chat_id=chat_id,
                caption=unlock_caption,
                reply_markup=build_unlock_premium_keyboard(),
            )
            return

        premium_ban_caption = (
            f"{make_header('TG BAN CONTROL SUITE', 'SELECT TARGET OPERATION')}"
            f"{make_quote('Choose your target mode below to submit a moderation action.')}"
            f"{format_user_identity(user.id, user.full_name)}\n\n"
            f"{format_premium_status(user_rec)}\n\n"
            f"<b><i>{to_revue_italic('Available Modes')}</i></b>\n\n"
            f"👥 <b>{to_revue_italic('Group Ban')}</b> — Target a Telegram group link\n\n"
            f"📢 <b>{to_revue_italic('Channel Ban')}</b> — Target a Telegram channel link\n\n"
            f"🎯 <b>{to_revue_italic('TG ID Ban')}</b> — Target a user by @username"
        )
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=premium_ban_caption,
            reply_markup=build_premium_ban_keyboard(),
        )
        return

    if data == "menu_mass_report":
        if not has_active_premium(user_rec):
            user_rec["awaiting_mode"] = None
            save_db(db)
            unlock_caption = (
                f"{make_header('UNLOCK PREMIUM ACCESS', 'MASS REPORT ENGINE')}"
                f"{make_quote(f'Dm : {OWNER_USERNAME}')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"🔹 <b>{to_revue_italic('You have normal access.')}</b>\n\n"
                f"💎 To unlock premium access, complete <code>10 referrals</code> or if you want direct access, DM the owner <b>{OWNER_USERNAME}</b>.\n\n"
                f"👑 <b>{to_revue_italic('Owner')}:</b> <b>{OWNER_USERNAME}</b>"
            )
            await send_stylish_video_message(
                context.bot,
                chat_id=chat_id,
                caption=unlock_caption,
                reply_markup=build_unlock_premium_keyboard(),
            )
            return

        user_rec["awaiting_mode"] = "mass_report"
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('MASS REPORT SUITE', '60-SECOND EXECUTION ENGINE')}"
                f"{make_quote('Send the target link or @username to launch a 1-minute phased mass report cycle.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"{format_premium_status(user_rec)}\n\n"
                f"<b>{to_revue_italic('Send Link / Target Format')}:</b>\n"
                f"<code>https://t.me/+972zYAr5L1BjMmM1</code>\n\n"
                f"⏱️ <b>{to_revue_italic('Execution Cycle')}:</b> <code>60 Seconds (1 Minute)</code>\n\n"
                f"<i>{to_revue_italic('Send /cancel at any time to abort.')}</i>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")]]
            ),
        )
        return

    if data == "ban_type_group":
        user_rec["awaiting_mode"] = "ban_group"
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('GROUP BAN MODE', 'TARGET GROUP SUBMISSION')}"
                f"{make_quote('Send the target group link in the required format below.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"<b>{to_revue_italic('Send Link Format')}:</b>\n"
                f"<code>https://t.me/+972zYAr5L1BjMmM1</code>\n\n"
                f"<i>{to_revue_italic('Send /cancel at any time to abort.')}</i>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⬅️ Back to Ban Modes", callback_data="menu_tg_ban")],
                ]
            ),
        )
        return

    if data == "ban_type_channel":
        user_rec["awaiting_mode"] = "ban_channel"
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('CHANNEL BAN MODE', 'TARGET CHANNEL SUBMISSION')}"
                f"{make_quote('Send the target channel link in the required format below.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"<b>{to_revue_italic('Send Link Format')}:</b>\n"
                f"<code>https://t.me/+972zYAr5L1BjMmM1</code>\n\n"
                f"<i>{to_revue_italic('Send /cancel at any time to abort.')}</i>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⬅️ Back to Ban Modes", callback_data="menu_tg_ban")],
                ]
            ),
        )
        return

    if data == "ban_type_id":
        user_rec["awaiting_mode"] = "ban_tg_id"
        save_db(db)
        await send_stylish_video_message(
            context.bot,
            chat_id=chat_id,
            caption=(
                f"{make_header('TG ID BAN MODE', 'TARGET ACCOUNT SUBMISSION')}"
                f"{make_quote('Send the target username in the required format below.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"<b>{to_revue_italic('Send Format')}:</b>\n"
                f"<code>@username</code>\n\n"
                f"<i>{to_revue_italic('Send /cancel at any time to abort.')}</i>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⬅️ Back to Ban Modes", callback_data="menu_tg_ban")],
                ]
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
                f"{make_quote('Complete 10 referrals for 1 month of free premium access, or contact the owner directly.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"🔗 <b>{to_revue_italic('Personal Invite Link')}:</b>\n<code>{ref_link}</code>\n\n"
                f"📈 <b>{to_revue_italic('Total Referrals')}:</b> <code>{refs}</code>\n\n"
                f"🎯 <b>{to_revue_italic('Referrals Needed')}:</b> <code>{rem}</code>\n\n"
                f"💎 <b>{to_revue_italic('Status')}:</b> {format_premium_status(user_rec)}\n\n"
                f"👑 <b>{to_revue_italic('Owner')}:</b> <b>{OWNER_USERNAME}</b>"
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
                f"{make_header('SUPPORT DESK', 'DIRECT OWNER & TICKET ASSISTANCE')}"
                f"{make_quote('Send your inquiry directly here or reach out to the owner for priority assistance.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"👑 <b>{to_revue_italic('Owner')}:</b> <b>{OWNER_USERNAME}</b>\n\n"
                f"🤖 <b>{to_revue_italic('Partner Bot')}:</b> <a href=\"{PARTNER_BOT_URL}\">{to_revue_italic('Nobita BanBot')}</a>\n\n"
                f"<i>{to_revue_italic('Type your support message below to create a ticket.')}</i>"
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
                f"{make_header('ACCOUNT TELEMETRY', 'LIVE MEMBER OVERVIEW')}"
                f"{make_quote('Real-time summary of your profile, referrals, and premium subscription.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"📈 <b>{to_revue_italic('Total Referrals')}:</b> <code>{user_rec.get('referrals', 0)}</code>\n\n"
                f"💎 <b>{to_revue_italic('Subscription')}:</b> {format_premium_status(user_rec)}"
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
                f"{make_header(BOT_NAME, 'ELITE CONTROL SUITE')}"
                f"{make_quote('Crafted for refined control, 10-referral free premium, and priority support.')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"🤖 <b>{to_revue_italic('Bot')}:</b> {bold_mono(BOT_USERNAME)}  •  👑 <b>{OWNER_USERNAME}</b>\n\n"
                f"{format_premium_status(user_rec)}"
            ),
            reply_markup=build_main_menu_keyboard(),
        )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message or not update.message.text:
        return

    user = update.effective_user
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    db = load_db()
    user_rec = get_user(db, user.id, user.full_name, user.username or "")
    mode = user_rec.get("awaiting_mode")

    if mode == "mass_report":
        if not has_active_premium(user_rec):
            user_rec["awaiting_mode"] = None
            save_db(db)
            await update.message.reply_text(
                f"{make_header('UNLOCK PREMIUM ACCESS', 'PREMIUM REQUIRED')}"
                f"{make_quote(f'Dm : {OWNER_USERNAME}')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"🔹 <b>{to_revue_italic('You have normal access.')}</b>\n\n"
                f"💎 Complete <code>10 referrals</code> or DM <b>{OWNER_USERNAME}</b> for direct access.",
                parse_mode=ParseMode.HTML,
                reply_markup=build_unlock_premium_keyboard(),
            )
            return

        job_id = f"MR-{len(db['mass_report_jobs']) + 1001}"
        db["mass_report_jobs"].append(
            {
                "job_id": job_id,
                "submitted_by": user.id,
                "target": text,
                "timestamp": int(time.time()),
            }
        )
        user_rec["awaiting_mode"] = None
        save_db(db)

        asyncio.create_task(
            run_mass_report_animation(
                bot=context.bot,
                chat_id=chat_id,
                job_id=job_id,
                target=text,
                user_full_name=user.full_name,
                user_id=user.id,
            )
        )
        return

    if mode in {"ban_group", "ban_channel", "ban_tg_id"}:
        if not has_active_premium(user_rec):
            user_rec["awaiting_mode"] = None
            save_db(db)
            await update.message.reply_text(
                f"{make_header('UNLOCK PREMIUM ACCESS', 'PREMIUM REQUIRED')}"
                f"{make_quote(f'Dm : {OWNER_USERNAME}')}"
                f"{format_user_identity(user.id, user.full_name)}\n\n"
                f"🔹 <b>{to_revue_italic('You have normal access.')}</b>\n\n"
                f"💎 Complete <code>10 referrals</code> or DM <b>{OWNER_USERNAME}</b> for direct access.",
                parse_mode=ParseMode.HTML,
                reply_markup=build_unlock_premium_keyboard(),
            )
            return

        mode_labels = {
            "ban_group": "GROUP BAN",
            "ban_channel": "CHANNEL BAN",
            "ban_tg_id": "TG ID BAN",
        }
        ban_type_title = mode_labels[mode]
        case_id = f"CASE-{len(db['tg_ban_cases']) + 1001}"
        db["tg_ban_cases"].append(
            {
                "case_id": case_id,
                "ban_type": ban_type_title,
                "submitted_by": user.id,
                "payload": text,
                "timestamp": int(time.time()),
            }
        )
        user_rec["awaiting_mode"] = None
        save_db(db)

        asyncio.create_task(
            run_tg_ban_animation(
                bot=context.bot,
                chat_id=chat_id,
                case_id=case_id,
                ban_type_title=ban_type_title,
                target=text,
                user_full_name=user.full_name,
                user_id=user.id,
            )
        )
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
            f"{make_header('SUPPORT TICKET SUBMITTED', 'OWNER NOTIFIED')}"
            f"{make_quote('Your message has been delivered to the support team.')}"
            f"{format_user_identity(user.id, user.full_name)}\n\n"
            f"🎫 <b>Ticket ID:</b> <code>{ticket_id}</code>\n\n"
            f"👑 <b>Owner:</b> <b>{OWNER_USERNAME}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=build_main_menu_keyboard(),
        )
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"{make_header('NEW SUPPORT TICKET', ticket_id)}"
                    f"{format_user_identity(user.id, user.full_name)}\n\n"
                    f"{make_quote(text)}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    await update.message.reply_text(
        f"{make_header(BOT_NAME, 'NAVIGATION PROMPT')}"
        f"{make_quote('Use /start or select a button below to open the main control panel.')}"
        f"{format_user_identity(user.id, user.full_name)}",
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
        await update.message.reply_text("Duration must be greater than 0 days.")
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
        f"{make_header('PREMIUM GRANTED', 'OWNER ADMINISTRATION')}"
        f"🆔 <b>User ID:</b> <code>{target_id}</code>\n\n"
        f"⏳ <b>Duration Added:</b> <b>{days} Days</b>",
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                f"{make_header('PREMIUM ACTIVATED', 'VIP ACCESS GRANTED')}"
                f"{make_quote(f'Owner {OWNER_USERNAME} has granted you {days} days of Premium access.')}"
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
            f"⚠️ User <code>{target_id}</code> was not found in the database.",
            parse_mode=ParseMode.HTML,
        )
        return

    db["users"][target_id]["premium_until"] = 0
    save_db(db)

    await update.message.reply_text(
        f"{make_header('PREMIUM REVOKED', 'OWNER ADMINISTRATION')}"
        f"🆔 <b>User ID:</b> <code>{target_id}</code> premium access has been removed.",
        parse_mode=ParseMode.HTML,
    )
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=(
                f"{make_header('PREMIUM UPDATED', 'STANDARD ACCESS')}"
                f"{make_quote(f'Your premium access has been removed. Contact {OWNER_USERNAME} for assistance.')}"
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
            "Usage: <code>/broadcast &lt;message&gt;</code>",
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
        f"{make_header('BROADCAST COMPLETE', 'DELIVERY SUMMARY')}"
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
    total_jobs = len(db["mass_report_jobs"])
    total_tickets = len(db["support_tickets"])

    await update.message.reply_text(
        f"{make_header(BOT_NAME, 'SYSTEM TELEMETRY')}"
        f"👥 <b>Total Users:</b> <code>{total_users}</code>\n\n"
        f"👑 <b>Active Premium:</b> <code>{active_prem}</code>\n\n"
        f"⚔️ <b>TG Ban Cases:</b> <code>{total_cases}</code>\n\n"
        f"🚨 <b>Mass Report Jobs:</b> <code>{total_jobs}</code>\n\n"
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
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    logger.info("Starting %s (%s)...", BOT_NAME, BOT_USERNAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
