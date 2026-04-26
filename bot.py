import os
import json
import random
import asyncio
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

def get_display_name(user):
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return "কে যেন"

async def save_message(uid, name, text):
    uid = str(uid)
    now = datetime.now().isoformat()
    
    if uid not in memory["users"]:
        memory["users"][uid] = {
            "name": name,
            "messages": [],
            "points": []
        }
    
    memory["users"][uid]["messages"].append({"text": text, "time": now})
    
    # সর্বশেষ 40 মেসেজ রাখবো
    if len(memory["users"][uid]["messages"]) > 40:
        memory["users"][uid]["messages"] = memory["users"][uid]["messages"][-40:]
    
    save_memory(memory)
    
    # ব্যাকগ্রাউন্ডে পয়েন্ট এক্সট্রাক্ট
    asyncio.create_task(extract_points(uid, name))

async def extract_points(uid, name):
    """ইউজারের মেসেজ থেকে পয়েন্ট বের করে সেভ করে"""
    user = memory["users"].get(str(uid))
    if not user or len(user.get("messages", [])) < 3:
        return
    
    messages = user["messages"][-15:]
    if len(messages) < 2:
        return
    
    msg_text = "\n".join([f"- {m['text'][:80]}" for m in messages])
    
    prompt = f"""'{name}' এর নিচের কথাগুলো বিশ্লেষণ করে তার ২-৩টি দুর্বলতা, ফাপরামি, বা মজার অভ্যাস বের কর।
প্রতিটি পয়েন্ট এক লাইনে, তীক্ষ্ণ এবং ব্যঙ্গাত্মক হবে।

{name} এর কথাবার্তা:
{msg_text}

পয়েন্টসমূহ:"""
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=200
        )
        points = response.choices[0].message.content.strip()
        
        if points and len(points) > 10:
            if "points" not in memory["users"][str(uid)]:
                memory["users"][str(uid)]["points"] = []
            memory["users"][str(uid)]["points"].append({
                "text": points,
                "time": datetime.now().isoformat()
            })
            # শেষ 10টি পয়েন্ট রাখবো
            if len(memory["users"][str(uid)]["points"]) > 10:
                memory["users"][str(uid)]["points"] = memory["users"][str(uid)]["points"][-10:]
            save_memory(memory)
    except:
        pass

def get_user_points(uid):
    """ইউজারের সেভ করা পয়েন্ট থেকে র‍্যান্ডম কয়েকটা নেয়"""
    user = memory["users"].get(str(uid))
    if not user:
        return None
    points = user.get("points", [])
    if not points:
        return None
    
    # সব পয়েন্টের টেক্সট নেওয়া
    point_texts = []
    for p in points:
        if isinstance(p, dict):
            point_texts.append(p.get("text", ""))
        else:
            point_texts.append(str(p))
    
    if not point_texts:
        return None
    
    # সর্বশেষ 5টি থেকে 1-2টা নেবে
    recent_points = point_texts[-5:]
    random.shuffle(recent_points)
    return recent_points[:2]  # 2টা পয়েন্ট নিবে

def is_targeting(text):
    """টার্গেটিং ডিটেক্ট করে"""
    targets = [
        'তুই', 'তোকে', 'তোর', 'তোরা', 'শালা', 'পাগলা', 'বোকা', 'গাধা',
        'ফাপর', 'বাজে', 'রে', 'নিয়া', 'নিয়ে', 'কথা', 'বলেন', 'বলো',
        'গাদা', 'পোলা', 'ভাই', 'কি বলছিস', 'কী বলছ', 'কে', 'কার',
        'monir', 'joni', 'alpha', 'mehedi', 'akta', 'gadha', 'niye', 'kichu',
        'bolen', 'faltu', 'bot', 'take', 'rost', 'kor', 'রে', 'মোনির', 'জনি'
    ]
    text_lower = text.lower()
    return any(t in text_lower for t in targets)

async def generate_roast(target_name, target_id, attacker_name, current_msg):
    """স্যাভেজ রোস্ট জেনারেট করে"""
    
    # টার্গেটের পুরনো পয়েন্ট
    points = get_user_points(target_id)
    points_text = ""
    if points:
        points_text = f"\n\n🎯 {target_name} এর আগের বিশ্লেষণে পাওয়া পয়েন্ট:\n" + "\n".join([f"   • {p}" for p in points])
    
    # টার্গেটের পুরনো কিছু মেসেজ (র‍্যান্ডম)
    target_data = memory["users"].get(str(target_id), {})
    old_msgs = target_data.get("messages", [])
    msg_hint = ""
    if old_msgs and len(old_msgs) > 2:
        random_msg = random.choice(old_msgs[-10:])
        msg_hint = f"\n\n📝 {target_name} এর আগের কথা: \"{random_msg['text'][:80]}\""
    
    # র‍্যান্ডম টেম্পারেচার (প্রতিবার ভিন্ন রোস্টের জন্য)
    random_temp = random.uniform(0.95, 1.3)
    
    prompt = f"""তুমি 'স্যাভেজ বাংলা রোস্ট বট'। {attacker_name} {target_name} কে টার্গেট করে বলেছে: "{current_msg}"{points_text}{msg_hint}

এখন {attacker_name} এর পরিবর্তে তুমি {target_name} কে উদ্দেশ্য করে একটি স্যাভেজ রোস্ট দাও।

নিয়ম কঠোরভাবে মেনে চলো:
1. শুধু বিশুদ্ধ বাংলা ভাষায় লিখতে হবে (কোনো ইংরেজি/হিন্দি/উর্দু নয়)
2. নাম ধরে সম্বোধন করতে হবে (যেমন: "শোন জনি", "ওহে মনির")
3. ২-৩ লাইনের বেশি হবে না
4. গালি দেওয়া যাবে না, কিন্তু তীক্ষ্ণ ব্যাঙ্গ করতে হবে
5. শেষ লাইনে একটি কিলার (মারাত্মক) punchline দিতে হবে
6. প্রতিবার ভিন্ন স্টাইলে, ভিন্নভাবে করতে হবে

উদাহরণ স্টাইল:
"শোন জনি কাকা, তোর কনফিডেন্স দেখে মনে হয় গ্রুপের সিইও, অথচ কাজের বেলায় তুই নেটওয়ার্কের বাইরে। তোর চেয়ে গ্রুপের বট বেশি কাজ করে!"

এখন তোর রোস্ট দে:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "তুমি শুধু বিশুদ্ধ বাংলা ভাষায় উত্তর দেবে। তুমি প্রতিবার ভিন্ন ভিন্ন স্যাভেজ রোস্ট দেবে। গালি দেবে না। তীক্ষ্ণ ব্যাঙ্গ করবে। শেষে punchline থাকবে।"},
                {"role": "user", "content": prompt}
            ],
            temperature=random_temp,
            max_tokens=180
        )
        roast = response.choices[0].message.content.strip()
        
        # ফিল্টার: ইংরেজি/হিন্দি চেক
        english_count = sum(1 for c in roast if ord(c) < 128 and c.isalpha())
        if english_count > 15 or len(roast) < 15:
            return generate_fallback_roast(target_name, attacker_name)
        
        return roast
    except Exception as e:
        print(f"API Error: {e}")
        return generate_fallback_roast(target_name, attacker_name)

def generate_fallback_roast(target_name, attacker_name):
    """API fail করলে ফলব্যাক রোস্ট (প্রতিবার ভিন্ন)"""
    fallbacks = [
        f"শোন {target_name}, তোর কনফিডেন্স দেখে মনে হয় গ্রুপের বাদশা, অথচ কাজের বেলায় তুই সবাইকে এড়িয়ে চলিস!",
        f"ওহে {target_name}, তুই এত ফাপর যে তোর কথা শুনলে গ্রুপের বটও তোকে মিউট করে দিতে চায়!",
        f"{target_name} রে, তোর বুদ্ধির চেয়ে তোর জুতার ফিতা বেশি কাজ করে!",
        f"শোন {target_name}, তুই হিরো ভাবিস, কিন্তু রিয়েলিটি চেক - তুই এক্সট্রা ক্যারেক্টার!",
        f"{target_name}, তোর চেয়ে গ্রুপের নোটিফিকেশন বেশি কাজে লাগে!",
        f"ওহে {target_name}, তোর মুখে যে কনফিডেন্স, সেটা দেখলে মনে হয় তুই বিশ্ব জয় করছিস - অথচ তুই পেন্ডিং কাজ শেষ করতে পারিস না!"
    ]
    return random.choice(fallbacks)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    
    if REPAIR_MODE:
        return
    
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat = msg.chat
    if chat.type not in ["group", "supergroup"]:
        return
    
    sender = msg.from_user
    text = msg.text
    
    # কমান্ড চেক
    if text.startswith('/'):
        return
    
    # মেসেজ সেভ
    await save_message(sender.id, get_display_name(sender), text)
    
    # টার্গেট চেক
    targeting = is_targeting(text.lower())
    is_reply = msg.reply_to_message is not None
    
    if not targeting and not is_reply:
        return
    
    # টার্গেট নির্ধারণ
    target = None
    
    if is_reply and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
    elif msg.entities:
        for entity in msg.entities:
            if entity.type == "text_mention":
                target = entity.user
                break
    
    # এখনো টার্গেট না পেলে সেন্ডারকেই ধরি (নিজেকে রোস্ট)
    if not target:
        target = sender
    
    # বট নিজেকে প্রোটেক্ট
    if target.id == context.bot.id:
        bot_responses = [
            f"🫡 {get_display_name(sender)}, বটের পিছনে না লেগে আগে নিজের দাগ দেখো!",
            f"😂 {get_display_name(sender)}, বটকে রোস্ট করতে চাস? তুই আগে মানুষ হও!",
            f"🤡 {get_display_name(sender)}, তোর চেয়ে বট ১০০ গুণ ভালো রোস্ট দিতে পারে!"
        ]
        await msg.reply_text(random.choice(bot_responses))
        return
    
    # রোস্ট জেনারেট
    roast = await generate_roast(
        get_display_name(target),
        target.id,
        get_display_name(sender),
        text
    )
    
    # র‍্যান্ডম এমোজি
    emoji = random.choice(['🎯', '🔥', '💀', '🤡', '😭', '😂', '🃏', '👑', '⚡', '💢'])
    
    await msg.reply_text(f"{emoji} {roast}")

# ========== কমান্ড ==========

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **স্যাভেজ রোস্ট বট**\n\n"
        "কে কাউকে কিছু বললেই বট চরম রোস্ট দেবে!\n\n"
        "**যেভাবে কাজ করে:**\n"
        "• কাউকে রিপ্লাই করে কিছু বলুন\n"
        "• 'তুই বোকা', 'গাধা' জাতীয় কিছু বলুন\n"
        "• বট সবাইয়ের কথা মনে রাখে এবং সেই অনুযায়ী রোস্ট দেয়\n\n"
        "**কমান্ড:**\n"
        "/repair_on - বট বন্ধ\n"
        "/repair_off - বট চালু\n"
        "/clear - সব ডাটা ডিলিট\n"
        "/users - ইউজার লিস্ট দেখুন\n"
        "/status - বট স্ট্যাটাস দেখুন\n"
        "/points @username - কারো পয়েন্ট দেখুন",
        parse_mode="Markdown"
    )

async def repair_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন!")
        return
    REPAIR_MODE = True
    await update.message.reply_text("🔴 **রিপেয়ার মোড অন** - বট বন্ধ আছে 🛑", parse_mode="Markdown")

async def repair_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REPAIR_MODE
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন!")
        return
    REPAIR_MODE = False
    await update.message.reply_text("🟢 **রিপেয়ার মোড অফ** - বট চালু আছে 🔥", parse_mode="Markdown")

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await update.effective_chat.get_administrators()
    if update.effective_user.id not in [a.user.id for a in admins]:
        await update.message.reply_text("👑 শুধু অ্যাডমিন পারবেন!")
        return
    global memory
    memory = {"users": {}}
    save_memory(memory)
    await update.message.reply_text("🗑️ **সব মেমরি ডিলিট করা হয়েছে** 🧹", parse_mode="Markdown")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory["users"]:
        await update.message.reply_text("📭 এখনো কোনো ইউজার ডাটা নেই")
        return
    
    lines = []
    for uid, data in list(memory["users"].items())[:20]:
        name = data.get("name", "নামবিহীন")
        msg_count = len(data.get("messages", []))
        point_count = len(data.get("points", []))
        lines.append(f"👤 **{name}** - {msg_count}টি মেসেজ, {point_count}টি পয়েন্ট")
    
    await update.message.reply_text("📋 **ইউজার লিস্ট:**\n\n" + "\n".join(lines), parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_count = len(memory["users"])
    msg_count = sum(len(u.get("messages", [])) for u in memory["users"].values())
    point_count = sum(len(u.get("points", [])) for u in memory["users"].values())
    mode = "🔧 রিপেয়ার" if REPAIR_MODE else "✅ নরমাল (সক্রিয়)"
    
    await update.message.reply_text(
        f"📊 **বট স্ট্যাটাস**\n\n"
        f"👥 মোট ইউজার: **{user_count}**\n"
        f"💬 সংরক্ষিত মেসেজ: **{msg_count}**\n"
        f"🎯 সংরক্ষিত পয়েন্ট: **{point_count}**\n"
        f"⚙️ বর্তমান মোড: {mode}\n"
        f"🕐 বট চালু: সক্রিয়",
        parse_mode="Markdown"
    )

async def points_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """কারো পয়েন্ট দেখানোর জন্য"""
    args = context.args
    if not args:
        await update.message.reply_text("ব্যবহার: `/points @username`", parse_mode="Markdown")
        return
    
    username = args[0].replace('@', '').lower()
    
    found_uid = None
    found_name = None
    for uid, data in memory["users"].items():
        name = data.get("name", "").lower()
        if username in name or (data.get("username") and username in data.get("username", "").lower()):
            found_uid = uid
            found_name = data.get("name")
            break
    
    if not found_uid:
        await update.message.reply_text(f"❌ `{username}` এর কোনো ডাটা পাওয়া যায়নি", parse_mode="Markdown")
        return
    
    points = get_user_points(found_uid)
    if not points:
        await update.message.reply_text(f"📭 `{found_name}` এর এখনো কোনো পয়েন্ট জমা হয়নি", parse_mode="Markdown")
        return
    
    points_text = "\n".join([f"• {p}" for p in points])
    await update.message.reply_text(
        f"🎯 **{found_name} এর দুর্বলতা/ফাপরামি পয়েন্ট:**\n\n{points_text}",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # কমান্ড হ্যান্ডলার
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("repair_on", repair_on))
    app.add_handler(CommandHandler("repair_off", repair_off))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("points", points_cmd))
    
    # মেসেজ হ্যান্ডলার
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 50)
    print("🔥 স্যাভেজ রোস্ট বট চালু হয়েছে 🔥")
    print("=" * 50)
    print("📌 ফিচারসমূহ:")
    print("   • কেউ কাউকে টার্গেট করলেই রোস্ট")
    print("   • প্রতিবার ভিন্ন ভিন্ন স্যাভেজ রোস্ট")
    print("   • পুরনো কথা থেকে পয়েন্ট বের করে সেভ")
    print("   • সেই পয়েন্ট ব্যবহার করে রোস্ট")
    print("   • সম্পূর্ণ বিশুদ্ধ বাংলা")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()
