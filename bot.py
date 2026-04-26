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
        memory["users"][uid] = {"name": name, "messages": []}
    
    memory["users"][uid]["messages"].append({"text": text, "time": datetime.now().isoformat()})
    
    if len(memory["users"][uid]["messages"]) > 30:
        memory["users"][uid]["messages"] = memory["users"][uid]["messages"][-30:]
    
    save_memory(memory)

def is_targeting(text):
    """বাংলা টার্গেটিং শনাক্ত"""
    targets = ['তুই', 'তোকে', 'তোর', 'তোরা', 'শালা', 'পাগলা', 'বোকা', 'গাধা', 'ফাপর', 
               'বাজে', 'রে', 'কে', 'কার', 'নিয়া', 'নিয়ে', 'কথা', 'বলেন', 'বলো', 'গাদা', 
               'পোলা', 'ভাই', 'কি বলছিস', 'কী বলছ', 'আয়', 'দেখ', 'শুন', 'মোনির', 'মনির', 
               'ke', 'niye', 'kichu', 'bolen', 'akta']
    t = text.lower()
    return any(x in t for x in targets)

async def generate_bangla_roast(attacker_name, target_name, user_message, old_messages):
    """শুধু বাংলায় রোস্ট জেনারেট করবে"""
    
    # পুরনো মেসেজ থেকে পয়েন্ট বের করার জন্য
    old_text = ""
    if old_messages and len(old_messages) > 2:
        recent = old_messages[-10:]
        old_text = "\n".join([f"- {m['text']}" for m in recent])
        old_text = f"\n\n{target_name} এর আগের কিছু কথা:\n{old_text}\n"
    
    prompt = f"""তুমি একজন বাংলা স্যাভেজ রোস্ট বট। তোমার কাজ হলো মজার কিন্তু তীক্ষ্ণ রোস্ট দেওয়া।

{attacker_name} {target_name} কে টার্গেট করে বলেছে: "{user_message}"{old_text}

এখন শুধু বাংলা ভাষায় {target_name} এর হয়ে {attacker_name} কে একটি স্যাভেজ রোস্ট দাও।

নিয়ম:
- শুধুমাত্র বাংলা ভাষায় লিখতে হবে (কোনো হিন্দি/উর্দু/ইংরেজি নয়)
- গালি দেওয়া যাবে
- ২ থেকে ৩ লাইনের মধ্যে রাখো
- নাম ধরে সম্বোধন করো
- তীক্ষ্ণ, ব্যাঙ্গাত্মক এবং মজার হতে হবে

উদাহরণ:
"জনি কাকা, তোর কনফিডেন্স দেখে মনে হয় গ্রুপের সিইও, কিন্তু কাজের বেলায় নেটওয়ার্কের বাইরে। আগে নিজের পারফরম্যান্স রিপোর্ট দে ভাই!"

এখন তোমার রোস্ট দাও (শুধু বাংলায়):"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "তুমি শুধু বাংলা ভাষায় উত্তর দেবে। কোনো হিন্দি বা উর্দু শব্দ ব্যবহার করবে না। তুমি একজন মজার রোস্ট বট।"},
                {"role": "user", "content": prompt}
            ],
            temperature=1.0,
            max_tokens=150
        )
        roast = response.choices[0].message.content.strip()
        
        # যদি হিন্দি/উর্দু চলে আসে তাহলে ফিক্স
        if any(word in roast for word in ['है', 'कर', 'में', 'को', 'से', 'का', 'की', 'वाला', 'गया']):
            return f"{attacker_name}, তোর জন্য রোস্ট বানানো কঠিন! 🤣"
        
        return roast
    except Exception as e:
        return f"🔥 {attacker_name}, তুই এত ফাপর যে রোস্ট দিতে API ও হেরে গেল! 😂"

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
    
    # সেভ ইউজার মেসেজ
    await save_message(sender.id, sender.first_name or sender.username or "কে যেন", text)
    
    # টার্গেট চেক
    is_target = is_targeting(text.lower())
    is_reply = m.reply_to_message is not None
    
    if not is_target and not is_reply:
        return
    
    # টার্গেট নির্ধারণ
    target = None
    if is_reply and m.reply_to_message.from_user:
        target = m.reply_to_message.from_user
    elif m.entities:
        for e in m.entities:
            if e.type == "text_mention":
                target = e.user
                break
    
    # যদি টার্গেট না পাওয়া যায়, সেন্ডারকেই ধরি (নিজেকে রোস্ট)
    if not target:
        target = sender
    
    # বট নিজেকে প্রটেক্ট
    if target.id == context.bot.id:
        await m.reply_text(f"🫡 {sender.first_name}, বটের পিছনে না লেগে নিজের দাগ দেখো আগে!")
        return
    
    # টার্গেটের পুরনো মেসেজ পাওয়া
    target_uid = str(target.id)
    old_msgs = memory["users"].get(target_uid, {}).get("messages", [])
    
    # রোস্ট জেনারেট
    roast = await generate_bangla_roast(
        sender.first_name or sender.username or "কে যেন",
        target.first_name or target.username or target.first_name or "ওই ভাই",
        text,
        old_msgs
    )
    
    await m.reply_text(f"🎯 {roast}\n\n💀")

# ========== কমান্ড ==========

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **রোস্টার বট - বাংলা স্যাভেজ সংস্করণ**\n\n"
        "যেভাবে ব্যবহার করবেন:\n"
        "• কাউকে রিপ্লাই করে কিছু বলুন\n"
        "• 'তুই বোকা', 'গাধা' জাতীয় কিছু বলুন\n"
        "• মনিরের মতো 'monir akta gadha' বলুন\n\n"
        "👑 **কমান্ড:**\n"
        "/repair_on - বট বন্ধ\n"
        "/repair_off - বট চালু\n"
        "/clear - সব মেমরি ডিলিট\n"
        "/users - ইউজার লিস্ট দেখুন\n"
        "/status - বট স্ট্যাটাস",
        parse_mode="Markdown"
    )

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 অ্যাডমিন ছাড়া পারবে না!")
        return
    REPAIR_MODE = True
    await update.message.reply_text("🔴 রিপেয়ার মোড অন - বট বন্ধ আছে")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 অ্যাডমিন ছাড়া পারবে না!")
        return
    REPAIR_MODE = False
    await update.message.reply_text("🟢 রিপেয়ার মোড অফ - বট চালু আছে")

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 অ্যাডমিন ছাড়া পারবে না!")
        return
    global memory
    memory = {"users": {}}
    save_memory(memory)
    await update.message.reply_text("🗑️ সব মেমরি ডিলিট করা হয়েছে")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 এখনো কোনো ইউজার ডাটা নেই")
        return
    
    lines = []
    for uid, data in list(memory["users"].items())[:20]:
        name = data.get("name", "নামবিহীন")
        msg_count = len(data.get("messages", []))
        lines.append(f"👤 {name} - {msg_count} টি মেসেজ")
    
    await update.message.reply_text("📋 **ইউজার লিস্ট:**\n" + "\n".join(lines), parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_count = len(memory["users"])
    msg_count = sum(len(u.get("messages", [])) for u in memory["users"].values())
    mode = "🔧 রিপেয়ার" if REPAIR_MODE else "✅ নরমাল"
    await update.message.reply_text(
        f"📊 **বট স্ট্যাটাস**\n\n"
        f"👥 ইউজার: {user_count}\n"
        f"💬 মেসেজ: {msg_count}\n"
        f"⚙️ মোড: {mode}",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    
    print("✅ বাংলা রোস্টার বট চালু...")
    app.run_polling()

if __name__ == "__main__":
    main()
