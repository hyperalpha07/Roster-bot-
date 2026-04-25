# -*- coding: utf-8 -*-
"""
ALPHA Final Roast Bot
Features:
- clean Bangla-only savage roast
- target/reason/memory logic
- normal message response
- target-name-only memory roast
- sender memory fallback
- reply targeting
- VS roast
- bot/admin protection
- repair mode
- admin-only memory delete
- shift/day-night user system
- users list
- group lock

Railway Start Command:
python bot.py

Required ENV:
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321
ALLOWED_GROUP_IDS=-1001234567890

Optional ENV:
TIMEZONE=Asia/Colombo
DATA_FILE=alpha_roast_data.json
BOT_USERNAME=YourBotUsername
"""

import asyncio
import json
import os
import random
import re
import html
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from telegram import Update, User
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
ALLOWED_GROUP_IDS = {
    int(x.strip())
    for x in os.getenv("ALLOWED_GROUP_IDS", "").replace(" ", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Colombo").strip()
DATA_FILE = Path(os.getenv("DATA_FILE", "alpha_roast_data.json")).resolve()

# Admin names are protected even if Telegram ID is not known yet.
PROTECTED_NAMES = {"alpha", "alfa", "আলফা", "admin", "এডমিন", "বস", "boss"}
BOT_NAMES = {"bot", "বট", "roastbot", "robot", "রোবট"}

TRIGGERS = [
    "rost", "roast", "পচা", "পচাও", "পচাই", "ফাপর", "fapor", "fapore", "target",
    "খোঁচা", "খোচা", "ধুয়ে দাও", "dhuye dao", "jhari", "ঝাড়", "ঝাড়"
]

NORMAL_RESPONSE = (
    "আমি normal message-এর জন্য না। আমাকে target বলো।\n"
    "উদাহরণ: <b>joni ফাপরে চলে</b> / <b>joni vs mony</b> / কারো message-এ reply দিয়ে কারণ লিখো।"
)
NO_MEMORY_RESPONSE = (
    "এই target-এর roast করার মতো তেমন কোনো তথ্য আমার কাছে নেই।\n"
    "তুমি আগে তার বিষয়ে কিছু বলো, তারপর আমি সুন্দর করে পচিয়ে দেব।"
)
PROTECTED_RESPONSE = (
    "Admin বা bot target করা যাবে না। আগে নিজের সাহস upgrade করো, তারপর অন্য target দাও।"
)
REPAIR_RESPONSE = (
    "Repair mode ON আছে। এখন আমি roast বন্ধ রেখেছি, শুধু admin system check করতে পারবে।"
)

# =========================================================
# DATA LAYER
# =========================================================
DEFAULT_DATA: Dict[str, Any] = {
    "settings": {
        "repair_mode": False,
        "group_lock": True,
        "allowed_group_ids": [],
    },
    "users": {},          # user_id: {id, name, username, role, shift, active, aliases, last_seen}
    "memories": {},       # normalized_name: [{text, by, at, source}]
    "recent_messages": {},# normalized_name: [text...]
    "name_to_id": {},     # normalized_name: user_id str
}


def now_iso() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds")


def now_hour() -> int:
    return datetime.now(ZoneInfo(TIMEZONE)).hour


def load_data() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return json.loads(json.dumps(DEFAULT_DATA))
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULT_DATA))
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        return merged
    except Exception:
        backup = DATA_FILE.with_suffix(".broken.json")
        try:
            DATA_FILE.rename(backup)
        except Exception:
            pass
        return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data: Dict[str, Any]) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def norm(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[@#:,;.!?।\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def safe(text: str) -> str:
    return html.escape(text or "")


def is_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def display_name(user: Optional[User]) -> str:
    if not user:
        return "Unknown"
    name = " ".join([p for p in [user.first_name, user.last_name] if p]).strip()
    return name or user.username or str(user.id)


def register_user(data: Dict[str, Any], user: Optional[User], role: str = "member") -> None:
    if not user:
        return
    uid = str(user.id)
    name = display_name(user)
    username = user.username or ""
    old = data["users"].get(uid, {})
    aliases = set(old.get("aliases", []))
    for item in [name, username, user.first_name or "", user.last_name or ""]:
        n = norm(item)
        if n:
            aliases.add(n)
            data["name_to_id"][n] = uid
    data["users"][uid] = {
        "id": user.id,
        "name": name,
        "username": username,
        "role": "admin" if is_admin(user.id) else old.get("role", role),
        "shift": old.get("shift", auto_shift_label()),
        "active": old.get("active", True),
        "aliases": sorted(aliases),
        "last_seen": now_iso(),
    }


def auto_shift_label() -> str:
    h = now_hour()
    if 7 <= h < 19:
        return "day"
    return "night"


def add_memory(data: Dict[str, Any], target: str, text: str, by: str, source: str = "manual") -> None:
    key = norm(target)
    if not key or not text.strip():
        return
    data["memories"].setdefault(key, [])
    data["memories"][key].append({
        "text": text.strip()[:500],
        "by": by,
        "at": now_iso(),
        "source": source,
    })
    data["memories"][key] = data["memories"][key][-25:]


def remember_recent(data: Dict[str, Any], who: str, text: str) -> None:
    key = norm(who)
    if not key or not text.strip():
        return
    data["recent_messages"].setdefault(key, [])
    data["recent_messages"][key].append(text.strip()[:300])
    data["recent_messages"][key] = data["recent_messages"][key][-12:]


def get_memories(data: Dict[str, Any], target: str) -> List[str]:
    key = norm(target)
    mems = [m.get("text", "") for m in data["memories"].get(key, []) if m.get("text")]
    recent = data["recent_messages"].get(key, [])[-4:]
    return (mems + recent)[-10:]


def all_known_names(data: Dict[str, Any]) -> List[str]:
    names = set(data.get("memories", {}).keys()) | set(data.get("name_to_id", {}).keys()) | set(data.get("recent_messages", {}).keys())
    for u in data.get("users", {}).values():
        for a in u.get("aliases", []):
            if a:
                names.add(a)
    return sorted(names, key=len, reverse=True)


def is_protected_target(data: Dict[str, Any], target: str) -> bool:
    key = norm(target)
    if not key:
        return False
    if key in PROTECTED_NAMES or key in BOT_NAMES:
        return True
    if BOT_USERNAME and key in {norm(BOT_USERNAME), norm("@" + BOT_USERNAME)}:
        return True
    uid = data.get("name_to_id", {}).get(key)
    if uid and uid.isdigit() and int(uid) in ADMIN_IDS:
        return True
    user_info = data.get("users", {}).get(str(uid), {}) if uid else {}
    if user_info.get("role") == "admin":
        return True
    return False


def allowed_chat(data: Dict[str, Any], chat_id: int, chat_type: str) -> bool:
    if chat_type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return True
    locked = data.get("settings", {}).get("group_lock", True)
    if not locked:
        return True
    allowed = set(ALLOWED_GROUP_IDS)
    allowed.update(int(x) for x in data.get("settings", {}).get("allowed_group_ids", []) if str(x).lstrip("-").isdigit())
    return not allowed or chat_id in allowed

# =========================================================
# TARGET PARSER
# =========================================================
@dataclass
class ParsedTarget:
    mode: str
    target: Optional[str] = None
    target2: Optional[str] = None
    reason: str = ""


def clean_command_words(text: str) -> str:
    t = text.strip()
    for w in TRIGGERS:
        t = re.sub(rf"\b{re.escape(w)}\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_vs(text: str) -> Optional[Tuple[str, str, str]]:
    raw = text.strip()
    patterns = [r"(.+?)\s+vs\s+(.+)", r"(.+?)\s+VS\s+(.+)", r"(.+?)\s+versus\s+(.+)"]
    for p in patterns:
        m = re.search(p, raw, flags=re.I)
        if m:
            left = clean_command_words(m.group(1)).strip(" ,।")
            right_part = clean_command_words(m.group(2)).strip(" ,।")
            pieces = right_part.split()
            if pieces:
                right = pieces[0]
                reason = " ".join(pieces[1:]).strip()
                return left, right, reason
    return None


def find_known_target(data: Dict[str, Any], text: str) -> Optional[str]:
    low = " " + norm(text) + " "
    for name in all_known_names(data):
        if len(name) < 2:
            continue
        if f" {name} " in low:
            return name
    return None


def parse_message(data: Dict[str, Any], update: Update) -> ParsedTarget:
    msg = update.effective_message
    text = msg.text or msg.caption or ""

    # Reply targeting: reply to someone's message + reason = target replied user.
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_name = display_name(msg.reply_to_message.from_user)
        reason = clean_command_words(text)
        return ParsedTarget(mode="reply", target=target_name, reason=reason)

    vs = parse_vs(text)
    if vs:
        return ParsedTarget(mode="vs", target=vs[0], target2=vs[1], reason=vs[2])

    known = find_known_target(data, text)
    if known:
        reason = clean_command_words(re.sub(re.escape(known), " ", text, flags=re.I)).strip()
        return ParsedTarget(mode="single", target=known, reason=reason)

    # Pattern: first word as target if trigger/reason exists.
    words = text.strip().split()
    has_trigger = any(w.lower() in text.lower() for w in TRIGGERS)
    if words and has_trigger:
        target = words[0].lstrip("@").strip(" ,।")
        reason = clean_command_words(" ".join(words[1:]))
        return ParsedTarget(mode="single", target=target, reason=reason)

    return ParsedTarget(mode="normal")

# =========================================================
# ROAST ENGINE - Bangla only, clean savage, no vulgar words
# =========================================================
OPENERS = [
    "আজকের target <b>{target}</b>, আর অবস্থা দেখে মনে হচ্ছে আত্মবিশ্বাসটা full charge, কিন্তু কাজের speed এখনো loading screen-এ আটকে আছে।",
    "<b>{target}</b> এমন confidence নিয়ে চলে, যেন পুরো group তার fan club; বাস্তবে সবাই শুধু screenshot নেওয়ার অপেক্ষায় থাকে।",
    "<b>{target}</b>-কে দেখলে বোঝা যায়, drama free life সম্ভব না—কারণ drama নিজেই হাঁটতে হাঁটতে চলে এসেছে।",
]

REASON_LINES = [
    "কারণটা পরিষ্কার: <b>{reason}</b>। এই level-এর performance দেখে calculator-ও হিসাব করতে লজ্জা পায়।",
    "ঘটনা হলো: <b>{reason}</b>। এত সুন্দরভাবে নিজেকে expose করা সত্যিই rare talent।",
    "Main point: <b>{reason}</b>। এখানে আর roast লাগে না, ঘটনা নিজেই premium insult package।",
]

MEMORY_LINES = [
    "আগের record বলছে: <b>{memory}</b>। তাই আজকের roast নতুন না, শুধু পুরোনো file আবার open হলো।",
    "Memory থেকে দেখা যাচ্ছে: <b>{memory}</b>। মানুষ ভুলতে পারে, bot কিন্তু evidence রাখে।",
    "তার history-তে লেখা আছে: <b>{memory}</b>। এই data দেখে reputation নিজেই silent mode-এ চলে গেছে।",
]

FALLBACK_LINES = [
    "তথ্য কম, কিন্তু vibe যথেষ্ট। <b>{target}</b> এমনভাবে serious হয়, যেন meeting করছে; ফলাফল দেখে মনে হয় practice match-ও না।",
    "<b>{target}</b>-এর সমস্যা হলো কথা বলার আগে confidence আসে, logic পরে রাস্তা খুঁজে।",
    "তথ্য না থাকলেও আন্দাজ পরিষ্কার—<b>{target}</b> আগে pose দেয়, পরে বুঝে scene কী ছিল।",
]

CLOSERS = [
    "তাই শান্ত থাকো, পানি খাও, আর পরেরবার entry দেওয়ার আগে নিজের software update করে এসো।",
    "Group-এ comeback করতে চাইলে আগে performance দাও, excuse না।",
    "আজ এতটুকুই যথেষ্ট—বাকি দিলে self-respect নিজেই leave request দিয়ে দেবে।",
]

VS_LINES = [
    "<b>{a}</b> vs <b>{b}</b> — এটা fight না, এটা হলো কে আগে নিজের logic হারাবে সেই competition।",
    "এক পাশে <b>{a}</b>, আরেক পাশে <b>{b}</b>; দুইজনের confidence high, কিন্তু proof দুজনেরই network problem।",
    "<b>{a}</b> আর <b>{b}</b> একসাথে নামলে group শান্ত থাকে না, কারণ comedy আর confusion একই stage-এ উঠে পড়ে।",
]


def make_roast(target: str, reason: str, memories: List[str]) -> str:
    parts = [random.choice(OPENERS).format(target=safe(target))]
    if reason and len(reason.strip()) > 1:
        parts.append(random.choice(REASON_LINES).format(reason=safe(reason[:220])))
    if memories:
        mem = random.choice(memories[-6:])
        parts.append(random.choice(MEMORY_LINES).format(memory=safe(mem[:220])))
    if not reason and not memories:
        parts.append(random.choice(FALLBACK_LINES).format(target=safe(target)))
    parts.append(random.choice(CLOSERS))
    return "\n\n".join(parts)


def make_vs_roast(a: str, b: str, reason: str, mem_a: List[str], mem_b: List[str]) -> str:
    parts = [random.choice(VS_LINES).format(a=safe(a), b=safe(b))]
    if reason:
        parts.append(f"আজকের issue: <b>{safe(reason[:220])}</b>।")
    if mem_a:
        parts.append(f"<b>{safe(a)}</b>-এর file থেকে: <b>{safe(random.choice(mem_a[-5:])[:180])}</b>।")
    if mem_b:
        parts.append(f"<b>{safe(b)}</b>-এর file থেকেও কম যায় না: <b>{safe(random.choice(mem_b[-5:])[:180])}</b>।")
    if not mem_a and not mem_b and not reason:
        parts.append("দুইজনের ব্যাপারেই data কম, কিন্তু group-এর reaction দেখে বোঝা যাচ্ছে problem real।")
    parts.append("Final result: দুজনেই একটু চুপ থাকলে group-এর battery বাঁচে।")
    return "\n\n".join(parts)

# =========================================================
# COMMANDS
# =========================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    register_user(data, update.effective_user)
    save_data(data)
    await update.effective_message.reply_text(
        "Alpha Roast Bot ready. Group-এ target বললেই roast হবে। /help দেখো।",
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Commands</b>\n"
        "/users - user list + shift\n"
        "/mem name text - memory save\n"
        "/memory name - memory দেখো\n"
        "/delmem name - memory delete, admin only\n"
        "/shift name day|night|off - shift set, admin only\n"
        "/repair_on /repair_off - admin only\n"
        "/lockgroup /unlockgroup - admin only\n"
        "/setgroup - current group allow, admin only\n\n"
        "<b>Use</b>\n"
        "joni ফাপরে চলে\n"
        "joni vs mony\n"
        "কারো message-এ reply দিয়ে কারণ লিখো"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    register_user(data, update.effective_user)
    save_data(data)
    users = list(data.get("users", {}).values())
    if not users:
        await update.effective_message.reply_text("এখনো কোনো user save নেই।")
        return
    lines = ["<b>Users / Shift List</b>"]
    for u in sorted(users, key=lambda x: (x.get("shift", ""), x.get("name", ""))):
        role = "ADMIN" if u.get("role") == "admin" else "USER"
        active = "ON" if u.get("active", True) else "OFF"
        lines.append(f"• <b>{safe(u.get('name','Unknown'))}</b> — {safe(u.get('shift','auto'))} — {role} — {active}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def setgroup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    chat = update.effective_chat
    data = load_data()
    arr = set(int(x) for x in data["settings"].get("allowed_group_ids", []) if str(x).lstrip("-").isdigit())
    arr.add(chat.id)
    data["settings"]["allowed_group_ids"] = sorted(arr)
    save_data(data)
    await update.effective_message.reply_text(f"এই group allow করা হলো: <code>{chat.id}</code>", parse_mode=ParseMode.HTML)


async def lockgroup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    data = load_data()
    data["settings"]["group_lock"] = True
    save_data(data)
    await update.effective_message.reply_text("Group lock ON। এখন শুধু allowed group-এ কাজ করবে।")


async def unlockgroup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    data = load_data()
    data["settings"]["group_lock"] = False
    save_data(data)
    await update.effective_message.reply_text("Group lock OFF।")


async def repair_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    data = load_data()
    data["settings"]["repair_mode"] = True
    save_data(data)
    await update.effective_message.reply_text("Repair mode ON।")


async def repair_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    data = load_data()
    data["settings"]["repair_mode"] = False
    save_data(data)
    await update.effective_message.reply_text("Repair mode OFF। Bot আবার active।")


async def mem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    register_user(data, update.effective_user)
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text("Use: /mem name তার বিষয়ে তথ্য")
        return
    target = args[0].lstrip("@")
    text = " ".join(args[1:]).strip()
    if is_protected_target(data, target) and not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(PROTECTED_RESPONSE)
        return
    add_memory(data, target, text, display_name(update.effective_user), "manual")
    save_data(data)
    await update.effective_message.reply_text(f"Memory saved: <b>{safe(target)}</b>", parse_mode=ParseMode.HTML)


async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if not context.args:
        await update.effective_message.reply_text("Use: /memory name")
        return
    target = " ".join(context.args).strip().lstrip("@")
    mems = get_memories(data, target)
    if not mems:
        await update.effective_message.reply_text(NO_MEMORY_RESPONSE)
        return
    lines = [f"<b>{safe(target)} memory</b>"] + [f"• {safe(m)}" for m in mems[-10:]]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def delmem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Memory delete শুধু admin করতে পারবে।")
        return
    data = load_data()
    if not context.args:
        await update.effective_message.reply_text("Use: /delmem name")
        return
    target = norm(" ".join(context.args))
    removed = False
    for box in ["memories", "recent_messages"]:
        if target in data.get(box, {}):
            data[box].pop(target, None)
            removed = True
    save_data(data)
    await update.effective_message.reply_text("Memory deleted." if removed else "এই নামে কোনো memory পাইনি।")


async def shift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    data = load_data()
    if len(context.args) < 2:
        await update.effective_message.reply_text("Use: /shift name day|night|off")
        return
    shift = context.args[-1].lower()
    if shift not in {"day", "night", "off"}:
        await update.effective_message.reply_text("Shift হবে: day / night / off")
        return
    target = norm(" ".join(context.args[:-1]).lstrip("@"))
    uid = data.get("name_to_id", {}).get(target)
    if not uid:
        # create shadow user by name
        uid = f"name:{target}"
        data["users"].setdefault(uid, {"id": uid, "name": target, "username": "", "role": "member", "aliases": [target]})
        data["name_to_id"][target] = uid
    data["users"].setdefault(uid, {})
    data["users"][uid]["shift"] = shift
    data["users"][uid]["active"] = shift != "off"
    data["users"][uid].setdefault("name", target)
    data["users"][uid].setdefault("aliases", [target])
    save_data(data)
    await update.effective_message.reply_text(f"Shift updated: <b>{safe(target)}</b> → <b>{shift}</b>", parse_mode=ParseMode.HTML)

# =========================================================
# MESSAGE HANDLER
# =========================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not user or not (msg.text or msg.caption):
        return

    data = load_data()
    register_user(data, user)

    if not allowed_chat(data, chat.id, chat.type):
        save_data(data)
        return

    text = msg.text or msg.caption or ""
    sender_name = display_name(user)
    remember_recent(data, sender_name, text)

    if data.get("settings", {}).get("repair_mode") and not is_admin(user.id):
        save_data(data)
        await msg.reply_text(REPAIR_RESPONSE)
        return

    parsed = parse_message(data, update)

    if parsed.mode == "normal":
        save_data(data)
        # Only respond in groups when bot mentioned or message looks like it expects bot.
        bot_mentioned = BOT_USERNAME and ("@" + BOT_USERNAME.lower()) in text.lower()
        has_trigger = any(t.lower() in text.lower() for t in TRIGGERS)
        if bot_mentioned or has_trigger:
            await msg.reply_text(NORMAL_RESPONSE, parse_mode=ParseMode.HTML)
        return

    if parsed.mode == "vs" and parsed.target and parsed.target2:
        if is_protected_target(data, parsed.target) or is_protected_target(data, parsed.target2):
            save_data(data)
            await msg.reply_text(PROTECTED_RESPONSE)
            return
        mem_a = get_memories(data, parsed.target)
        mem_b = get_memories(data, parsed.target2)
        if parsed.reason:
            add_memory(data, parsed.target, parsed.reason, sender_name, "auto_vs")
            add_memory(data, parsed.target2, parsed.reason, sender_name, "auto_vs")
        save_data(data)
        await msg.reply_text(make_vs_roast(parsed.target, parsed.target2, parsed.reason, mem_a, mem_b), parse_mode=ParseMode.HTML)
        return

    target = parsed.target or ""
    if not target:
        save_data(data)
        await msg.reply_text(NORMAL_RESPONSE, parse_mode=ParseMode.HTML)
        return

    if is_protected_target(data, target):
        save_data(data)
        await msg.reply_text(PROTECTED_RESPONSE)
        return

    memories = get_memories(data, target)

    # If target-name-only and no memory, ask for info.
    if not parsed.reason and not memories:
        # sender memory fallback: if sender has memory and target has none, roast sender lightly.
        sender_mems = get_memories(data, sender_name)
        save_data(data)
        if sender_mems:
            await msg.reply_text(
                "এই target-এর data কম, তাই আপাতত যে ডাক দিয়েছে তাকেই ধরলাম।\n\n" + make_roast(sender_name, "target না দিয়ে scene বানাতে এসেছে", sender_mems),
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.reply_text(NO_MEMORY_RESPONSE, parse_mode=ParseMode.HTML)
        return

    if parsed.reason:
        add_memory(data, target, parsed.reason, sender_name, "auto_reason")
        memories = get_memories(data, target)

    save_data(data)
    await msg.reply_text(make_roast(target, parsed.reason, memories), parse_mode=ParseMode.HTML)

# =========================================================
# ERROR HANDLER
# =========================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("ERROR:", repr(context.error))

# =========================================================
# MAIN
# =========================================================
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing. Add BOT_TOKEN in Railway Variables.")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("setgroup", setgroup_cmd))
    app.add_handler(CommandHandler("lockgroup", lockgroup_cmd))
    app.add_handler(CommandHandler("unlockgroup", unlockgroup_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on_cmd))
    app.add_handler(CommandHandler("repair_off", repair_off_cmd))
    app.add_handler(CommandHandler("mem", mem_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("delmem", delmem_cmd))
    app.add_handler(CommandHandler("shift", shift_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    print("Alpha Roast Bot starting...")
    print(f"Data file: {DATA_FILE}")
    print(f"Admins: {sorted(ADMIN_IDS)}")
    print(f"Allowed groups: {sorted(ALLOWED_GROUP_IDS)}")
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
