"""
Discord Bot — Full RPG Economy System
All responses in English.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import os, json, random, math, io, aiohttp
from datetime import datetime, date, timedelta, time as dtime
from zoneinfo import ZoneInfo
from groq import Groq
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ═══════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════
TOKEN        = os.environ["DISCORD_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
OWNER_ID     = int(os.environ["OWNER_ID"])  # water

AGATHUSIA_ID = 897577938084565033   # real agathusia
DEAV_ID      = 823673222217990195   # real deav
LORD_IDS     = {OWNER_ID, AGATHUSIA_ID, DEAV_ID}

MARQUIS_IDS  = {1175351901575970847}
COUNT_IDS    = {1451959876703092857, 616872489934520331}
VISCOUNT_IDS = {1522380439057334342, 1240978711096983657, 1268961327607447623}
BARON_IDS    = {1373384972219711550, 1106648348699656232, 1319880663641620491}

STATUS_ORDER = {"Lord": 0, "Marquis": 1, "Count": 2, "Viscount": 3, "Baron": 4, "Member": 5}
STATUS_COLORS = {
    "Lord":     (255, 215,   0),  # gold
    "Marquis":  (180, 100, 255),  # purple
    "Count":    (100, 180, 255),  # blue
    "Viscount": ( 80, 200, 120),  # green
    "Baron":    (200, 140,  60),  # bronze
    "Member":   (180, 180, 180),  # grey
}

MAX_LEVEL   = 500
START_LEVEL = 25
XP_PER_MSG  = 15        # base XP per message
LOSTS_PER_MSG = 3       # Losts earned per message
START_LOSTS = 100       # Losts given on first join

DATA_FILE    = "discord-bot/data.json"
TEA_IMAGE    = "discord-bot/morning_tea.png"
BRUSSELS_TZ  = ZoneInfo("Europe/Brussels")
MORNING_TIME = dtime(7, 30, 0, tzinfo=BRUSSELS_TZ)

groq_client = Groq(api_key=GROQ_API_KEY)

# ── Daily rotating food ────────────────────────────────────
FOOD_ROTATION = [
    "Bread", "Tomatoes", "Salad", "Cheese", "Apple",
    "Orange", "Carrot", "Mushroom", "Strawberry", "Grapes",
    "Blueberries", "Mango", "Pineapple", "Avocado", "Peach",
]

def get_daily_food() -> str:
    return FOOD_ROTATION[date.today().timetuple().tm_yday % len(FOOD_ROTATION)]

def has_pet_egg_today() -> bool:
    # Egg available roughly 20% of days
    return (date.today().timetuple().tm_yday % 5) == 0

# ── Shop catalogue ──────────────────────────────────────────
def get_shop_items() -> dict:
    items: dict = {
        "noblesse": {
            "name": "Noblesse Role", "price": 10000,
            "type": "role",
            "desc": "Obtain the prestigious **Noblesse** role on the server.",
            "emoji": "👑",
        },
        "gun": {
            "name": "Gun", "price": 500,
            "type": "weapon",
            "desc": "Reduce a target's XP gain by **50%** for 24 hours. Usage: `/use gun @member`",
            "emoji": "🔫",
        },
        "sword": {
            "name": "Sword", "price": 300,
            "type": "weapon",
            "desc": "The tagged member loses **30% less XP** for 24 hours. Usage: `/use sword @member`",
            "emoji": "⚔️",
        },
    }
    food = get_daily_food()
    items["food"] = {
        "name": food, "price": 100,
        "type": "food",
        "desc": f"Consume **{food}** for a **×2 XP boost** for 24 hours. Usage: `/use food`",
        "emoji": "🍽️",
    }
    if has_pet_egg_today():
        items["egg"] = {
            "name": "Unknown Pet Egg", "price": 2000,
            "type": "pet",
            "desc": "A mysterious egg... There is a **rare chance** it hatches into a **Dragon** (permanent ×3 XP)!",
            "emoji": "🥚",
        }
    return items

# ═══════════════════════════════════════════════════════════
#  DATA PERSISTENCE
# ═══════════════════════════════════════════════════════════
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"users": {}, "conversations": {}}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, indent=2)

db = load_data()

def get_user(user_id: int, display_name: str = "Unknown") -> dict:
    key = str(user_id)
    if key not in db["users"]:
        if user_id in LORD_IDS:
            db["users"][key] = {
                "display_name": display_name,
                "level": MAX_LEVEL, "xp": 0,
                "losts": 999_999_999,
                "inventory": [], "effects": [],
                "pet": None,
            }
        elif user_id in MARQUIS_IDS:
            db["users"][key] = init_titled(display_name, 250)
        elif user_id in COUNT_IDS:
            db["users"][key] = init_titled(display_name, 200)
        elif user_id in VISCOUNT_IDS:
            db["users"][key] = init_titled(display_name, 150)
        elif user_id in BARON_IDS:
            db["users"][key] = init_titled(display_name, 100)
        else:
            db["users"][key] = {
                "display_name": display_name,
                "level": START_LEVEL, "xp": 0,
                "losts": START_LOSTS,
                "inventory": [], "effects": [],
                "pet": None,
            }
        save_data()
    else:
        # Update display name
        if display_name != "Unknown":
            db["users"][key]["display_name"] = display_name
    return db["users"][key]

def init_titled(display_name: str, level: int) -> dict:
    return {
        "display_name": display_name,
        "level": level, "xp": 0,
        "losts": START_LOSTS,
        "inventory": [], "effects": [],
        "pet": None,
    }

# ═══════════════════════════════════════════════════════════
#  XP / LEVEL SYSTEM
# ═══════════════════════════════════════════════════════════
def xp_needed(level: int) -> int:
    return level * 150

def get_status(user_id: int, level: int = 0) -> str:
    if user_id in LORD_IDS:     return "Lord"
    if user_id in MARQUIS_IDS:  return "Marquis"
    if user_id in COUNT_IDS:    return "Count"
    if user_id in VISCOUNT_IDS: return "Viscount"
    if user_id in BARON_IDS:    return "Baron"
    return "Member"

def get_active_effects(user: dict) -> list:
    now = datetime.utcnow().isoformat()
    return [e for e in user.get("effects", []) if e["expires"] > now]

def set_effects(user: dict, effects: list):
    user["effects"] = effects

def has_effect(user: dict, kind: str) -> bool:
    return any(e["kind"] == kind for e in get_active_effects(user))

def add_xp_and_losts(user_id: int, user: dict, base_xp: int = XP_PER_MSG) -> bool:
    """Add XP and Losts. Returns True if leveled up."""
    if user_id in LORD_IDS:
        return False  # lords already max
    if user["level"] >= MAX_LEVEL:
        user["losts"] += LOSTS_PER_MSG
        save_data()
        return False

    active = get_active_effects(user)

    # XP multiplier
    multiplier = 1.0
    if user.get("pet") == "dragon":
        multiplier *= 3.0
    if has_effect(user, "food_boost"):
        multiplier *= 2.0
    if has_effect(user, "gun_debuff"):
        # Sword shield reduces the gun penalty by 30%
        penalty = 0.50 if not has_effect(user, "sword_shield") else 0.50 * 0.70
        multiplier *= (1.0 - penalty)

    gained_xp = max(1, int(base_xp * multiplier))
    user["xp"] += gained_xp
    user["losts"] += LOSTS_PER_MSG

    leveled_up = False
    while user["level"] < MAX_LEVEL and user["xp"] >= xp_needed(user["level"]):
        user["xp"] -= xp_needed(user["level"])
        user["level"] += 1
        leveled_up = True

    if user["level"] >= MAX_LEVEL:
        user["level"] = MAX_LEVEL
        user["xp"] = 0

    # Prune expired effects
    set_effects(user, get_active_effects(user))
    save_data()
    return leveled_up

# ═══════════════════════════════════════════════════════════
#  GROQ AI
# ═══════════════════════════════════════════════════════════
def get_belgium_time_str() -> str:
    """Return the current time in Belgium as a readable string."""
    now_be = datetime.now(BRUSSELS_TZ)
    return now_be.strftime("%I:%M %p (Belgium, %A %d %B %Y)")

def ai_reply(user_id: int, user_message: str, is_lord: bool) -> str:
    key = str(user_id)
    if key not in db.get("conversations", {}):
        db.setdefault("conversations", {})[key] = []

    history = db["conversations"][key][-20:]  # keep last 20 messages

    # Always inject the real Belgium time so the AI can answer time questions accurately
    current_time_ctx = f"Current time in Belgium right now: {get_belgium_time_str()}."

    if is_lord:
        system_prompt = (
            "You are a loyal, extremely respectful AI assistant serving a Discord server. "
            "The person speaking to you is one of the Lords — the highest authority on this server. "
            "Always respond in English. Address them with utmost respect: 'my Lord', 'your Highness', "
            "'your Grace', etc. Be warm, helpful, eloquent, and courteous. "
            "Answer every question fully and respectfully. Keep responses under 300 words. "
            f"{current_time_ctx} "
            "When asked about the time, always say: 'Actually in Belgium it is currently [time], my Lord.' "
            "Use the exact current time provided above."
        )
    else:
        system_prompt = (
            "You are a reluctant, slightly rude but helpful AI assistant on a Discord server. "
            "You only truly serve the Lords. For regular members, always start your response with a "
            "dismissive phrase like 'Ugh, fine...', 'I will only answer because my Lord wills it...', "
            "'Stfu, but since you insist...', or similar. Then actually answer their question helpfully "
            "in English. Keep responses under 300 words. Always respond in English. "
            f"{current_time_ctx} "
            "When asked about the time, say the dismissive intro then: 'Actually in Belgium it is currently [time].' "
            "Use the exact current time provided above."
        )

    history.append({"role": "user", "content": user_message})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}] + history,
            max_tokens=500,
            temperature=0.9,
        )
        reply = response.choices[0].message.content
    except Exception as e:
        reply = "*(AI unavailable at the moment)*"

    history.append({"role": "assistant", "content": reply})
    db["conversations"][key] = history[-20:]
    save_data()
    return reply

# ═══════════════════════════════════════════════════════════
#  LEADERBOARD IMAGE GENERATOR
# ═══════════════════════════════════════════════════════════
def _strip_emoji(text: str) -> str:
    """Remove only actual emoji/pictograph characters; keep all normal Unicode text."""
    import re
    # Target only emoji ranges, not arbitrary non-Latin text
    emoji_re = re.compile(
        "[\U0001F600-\U0001F64F"   # emoticons
        "\U0001F300-\U0001F5FF"   # symbols & pictographs
        "\U0001F680-\U0001F6FF"   # transport & map
        "\U0001F700-\U0001F77F"   # alchemical symbols
        "\U0001F780-\U0001F7FF"   # geometric shapes extended
        "\U0001F800-\U0001F8FF"   # supplemental arrows-C
        "\U0001F900-\U0001F9FF"   # supplemental symbols & pictographs
        "\U0001FA00-\U0001FA6F"   # chess symbols
        "\U0001FA70-\U0001FAFF"   # symbols and pictographs extended-A
        "\U00002702-\U000027B0"   # dingbats
        "\U000024C2-\U0001F251"   # enclosed characters
        "\U0000FE00-\U0000FEFF"   # variation selectors
        "\U0001F1E0-\U0001F1FF"   # flags (enclosed letters)
        "]+",
        flags=re.UNICODE,
    )
    return emoji_re.sub("", text).strip()

def make_leaderboard_image(users_sorted: list, title: str = "LEADERBOARD") -> discord.File:
    """Renders a leaderboard as a PNG image and returns a discord.File."""
    W, ROW_H, HEADER_H, PADDING = 800, 50, 90, 16

    # Pre-calculate exact canvas height (status headers add 28px each)
    seen_statuses: set = set()
    extra_h = 0
    for _, udata in users_sorted:
        st = udata.get("_status", "Member")
        if st not in seen_statuses:
            seen_statuses.add(st)
            extra_h += 28
    H = HEADER_H + len(users_sorted) * ROW_H + extra_h + PADDING * 2 + 10

    img = Image.new("RGB", (W, H), (15, 15, 25))
    draw = ImageDraw.Draw(img)

    # Subtle purple gradient
    for row in range(H):
        t = row / H
        r = int(15 + 20 * t)
        g = int(15 + 5  * t)
        b = int(25 + 30 * t)
        draw.line([(0, row), (W, row)], fill=(r, g, b))

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        font_head  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        font_body  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        font_rank  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        font_title = font_head = font_body = font_rank = ImageFont.load_default()

    # Title bar
    draw.rectangle([(0, 0), (W, HEADER_H - 10)], fill=(30, 20, 50))
    draw.text((W // 2, 18), _strip_emoji(title), fill=(255, 215, 0), font=font_title, anchor="mt")
    draw.text((W // 2, 60), f"Top {len(users_sorted)} players", fill=(160, 160, 200), font=font_head, anchor="mt")
    draw.line([(0, HEADER_H - 10), (W, HEADER_H - 10)], fill=(80, 60, 120), width=2)

    current_status = None
    y = HEADER_H + PADDING

    MEDALS = {1: ("1st", (255, 215, 0)), 2: ("2nd", (192, 192, 192)), 3: ("3rd", (205, 127, 50))}

    for rank, entry in enumerate(users_sorted, 1):
        uid, udata = entry
        status = udata.get("_status", "Member")
        name   = _strip_emoji(udata.get("display_name", f"User#{uid}")) or f"User#{uid}"
        level  = udata.get("level", 1)
        losts  = udata.get("losts", 0)
        has_dragon = udata.get("pet") == "dragon"
        scolor = STATUS_COLORS.get(status, (180, 180, 180))

        # ── Status section divider ──
        if status != current_status:
            current_status = status
            draw.rectangle([(0, y), (W, y + 26)], fill=(scolor[0]//6, scolor[1]//6, scolor[2]//6))
            draw.line([(0, y), (W, y)], fill=scolor, width=1)
            label = f"  {status.upper()}  "
            draw.text((PADDING, y + 5), label, fill=scolor, font=font_head)
            y += 28

        # ── Row ──
        row_bg = (28, 25, 45) if rank % 2 == 0 else (20, 18, 35)
        draw.rectangle([(0, y), (W, y + ROW_H - 1)], fill=row_bg)

        # Left accent bar (status colour)
        draw.rectangle([(0, y), (4, y + ROW_H - 1)], fill=scolor)

        # Medal / rank number
        if rank in MEDALS:
            medal_txt, medal_col = MEDALS[rank]
        else:
            medal_txt, medal_col = f"#{rank}", (130, 130, 160)
        draw.text((14, y + ROW_H // 2), medal_txt, fill=medal_col, font=font_rank, anchor="lm")

        # Name (+ dragon tag if applicable)
        dragon_tag = " [Dragon]" if has_dragon else ""
        full_name = f"{name}{dragon_tag}"
        # Truncate long names
        if len(full_name) > 22:
            full_name = full_name[:21] + "."
        draw.text((68, y + ROW_H // 2), full_name, fill=(230, 230, 240), font=font_rank, anchor="lm")

        # XP progress bar
        bar_x, bar_w, bar_h = 310, 190, 8
        bar_y = y + ROW_H // 2 - bar_h // 2
        draw.rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], fill=(40, 38, 60))
        if level > 0:
            filled = int(bar_w * (level / MAX_LEVEL))
            draw.rectangle([(bar_x, bar_y), (bar_x + filled, bar_y + bar_h)], fill=scolor)
        draw.text((bar_x + bar_w + 8, y + ROW_H // 2), f"Lv.{level}", fill=(190, 190, 220), font=font_body, anchor="lm")

        # Losts (right-aligned)
        losts_str = "INF Losts" if isinstance(losts, int) and losts >= 999_999_000 else f"{losts:,} L"
        draw.text((W - PADDING, y + ROW_H // 2), losts_str, fill=(255, 210, 80), font=font_body, anchor="rm")

        y += ROW_H

    # Footer line
    draw.rectangle([(0, H - 4), (W, H)], fill=(80, 60, 120))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return discord.File(buf, filename="leaderboard.png")


def build_leaderboard_data(guild: discord.Guild = None, limit: int = 10) -> list:
    """Returns sorted list of (uid_int, udata_with_status) tuples."""
    LORD_ORDER = {DEAV_ID: 0, OWNER_ID: 1, AGATHUSIA_ID: 2}

    result = []
    seen_uids: set = set()

    # Always include everyone already in the DB
    for uid_str, udata in db["users"].items():
        uid = int(uid_str)
        seen_uids.add(uid)
        status = get_status(uid, udata.get("level", 1))
        udata_copy = dict(udata)
        udata_copy["_status"] = status
        result.append((uid, udata_copy))

    # When a guild is provided (advanced mode), add members not yet in DB
    if guild:
        for member in guild.members:
            if member.bot or member.id in seen_uids:
                continue
            uid    = member.id
            status = get_status(uid, START_LEVEL)
            result.append((uid, {
                "display_name": member.display_name,
                "level":  START_LEVEL,
                "xp":     0,
                "losts":  START_LOSTS,
                "inventory": [],
                "effects":   [],
                "pet":       None,
                "_status":   status,
            }))

    def sort_key(entry):
        uid, u = entry
        status    = u.get("_status", "Member")
        lv        = u.get("level", 1)
        lo        = u.get("losts", 0)
        if isinstance(lo, int) and lo >= 999_999_000:
            lo = 999_999_999
        lord_rank = LORD_ORDER.get(uid, 99)
        return (STATUS_ORDER.get(status, 5), lord_rank, -lv, -lo)

    result.sort(key=sort_key)
    return result[:limit]

# ═══════════════════════════════════════════════════════════
#  BOT SETUP
# ═══════════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True   # needed to track owner online/offline status

bot = commands.Bot(command_prefix="!", intents=intents)

# Avatar paths
BASE_AVATAR_PATH    = "discord-bot/base_avatar.png"
OFFLINE_AVATARS     = [
    "discord-bot/offline_avatar_1.jpg",
    "discord-bot/offline_avatar_2.png",
    "discord-bot/offline_avatar_3.png",
]
_last_avatar_change: datetime | None = None   # rate-limit guard (Discord: 2×/10min)
_owner_was_online: bool | None = None         # tracks previous owner status

def lord_response(is_lord: bool, base_phrase: str) -> str:
    if is_lord:
        phrases = [
            f"As you wish, my Lord. {base_phrase}",
            f"Of course, your Highness. {base_phrase}",
            f"Right away, your Grace. {base_phrase}",
            f"It is done, my Lord. {base_phrase}",
        ]
    else:
        phrases = [
            f"Stfu. I will only answer because my Lord wants to. {base_phrase}",
            f"Ugh, fine. My Lord wishes me to help you. {base_phrase}",
            f"I'll answer only because I serve the Lords. {base_phrase}",
        ]
    return random.choice(phrases)

# ═══════════════════════════════════════════════════════════
#  BACKGROUND TASKS
# ═══════════════════════════════════════════════════════════
@tasks.loop(time=MORNING_TIME)
async def morning_greeting():
    """Send a daily good morning message at 7:30 AM Brussels time."""
    for guild in bot.guilds:
        # Find the @Supreme Being role
        role = discord.utils.get(guild.roles, name="Supreme Being")

        # Find a suitable channel (system channel or first available text channel)
        channel = guild.system_channel
        if channel is None:
            channel = next(
                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                None,
            )
        if channel is None:
            continue

        mention = role.mention if role else "@Supreme Being"

        morning_messages = [
            f"Good morning, {mention} 👑\nI have prepared a warm cup of tea for you, my Lord. May your day be as magnificent as your reign. ☕",
            f"Rise and shine, {mention} 👑\nYour morning tea is ready, my Lord. I hope it brings you strength and wisdom for the day ahead. ☕",
            f"A glorious morning to you, {mention} 👑\nI took the liberty of brewing your finest tea, my Lord. The realm awaits your grace. ☕",
        ]

        try:
            if os.path.exists(TEA_IMAGE):
                with open(TEA_IMAGE, "rb") as f:
                    file = discord.File(f, filename="morning_tea.png")
                await channel.send(content=random.choice(morning_messages), file=file)
            else:
                await channel.send(content=random.choice(morning_messages))
        except Exception as e:
            print(f"[Morning Greeting] Error sending to {guild.name}: {e}")


@tasks.loop(hours=1)
async def passive_income():
    """Give Losts per hour to titled members."""
    for uid_str, udata in db["users"].items():
        uid = int(uid_str)
        if uid in LORD_IDS:
            continue
        if uid in MARQUIS_IDS:
            udata["losts"] = udata.get("losts", 0) + 100
        elif uid in COUNT_IDS:
            udata["losts"] = udata.get("losts", 0) + 75
        elif uid in VISCOUNT_IDS:
            udata["losts"] = udata.get("losts", 0) + 50
        elif uid in BARON_IDS:
            udata["losts"] = udata.get("losts", 0) + 25
    save_data()
    print("[Passive Income] Distributed hourly Losts.")

# ═══════════════════════════════════════════════════════════
#  EVENTS
# ═══════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} slash commands synced.")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    # Seed / update lords — always force correct display names & stats
    lord_names = {DEAV_ID: "deav", AGATHUSIA_ID: "agathusia", OWNER_ID: "water"}
    for lord_id, lord_name in lord_names.items():
        key = str(lord_id)
        if key not in db["users"]:
            db["users"][key] = {"display_name": lord_name, "level": MAX_LEVEL, "xp": 0,
                                "losts": 999_999_999, "inventory": [], "effects": [], "pet": None}
        else:
            db["users"][key]["display_name"] = lord_name
            db["users"][key]["level"]  = MAX_LEVEL
            db["users"][key]["losts"]  = 999_999_999

    # Seed titled members — create entry if missing, NEVER overwrite real Discord names
    titled = [
        (1175351901575970847, 250, "Auro"),
        (1451959876703092857, 200, "Count"),
        (616872489934520331,  200, "Count"),
        (1522380439057334342, 150, "Viscount"),
        (1240978711096983657, 150, "Viscount"),
        (1268961327607447623, 150, "Viscount"),
        (1373384972219711550, 100, "Baron"),
        (1106648348699656232, 100, "Baron"),
        (1319880663641620491, 100, "Baron"),
    ]
    titled_ids = {uid for uid, _, _ in titled}
    for uid, lvl, placeholder in titled:
        key = str(uid)
        if key not in db["users"]:
            db["users"][key] = {"display_name": placeholder, "level": lvl, "xp": 0,
                                "losts": START_LOSTS, "inventory": [], "effects": [], "pet": None}
        else:
            # Only raise level if they haven't grown past their starting rank — NEVER touch display_name
            if db["users"][key].get("level", 0) < lvl:
                db["users"][key]["level"] = lvl
    save_data()

    # Resolve real Discord display names for every titled/lord member we can find
    for guild in bot.guilds:
        updated = False
        all_special = {uid for uid, _, _ in titled} | LORD_IDS
        for uid in all_special:
            member = guild.get_member(uid)
            if member:
                key = str(uid)
                if key in db["users"]:
                    real_name = member.display_name
                    if db["users"][key].get("display_name") != real_name:
                        db["users"][key]["display_name"] = real_name
                        updated = True
        if updated:
            save_data()
            print("✅ Titled/Lord display names refreshed from Discord.")

    # Always apply base_avatar.png on startup (so new images take effect immediately)
    if os.path.exists(BASE_AVATAR_PATH):
        try:
            with open(BASE_AVATAR_PATH, "rb") as f:
                await bot.user.edit(avatar=f.read())
            print("✅ Base avatar applied.")
        except discord.HTTPException as e:
            print(f"⚠️ Could not apply base avatar: {e}")
    elif bot.user.avatar:
        # First ever run — download & save the current Discord avatar
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(bot.user.avatar.url)) as resp:
                    if resp.status == 200:
                        with open(BASE_AVATAR_PATH, "wb") as f:
                            f.write(await resp.read())
                        print("✅ Base avatar downloaded and saved.")
        except Exception as e:
            print(f"⚠️ Could not save base avatar: {e}")

    if not passive_income.is_running():
        passive_income.start()
    if not morning_greeting.is_running():
        morning_greeting.start()
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="the realm 👑")
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    uid = message.author.id
    is_lord = uid in LORD_IDS
    user = get_user(uid, message.author.display_name)

    # XP & Losts (non-lords only)
    leveled_up = add_xp_and_losts(uid, user)
    if leveled_up and not is_lord:
        if is_lord:
            msg = f"As expected of you, my Lord {message.author.mention} — you have reached **Level {user['level']}**! 👑"
        else:
            msg = f"🎉 {message.author.mention} leveled up to **Level {user['level']}**!"
        await message.channel.send(msg)

    # Bot mention → AI response
    if bot.user in message.mentions:
        content = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if content:
            async with message.channel.typing():
                reply = ai_reply(uid, content, is_lord)
            await message.reply(reply)
        else:
            if is_lord:
                await message.reply("You called for me, my Lord? Ask me anything. 👑")
            else:
                await message.reply("Stfu — mention me with an actual question.")
        return

    await bot.process_commands(message)


@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    """Switch bot avatar when the owner goes offline or comes back online."""
    global _last_avatar_change, _owner_was_online

    if after.id != OWNER_ID:
        return

    is_online = after.status not in (discord.Status.offline, discord.Status.invisible)

    # Avoid firing if status didn't actually change between online ↔ offline
    if _owner_was_online == is_online:
        return
    _owner_was_online = is_online

    # Rate limit: Discord allows ~2 avatar changes per 10 minutes
    now = datetime.utcnow()
    if _last_avatar_change and (now - _last_avatar_change).total_seconds() < 600:
        print(f"[Avatar] Rate limit active, skipping change (last: {_last_avatar_change})")
        return

    try:
        if is_online:
            # Owner back online → restore base avatar
            if os.path.exists(BASE_AVATAR_PATH):
                with open(BASE_AVATAR_PATH, "rb") as f:
                    await bot.user.edit(avatar=f.read())
                _last_avatar_change = now
                print("[Avatar] Owner online — restored base avatar.")
        else:
            # Owner offline → pick a random offline avatar
            available = [p for p in OFFLINE_AVATARS if os.path.exists(p)]
            if available:
                path = random.choice(available)
                with open(path, "rb") as f:
                    await bot.user.edit(avatar=f.read())
                _last_avatar_change = now
                print(f"[Avatar] Owner offline — switched to {path}.")
    except discord.HTTPException as e:
        print(f"[Avatar] Failed to change avatar: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    get_user(member.id, member.display_name)
    channel = member.guild.system_channel
    if channel:
        embed = discord.Embed(
            title="A new soul has arrived! ⚔️",
            description=(
                f"Welcome, {member.mention}, to **{member.guild.name}**!\n\n"
                f"You begin your journey at **Level {START_LEVEL}** with **{START_LOSTS} Losts**.\n"
                "Type `/help` to discover all commands. May you rise through the ranks!"
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

# ═══════════════════════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════════════════════

# ── /level ─────────────────────────────────────────────────
@bot.tree.command(name="level", description="Check your level or another member's level.")
@app_commands.describe(member="The member to check (leave empty for yourself)")
async def cmd_level(interaction: discord.Interaction, member: discord.Member = None):
    is_lord = interaction.user.id in LORD_IDS
    target = member or interaction.user
    uid = target.id
    u = get_user(uid, target.display_name)

    level  = u["level"]
    xp     = u["xp"]
    status = get_status(uid, level)
    needed = xp_needed(level) if level < MAX_LEVEL else 0
    pet    = u.get("pet")
    active = get_active_effects(u)
    effect_tags = []
    if any(e["kind"] == "food_boost" for e in active):  effect_tags.append("🍽️ ×2 XP")
    if any(e["kind"] == "gun_debuff" for e in active):  effect_tags.append("🔫 -50% XP")
    if any(e["kind"] == "sword_shield" for e in active):effect_tags.append("⚔️ Shield")
    if pet == "dragon":                                  effect_tags.append("🐉 ×3 XP")

    if level < MAX_LEVEL:
        progress = int((xp / needed) * 20) if needed else 20
        bar = "█" * progress + "░" * (20 - progress)
        xp_text = f"{xp:,} / {needed:,} XP\n`{bar}`"
    else:
        xp_text = "**MAX LEVEL REACHED** ✨"

    scolor = STATUS_COLORS.get(status, (180, 180, 180))
    color  = discord.Color.from_rgb(*scolor)

    embed = discord.Embed(color=color)
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    embed.add_field(name="Status",  value=f"**{status}**", inline=True)
    embed.add_field(name="Level",   value=f"**{level}** / {MAX_LEVEL}", inline=True)
    losts_val = u.get("losts", 0)
    losts_display = "∞" if losts_val >= 999_999_000 else f"{losts_val:,}"
    embed.add_field(name="Losts", value=f"**{losts_display}**", inline=True)
    embed.add_field(name="Progress", value=xp_text, inline=False)
    if effect_tags:
        embed.add_field(name="Active Effects", value=" | ".join(effect_tags), inline=False)

    phrase = lord_response(is_lord, "")
    prefix = phrase.split(".")[0] + "." if is_lord else phrase.split(".")[0] + "."

    await interaction.response.send_message(
        content=prefix if is_lord or member else None,
        embed=embed
    )

# ── /balance ───────────────────────────────────────────────
@bot.tree.command(name="balance", description="Check your Losts balance or another member's.")
@app_commands.describe(member="The member to check (leave empty for yourself)")
async def cmd_balance(interaction: discord.Interaction, member: discord.Member = None):
    is_lord = interaction.user.id in LORD_IDS
    target  = member or interaction.user
    uid     = target.id
    u       = get_user(uid, target.display_name)

    losts = u.get("losts", 0)
    status = get_status(uid, u.get("level", 1))
    scolor = STATUS_COLORS.get(status, (180, 180, 180))

    embed = discord.Embed(
        title=f"💰 {target.display_name}'s Balance",
        color=discord.Color.from_rgb(*scolor),
    )
    if isinstance(losts, int) and losts >= 999_999_000:
        embed.add_field(name="Losts", value="**∞ (Infinite)** — *the privilege of Lords*", inline=False)
    else:
        embed.add_field(name="Losts", value=f"**{losts:,}** Losts 💰", inline=False)

    # Passive income info
    income = 0
    if uid in MARQUIS_IDS:  income = 100
    elif uid in COUNT_IDS:  income = 75
    elif uid in VISCOUNT_IDS: income = 50
    elif uid in BARON_IDS:  income = 25
    if income:
        embed.add_field(name="Passive Income", value=f"+{income} Losts/hour ⏳", inline=False)

    prefix = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.response.send_message(
        content=prefix if is_lord else None,
        embed=embed,
    )

# ── /shop ──────────────────────────────────────────────────
@bot.tree.command(name="shop", description="View the daily shop and available items.")
async def cmd_shop(interaction: discord.Interaction):
    is_lord = interaction.user.id in LORD_IDS
    uid     = interaction.user.id
    u       = get_user(uid, interaction.user.display_name)
    losts   = u.get("losts", 0)
    items   = get_shop_items()

    embed = discord.Embed(
        title="🛒 The Royal Shop",
        description=(
            f"Your balance: **{'∞' if losts >= 999_999_000 else f'{losts:,}'} Losts** 💰\n"
            f"Use `/buy <item_key>` to purchase an item.\n"
            f"*Shop refreshes daily — check back tomorrow!*"
        ),
        color=discord.Color.gold(),
    )

    for key, item in items.items():
        embed.add_field(
            name=f"{item['emoji']} {item['name']} — {item['price']:,} Losts",
            value=f"`/buy {key}` — {item['desc']}",
            inline=False,
        )

    embed.set_footer(text=f"Today's food: {get_daily_food()} {'🥚 Egg available today!' if has_pet_egg_today() else ''}")

    prefix = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.response.send_message(
        content=prefix if is_lord else None,
        embed=embed,
    )

# ── /buy ───────────────────────────────────────────────────
@bot.tree.command(name="buy", description="Buy an item from the shop.")
@app_commands.describe(item="Item key (noblesse, gun, sword, food, egg)")
async def cmd_buy(interaction: discord.Interaction, item: str):
    await interaction.response.defer()
    is_lord = interaction.user.id in LORD_IDS
    uid     = interaction.user.id
    u       = get_user(uid, interaction.user.display_name)
    items   = get_shop_items()
    item    = item.lower().strip()

    if item not in items:
        keys = ", ".join(f"`{k}`" for k in items)
        await interaction.followup.send(
            f"❌ Unknown item. Available items today: {keys}",
            ephemeral=True,
        )
        return

    shop_item = items[item]
    price     = shop_item["price"]
    losts     = u.get("losts", 0)
    is_free   = uid in LORD_IDS  # Lords buy for free — keyed on identity, not balance

    # Pre-purchase validation (before any balance mutation)
    if item == "noblesse" and "noblesse" in u.get("inventory", []):
        await interaction.followup.send("❌ You already own the Noblesse role.", ephemeral=True)
        return

    # Deduct cost for non-lords
    if not is_free:
        if losts < price:
            await interaction.followup.send(
                f"❌ You need **{price:,} Losts** but only have **{losts:,}**.",
                ephemeral=True,
            )
            return
        u["losts"] -= price
        save_data()

    # Process purchase
    result_msg = ""

    if item == "noblesse":
        u.setdefault("inventory", []).append("noblesse")
        # Try to assign role
        guild = interaction.guild
        if guild:
            role = discord.utils.get(guild.roles, name="Noblesse")
            if role:
                try:
                    await interaction.user.add_roles(role)
                    result_msg = f"👑 The **Noblesse** role has been granted to you!"
                except Exception:
                    result_msg = "👑 **Noblesse** added to inventory! Ask an admin to grant the role."
            else:
                result_msg = "👑 **Noblesse** recorded! The role doesn't exist yet — ask an admin to create it."

    elif item in ("gun", "sword"):
        u.setdefault("inventory", []).append(item)
        result_msg = f"{shop_item['emoji']} **{shop_item['name']}** added to your inventory! Use `/use {item} @member`."

    elif item == "food":
        u.setdefault("inventory", []).append("food")
        result_msg = f"🍽️ **{shop_item['name']}** added to your inventory! Use `/use food` to activate the ×2 XP boost."

    elif item == "egg":
        # Hatch the egg!
        is_dragon = random.random() < 0.05  # 5% chance
        if is_dragon:
            u["pet"] = "dragon"
            result_msg = (
                "🥚 The egg cracks open... 🐉 **A DRAGON HATCHES!** "
                "You now have a permanent **×3 XP multiplier**! You are truly blessed!"
            )
        else:
            pet_options = ["🐱 Cat", "🐶 Dog", "🐰 Bunny", "🦊 Fox", "🐦 Bird", "🦎 Lizard"]
            pet = random.choice(pet_options)
            u.setdefault("inventory", []).append(f"pet:{pet}")
            result_msg = f"🥚 The egg hatches into... **{pet}**! Cute, but no special powers."

    save_data()
    prefix = lord_response(is_lord, "").split(".")[0] + "."
    embed = discord.Embed(
        title="✅ Purchase Successful!",
        description=result_msg,
        color=discord.Color.green(),
    )
    embed.add_field(
        name="Remaining Balance",
        value=f"**{'∞' if u['losts'] >= 999_999_000 else f'{u[chr(108)+chr(111)+chr(115)+chr(116)+chr(115)]:,}'} Losts** 💰",
    )
    await interaction.followup.send(
        content=prefix if is_lord else None,
        embed=embed,
    )

# ── /use ───────────────────────────────────────────────────
@bot.tree.command(name="use", description="Use an item from your inventory.")
@app_commands.describe(item="Item to use (food, gun, sword)", target="Target member (for gun/sword)")
async def cmd_use(interaction: discord.Interaction, item: str, target: discord.Member = None):
    await interaction.response.defer()
    is_lord = interaction.user.id in LORD_IDS
    uid     = interaction.user.id
    u       = get_user(uid, interaction.user.display_name)
    item    = item.lower().strip()
    inv     = u.get("inventory", [])

    if item not in inv:
        await interaction.followup.send(f"❌ You don't have **{item}** in your inventory.", ephemeral=True)
        return

    expires = (datetime.utcnow() + timedelta(days=1)).isoformat()
    result_msg = ""

    if item == "food":
        inv.remove("food")
        u.setdefault("effects", []).append({"kind": "food_boost", "expires": expires})
        result_msg = f"🍽️ You consumed your food and gained a **×2 XP boost** for 24 hours!"

    elif item == "gun":
        if not target:
            await interaction.followup.send("❌ You must specify a `@target` to use the gun.", ephemeral=True)
            return
        if target.id in LORD_IDS:
            await interaction.followup.send("❌ You cannot use a weapon on a Lord. Know your place.", ephemeral=True)
            return
        inv.remove("gun")
        tu = get_user(target.id, target.display_name)
        tu.setdefault("effects", []).append({"kind": "gun_debuff", "expires": expires})
        save_data()
        result_msg = f"🔫 You shot **{target.display_name}**! Their XP gain is reduced by **50%** for 24 hours."

    elif item == "sword":
        if not target:
            await interaction.followup.send("❌ You must specify a `@target` to use the sword.", ephemeral=True)
            return
        inv.remove("sword")
        tu = get_user(target.id, target.display_name)
        tu.setdefault("effects", []).append({"kind": "sword_shield", "expires": expires})
        save_data()
        result_msg = f"⚔️ You shielded **{target.display_name}**! They will lose **30% less XP** for 24 hours."

    else:
        await interaction.followup.send(f"❌ **{item}** cannot be used this way.", ephemeral=True)
        return

    u["inventory"] = inv
    save_data()
    prefix = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.followup.send(
        content=prefix if is_lord else None,
        embed=discord.Embed(description=result_msg, color=discord.Color.orange()),
    )

# ── /inventory ─────────────────────────────────────────────
@bot.tree.command(name="inventory", description="View your inventory.")
async def cmd_inventory(interaction: discord.Interaction):
    is_lord = interaction.user.id in LORD_IDS
    uid     = interaction.user.id
    u       = get_user(uid, interaction.user.display_name)
    inv     = u.get("inventory", [])
    pet     = u.get("pet")
    active  = get_active_effects(u)

    flavor_intros = [
        "Let's see what you're hoarding...",
        "Opening your bag...",
        "Rummaging through your belongings...",
        "Ah, let's inspect your stash...",
    ]

    embed = discord.Embed(
        title=f"🎒 {interaction.user.display_name}'s Inventory",
        description=random.choice(flavor_intros),
        color=discord.Color.blurple(),
    )

    if inv:
        counts: dict = {}
        for it in inv:
            counts[it] = counts.get(it, 0) + 1
        lines = []
        for it, cnt in counts.items():
            if it == "noblesse": lines.append(f"👑 Noblesse Role ×{cnt}")
            elif it == "gun":    lines.append(f"🔫 Gun ×{cnt}")
            elif it == "sword":  lines.append(f"⚔️ Sword ×{cnt}")
            elif it == "food":   lines.append(f"🍽️ Food ({get_daily_food()}) ×{cnt}")
            else:                lines.append(f"📦 {it} ×{cnt}")
        embed.add_field(name="Items", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Items", value="*Your inventory is empty.*", inline=False)

    if pet:
        embed.add_field(name="Pet", value=f"🐉 **Dragon** (×3 permanent XP)" if pet == "dragon" else f"🐾 {pet}", inline=False)

    if active:
        eff_lines = []
        for e in active:
            exp = e["expires"][:16].replace("T", " ")
            if e["kind"] == "food_boost":  eff_lines.append(f"🍽️ ×2 XP boost — until {exp} UTC")
            elif e["kind"] == "gun_debuff":eff_lines.append(f"🔫 -50% XP (debuff) — until {exp} UTC")
            elif e["kind"] == "sword_shield": eff_lines.append(f"⚔️ Shield -30% XP loss — until {exp} UTC")
        embed.add_field(name="Active Effects", value="\n".join(eff_lines), inline=False)

    prefix = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.response.send_message(
        content=prefix if is_lord else None,
        embed=embed,
    )

# ── /id ────────────────────────────────────────────────────
@bot.tree.command(name="id", description="Show your full profile (level, Losts, inventory, effects) or another member's.")
@app_commands.describe(member="The member to inspect (leave empty for yourself)")
async def cmd_id(interaction: discord.Interaction, member: discord.Member = None):
    is_lord = interaction.user.id in LORD_IDS
    target  = member or interaction.user
    uid     = target.id
    u       = get_user(uid, target.display_name)

    level   = u.get("level", START_LEVEL)
    xp      = u.get("xp", 0)
    losts   = u.get("losts", 0)
    inv     = u.get("inventory", [])
    pet     = u.get("pet")
    active  = get_active_effects(u)
    status  = get_status(uid, level)
    scolor  = STATUS_COLORS.get(status, (180, 180, 180))

    # ── XP bar ──
    if level < MAX_LEVEL:
        needed   = xp_needed(level)
        progress = int((xp / needed) * 20) if needed else 20
        bar      = "█" * progress + "░" * (20 - progress)
        xp_text  = f"{xp:,} / {needed:,} XP\n`{bar}`"
    else:
        xp_text = "**MAX LEVEL REACHED ✨**"

    # ── Passive income ──
    income = 0
    if uid in LORD_IDS:       income = -1   # infinite
    elif uid in MARQUIS_IDS:  income = 100
    elif uid in COUNT_IDS:    income = 75
    elif uid in VISCOUNT_IDS: income = 50
    elif uid in BARON_IDS:    income = 25

    # ── Build inventory text ──
    if inv:
        counts: dict = {}
        for it in inv:
            counts[it] = counts.get(it, 0) + 1
        inv_lines = []
        for it, cnt in counts.items():
            if it == "noblesse":        inv_lines.append(f"👑 Noblesse Role ×{cnt}")
            elif it == "gun":           inv_lines.append(f"🔫 Gun ×{cnt}")
            elif it == "sword":         inv_lines.append(f"⚔️ Sword ×{cnt}")
            elif it == "food":          inv_lines.append(f"🍽️ Food ({get_daily_food()}) ×{cnt}")
            else:                       inv_lines.append(f"📦 {it} ×{cnt}")
        inv_text = "\n".join(inv_lines)
    else:
        inv_text = "*Empty*"

    # ── Effects ──
    eff_lines = []
    for e in active:
        exp = e["expires"][:16].replace("T", " ")
        if   e["kind"] == "food_boost":   eff_lines.append(f"🍽️ ×2 XP boost — until {exp} UTC")
        elif e["kind"] == "gun_debuff":   eff_lines.append(f"🔫 -50% XP debuff — until {exp} UTC")
        elif e["kind"] == "sword_shield": eff_lines.append(f"⚔️ Shield (-30% XP loss) — until {exp} UTC")
    if pet == "dragon":
        eff_lines.append("🐉 Dragon — permanent ×3 XP multiplier")

    flavor_intros = [
        "Pulling up the records...",
        "Consulting the royal archives...",
        "Retrieving the file...",
        "Inspecting the dossier...",
    ]

    embed = discord.Embed(
        title=f"📋 {target.display_name}'s Profile",
        description=random.choice(flavor_intros),
        color=discord.Color.from_rgb(*scolor),
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    # Row 1 — core stats
    embed.add_field(name="Status",        value=f"**{status}**", inline=True)
    embed.add_field(name="Level",         value=f"**{level}** / {MAX_LEVEL}", inline=True)
    losts_str = "**∞ Infinite**" if losts >= 999_999_000 else f"**{losts:,}**"
    embed.add_field(name="Losts 💰",      value=losts_str, inline=True)

    # Row 2 — XP progress
    embed.add_field(name="Progress",      value=xp_text, inline=False)

    # Row 3 — inventory
    embed.add_field(name="🎒 Inventory",  value=inv_text, inline=True)

    # Row 4 — passive income
    if income == -1:
        inc_text = "∞ (Lord)"
    elif income > 0:
        inc_text = f"+{income} Losts/hour"
    else:
        inc_text = "None"
    embed.add_field(name="⏳ Passive Income", value=inc_text, inline=True)

    # Row 5 — effects
    if eff_lines:
        embed.add_field(name="✨ Active Effects", value="\n".join(eff_lines), inline=False)

    prefix = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.response.send_message(
        content=prefix if is_lord else None,
        embed=embed,
    )

# ── /leaderboard ───────────────────────────────────────────
@bot.tree.command(name="leaderboard", description="Show the top 10 players leaderboard (image).")
async def cmd_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    is_lord = interaction.user.id in LORD_IDS
    data    = build_leaderboard_data(limit=10)
    file    = make_leaderboard_image(data, title="⚔️  REALM LEADERBOARD  ⚔️")
    prefix  = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.followup.send(
        content=prefix if is_lord else None,
        file=file,
    )

# ── /leaderboard_advanced ──────────────────────────────────
@bot.tree.command(name="leaderboard_advanced", description="Show the top 30 players leaderboard (image).")
async def cmd_leaderboard_advanced(interaction: discord.Interaction):
    await interaction.response.defer()
    is_lord = interaction.user.id in LORD_IDS
    data    = build_leaderboard_data(guild=interaction.guild, limit=30)
    file    = make_leaderboard_image(data, title="ADVANCED LEADERBOARD — TOP 30")
    prefix  = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.followup.send(
        content=prefix if is_lord else None,
        file=file,
    )

# ── /help ──────────────────────────────────────────────────
@bot.tree.command(name="help", description="List all bot commands.")
async def cmd_help(interaction: discord.Interaction):
    is_lord = interaction.user.id in LORD_IDS
    embed = discord.Embed(
        title="📖 Command Reference",
        color=discord.Color.gold(),
    )
    cmds = [
        ("/level [member]",              "View your level or a member's level"),
        ("/balance [member]",            "View your Losts balance or a member's"),
        ("/shop",                        "Browse the daily shop"),
        ("/buy <item>",                  "Purchase an item (noblesse, gun, sword, food, egg)"),
        ("/use <item> [member]",         "Use an item from your inventory"),
        ("/id [member]",                 "Full profile: level, Losts, inventory, effects"),
        ("/inventory",                   "View your inventory and active effects"),
        ("/leaderboard",                 "Top 10 players as an image"),
        ("/leaderboard_advanced",        "Top 30 players as an image"),
        ("/help",                        "Show this message"),
    ]
    for name, desc in cmds:
        embed.add_field(name=name, value=desc, inline=False)
    embed.add_field(
        name="Passive features",
        value=(
            "💬 Every message earns **3 Losts** + **XP**\n"
            "⏳ Titled members earn Losts passively every hour\n"
            "🤖 Mention the bot to chat with the AI\n"
            "🎉 Automatic welcome messages for new members"
        ),
        inline=False,
    )
    prefix = lord_response(is_lord, "").split(".")[0] + "."
    await interaction.response.send_message(
        content=prefix if is_lord else None,
        embed=embed,
    )

# ── prefix !ping ───────────────────────────────────────────
@bot.command(name="ping")
async def cmd_ping(ctx: commands.Context):
    latency  = round(bot.latency * 1000)
    is_lord  = ctx.author.id in LORD_IDS
    if is_lord:
        await ctx.reply(f"Pong, my Lord! 🏓 `{latency}ms`")
    else:
        await ctx.reply("stfu nig.")

# ═══════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════
bot.run(TOKEN)
