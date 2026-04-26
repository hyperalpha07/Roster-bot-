import os
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

MEMORY_FILE = "memory.json"
REPAIR_MODE = False

def load_memory():
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": {}}

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

memory = load_memory()

async def save_message(uid, name, text):
    uid = str(uid)
    if uid not in memory["users"]:
        memory["users"][uid] = {"name": name, "messages": [], "flaws": []}
    
    memory["users"][uid]["messages"].append({"text": text, "time": datetime.now().isoformat()})
    
    if len(memory["users"][uid]["messages"]) > 40:
        memory["users"][uid]["messages"] = memory["users"][uid]["messages"][-40:]
    
    save_memory(memory)

def is_targeting(text):
    targets = ['তুই', 'তোকে', 'তোর', 'তোরা', 'শালা', 'পাগলা', 'বোকা', 'গাধা', 'ফাপর', 'বাজে', 'রে', 'কে', 'কার', 'নিয়া', 'নিয়ে', 'কথা', 'বলেন', 'বলো', 'গাদা', 'পোলা', 'ভাই', 'কি বলছিস', 'কী বলছ', 'আয়', 'দেখ', 'শুন']
    t = text.lower()
    return any(x in t for x in targets)

async def get_flaws(uid, name):
    if uid not in memory["users"]:
        return None
    msgs = memory["users"][uid].get("messages", [])
    if len(msgs) < 2:
        return None
    
    recent = "\n".join([f"- {m['text'][:80]}" for m in msgs[-12:]])
    
    prompt = f"{name} এর কথাগুলো দেখে ২-৩ লাইনে তার দুর্বলতা/ফাপর বের কর:\n{recent}\n\nদুর্বলতা:"
    try:
        r = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=120
        )
        return r.choices[0].message.content.strip()
    except:
        return None

async def make_roast(attacker, target, msg, flaws):
    flaw_text = f"\n{target} এর ফাপরামি: {flaws}" if flaws else ""
    prompt = f"""{attacker} {target} কে বলল: "{msg}"{flaw_text}
এখন {target} এর হয়ে {attacker} কে ২ লাইনের তীব্র বাংলা রোস্ট দাও (গালি ছাড়া):

রোস্ট:"""
    try:
        r = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=120
        )
        return r.choices[0].message.content.strip()
    except:
        return f"{attacker}, তোর রোস্ট খাওয়ার ক্লাস নাই বলেই API গেলো 😂"

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    if REPAIR_MODE:
        return
    
    m = update.message
    if not m or not m.text:
        return
    
    chat = m.chat
    if chat.type not in ["group", "supergroup"]:
        return
    
    sender = m.from_user
    text = m.text
    
    # কমান্ড চেক
    if text.startswith('/'):
        return
    
    await save_message(sender.id, sender.first_name or sender.username or "কে যেন", text)
    
    # টার্গেট চেক
    if not is_targeting(text) and not m.reply_to_message:
        return
    
    # টার্গেট বের করো
    target = None
    if m.reply_to_message:
        target = m.reply_to_message.from_user
    elif m.entities:
        for e in m.entities:
            if e.type == "text_mention":
                target = e.user
                break
    
    if not target:
        # নাম না পেলে সেন্ডারকেই ধরি
        target = sender
    
    # বট নিজেকে টার্গেট করলে
    if target.id == context.bot.id:
        await m.reply_text(f"🫡 {sender.first_name}, বটের ঘাড়ে ধরা দেয়ার পয়েন্ট নাই, আগে নিজের দেখো।")
        return
    
    # দুর্বলতা বের করো
    flaws = await get_flaws(str(target.id), target.first_name or target.username or "ওই যে")
    
    # রোস্ট জেনারেট
    roast = await make_roast(
        sender.first_name or sender.username or "কে যেন",
        target.first_name or target.username or "ওই ভাই",
        text,
        flaws
    )
    
    await m.reply_text(f"🔥 {roast}")

# ========== কমান্ড গুলো ==========

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **রোস্টার বট চালু!**\n\n"
        "কে কাউকে গালি দিলে/রিপ্লাই করলে বট রোস্ট দেবে।\n\n"
        "👑 **অ্যাডমিন:**\n"
        "/repair_on - বট বন্ধ\n"
        "/repair_off - বট চালু\n"
        "/clear - সব মেমরি ডিলিট\n"
        "/users - সব ইউজার দেখো\n"
        "/status - বট স্ট্যাটাস",
        parse_mode="Markdown"
    )

async def cmd_repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন!")
        return
    REPAIR_MODE = True
    await update.message.reply_text("🔴 রিপেয়ার মোড অন - বট বন্ধ")

async def cmd_repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন!")
        return
    REPAIR_MODE = False
    await update.message.reply_text("🟢 রিপেয়ার মোড অফ - বট চালু")

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন!")
        return
    memory["users"] = {}
    save_memory(memory)
    await update.message.reply_text("🗑️ সব ডাটা ডিলিট")

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 কোনো ডাটা নাই")
        return
    lines = []
    for uid, data in list(memory["users"].items())[:15]:
        lines.append(f"👤 {data.get('name', 'নামহীন')} - {len(data.get('messages', []))} টি মেসেজ")
    await update.message.reply_text("📋 ইউজার লিস্ট:\n" + "\n".join(lines))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uc = len(memory["users"])
    mc = sum(len(u.get("messages", [])) for u in memory["users"].values())
    mode = "🔧 রিপেয়ার" if REPAIR_MODE else "✅ নরমাল"
    await update.message.reply_text(f"📊 স্ট্যাটাস\n👥 ইউজার: {uc}\n💬 মেসেজ: {mc}\n⚙️ মোড: {mode}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("repair_on", cmd_repair_on))
    app.add_handler(CommandHandler("repair_off", cmd_repair_off))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    
    print("✅ রোস্টার বট চালু...")
    app.run_polling()

if __name__ == "__main__":
    main()
