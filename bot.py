import os
import json
import random
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
    targets = ['তুই', 'তোকে', 'তোর', 'তোরা', 'শালা', 'পাগলা', 'বোকা', 'গাধা', 'ফাপর', 
               'বাজে', 'রে', 'নিয়া', 'নিয়ে', 'কথা', 'বলেন', 'বলো', 'গাদা', 'পোলা', 
               'ভাই', 'কি বলছিস', 'কী বলছ', 'monir', 'joni', 'akta', 'gadha', 'niye', 
               'kichu', 'bolen', 'faltu', 'bot', 'take', 'rost', 'kor', 'কে']
    t = text.lower()
    return any(x in t for x in targets)

# কিছু প্রি-বিল্ট রোস্ট (API fail করলে ব্যবহার হবে)
FALLBACK_ROASTS = [
    "তোর কনফিডেন্স দেখে মনে হয় গ্রুপের সিইও, কিন্তু কাজের বেলায় নেটওয়ার্কের বাইরে!",
    "তুই এত ফাপর যে তোর কথা শুনলে মনে হয় টেলিভিশনের নিউজ, পুরো মিথ্যা!",
    "তোর বুদ্ধির চেয়ে তোর জুতার ফিতা বেশি কাজ করে!",
    "তুই যেই কনফিডেন্স নিয়ে কথা বলিস, সেটা দেখলে মনে হয় তুই বিশ্ব জয় করছিস, অথচ তুই ফ্যান পেজের অ্যাডমিন!",
    "তোর মাথায় বুদ্ধি না থাকায় সেখানে ইকো সিস্টেম তৈরি হয়ে গেছে!",
    "তুই যদি মাইক্রোফোন হোস, তাহলে আমি অন। তুই চুপ করলে পৃথিবী শান্ত হয়!",
    "তোর চেয়ে গ্রুপের 'বট' বেশি কাজ করে রে ভাই!",
    "তুই নিজেকে হিরো ভাবিস, কিন্তু রিয়েলিটি চেক - তুই এক্সট্রা!"
]

async def generate_roast(attacker_name, target_name, user_message, old_messages):
    """প্রতিবার ভিন্ন রোস্ট জেনারেট করে"""
    
    memory_hint = ""
    if old_messages and len(old_messages) > 2:
        recent = old_messages[-6:]
        interesting = [m['text'] for m in recent if len(m['text']) > 5 and len(m['text']) < 100]
        if interesting:
            random.shuffle(interesting)
            memory_hint = f"\n\n{target_name} এর আগের কথা: {interesting[0]}"
    
    # র‍্যান্ডম টেম্পারেচার ব্যবহার করা হচ্ছে (0.9 থেকে 1.3 এর মধ্যে)
    random_temp = random.uniform(0.95, 1.25)
    
    prompt = f"""তুমি বাংলা স্যাভেজ রোস্টার। {attacker_name} {target_name} কে বলেছে: "{user_message}"{memory_hint}

{target_name} এর হয়ে {attacker_name} কে একটি তীক্ষ্ণ রোস্ট দাও।

নিয়ম:
- শুধু বিশুদ্ধ বাংলা
- ২ লাইনের বেশি না
- গালি দিবেনা
- শেষ লাইনে punchline থাকবে

এখন রোস্ট দাও:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "তুমি শুধু বাংলা উত্তর দেবে। প্রতিবার ভিন্ন ভিন্ন রোস্ট দেবে। তুমি মজার স্যাভেজ রোস্টার।"},
                {"role": "user", "content": prompt}
            ],
            temperature=random_temp,  # র‍্যান্ডম টেম্পারেচার
            max_tokens=150
        )
        roast = response.choices[0].message.content.strip()
        
        # চেক করা ইংরেজি/হিন্দি আছে কিনা
        english_chars = sum(1 for c in roast if ord(c) < 128 and c.isalpha())
        if english_chars > 15 or len(roast) < 10:
            return random.choice(FALLBACK_ROASTS)
        
        return roast
    except Exception as e:
        print(f"API Error: {e}")
        return random.choice(FALLBACK_ROASTS)

# কমান্ডগুলোর জন্য আলাদা রেসপন্স স্টোর
COMMAND_RESPONSES = {
    "repair_on": "🔧 রিপেয়ার মোড অন - বট বন্ধ আছে 🛑",
    "repair_off": "✅ রিপেয়ার মোড অফ - বট চালু আছে 🔥",
    "clear": "🗑️ সব মেমরি ডিলিট করা হয়েছে 🧹",
    "users": None,  # ডায়নামিক
    "status": None,  # ডায়নামিক
    "start": "🤖 **বাংলা স্যাভেজ রোস্ট বট**\n\nকে কাউকে কিছু বললেই বট রোস্ট দেবে!\n\n`/repair_on` - বট বন্ধ\n`/repair_off` - বট চালু\n`/clear` - ডাটা ডিলিট\n`/users` - ইউজার লিস্ট\n`/status` - স্ট্যাটাস দেখুন"
}

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
    
    if text.startswith('/'):
        return
    
    await save_message(sender.id, sender.first_name or sender.username or "কে যেন", text)
    
    if not is_targeting(text.lower()) and not m.reply_to_message:
        return
    
    # টার্গেট নির্ধারণ
    target = None
    if m.reply_to_message and m.reply_to_message.from_user:
        target = m.reply_to_message.from_user
    elif m.entities:
        for e in m.entities:
            if e.type == "text_mention":
                target = e.user
                break
    
    if not target:
        target = sender
    
    if target.id == context.bot.id:
        responses = [
            f"🫡 {sender.first_name}, বটের পিছনে না লেগে আগে নিজের দাগ দেখো!",
            f"😂 {sender.first_name}, বটকে রোস্ট করতে চাস? তুই আগে মানুষ হও!",
            f"🤡 {sender.first_name}, তোর চেয়ে বট ১০০ গুণ ভালো রোস্ট দিতে পারে!"
        ]
        await m.reply_text(random.choice(responses))
        return
    
    target_uid = str(target.id)
    old_msgs = memory["users"].get(target_uid, {}).get("messages", [])
    
    roast = await generate_roast(
        sender.first_name or sender.username or "কে যেন",
        target.first_name or target.username or "ওই ভাই",
        text,
        old_msgs
    )
    
    # এমোজি র‍্যান্ডম
    emoji = random.choice(['🎯', '🔥', '💀', '🤡', '😭', '😂', '🃏'])
    await m.reply_text(f"{emoji} {roast}")

# ========== কমান্ড হ্যান্ডলার ==========

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(COMMAND_RESPONSES["start"], parse_mode="Markdown")

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন!")
        return
    REPAIR_MODE = True
    await update.message.reply_text(COMMAND_RESPONSES["repair_on"])

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন!")
        return
    REPAIR_MODE = False
    await update.message.reply_text(COMMAND_RESPONSES["repair_off"])

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন!")
        return
    global memory
    memory = {"users": {}}
    save_memory(memory)
    await update.message.reply_text(COMMAND_RESPONSES["clear"])

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 এখনো কোনো ডাটা নেই")
        return
    lines = []
    for uid, data in list(memory["users"].items())[:15]:
        name = data.get("name", "নামবিহীন")
        msg_count = len(data.get("messages", []))
        lines.append(f"👤 {name} - {msg_count}টি")
    await update.message.reply_text("📋 ইউজার লিস্ট:\n" + "\n".join(lines))

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uc = len(memory["users"])
    mc = sum(len(u.get("messages", [])) for u in memory["users"].values())
    mode = "🔧 রিপেয়ার" if REPAIR_MODE else "✅ নরমাল"
    await update.message.reply_text(f"📊 স্ট্যাটাস\n👥 ইউজার: {uc}\n💬 মেসেজ: {mc}\n⚙️ মোড: {mode}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    
    print("✅ রোস্টার বট চালু (ভ্যারিয়েবল রোস্ট মোড)...")
    app.run_polling()

if __name__ == "__main__":
    main()
