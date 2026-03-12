import discord
from discord.ui import View, Button
from discord.ext import commands, tasks
import random
import sqlite3
import os
from keep_alive import keep_alive
import base64
import requests
import logging
import asyncio
import json
import atexit
from time import sleep
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from discord import app_commands

# --- Configuration ---
TOKEN = os.environ["DISCORD_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

CHANNEL_NAME = "❰❰🚪❱❱luckydoors"
CHANNEL_NAMEX = "❰❰🚪❱❱game_chat"
TRADE_CHANNEL = "❰❰💼❱❱trade"
db_lock = asyncio.Lock()

# --- Login ---
keep_alive()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
items_data = {}
listings = {}

MODERATOR_ROLES = ["Administrator", "Moderator", "Mod"]
def has_moderator_role():
    async def predicate(interaction: discord.Interaction) -> bool:
        return any(role.name in MODERATOR_ROLES for role in interaction.user.roles)
    return app_commands.check(predicate)
# --- Database backup function on Github ---
def download_db():
    url = f"https://api.github.com/repos/Paither/discord-bot-backup/contents/luckydoors.db"
    try:
        r = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"])
            with open("luckydoors.db", "wb") as f:
                f.write(content)
            logging.info("✅ Download database backup from Github")
        else:
            logging.warning("⚠ Database backup not found, new one will be created" "Nie znaleziono backupu bazy, zostanie utworzona nowa")
    except Exception as e:
        logging.error(f"❌ Error occurred while downloading backup: {e}")

def upload_db(max_retries: int = 3, delay: float = 2.0):
    with open("luckydoors.db", "rb") as f:
        content = base64.b64encode(f.read()).decode()

    url = f"https://api.github.com/repos/Paither/discord-bot-backup/contents/luckydoors.db"

    for attempt in range(1, max_retries + 1):
        try:
            r_get = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
            sha = None
            if r_get.status_code == 200:
                try:
                    sha = r_get.json().get("sha")
                except Exception:
                    sha = None

            data = {"message": f"backup database {datetime.now().isoformat()}", "content": content}
            if sha:
                data["sha"] = sha

            r_put = requests.put(url, json=data, headers={"Authorization": f"token {GITHUB_TOKEN}"})
            if r_put.status_code in [200, 201]:
                logging.info("✅ the database has been sent to github")
                return True
            else:
                try:
                    err = r_put.json()
                except:
                    err = r_put.text
                logging.warning(f"⚠ Attempt {attempt}: PUT failed: {r_put.status_code} {err}")
        except Exception as e:
            logging.warning(f"⚠ Attempt {attempt}: exception during upload: {e}")

        sleep(delay)

    logging.error("❌ Failed to upload database after several attempts")
    return False

def download_items():
    url = "https://api.github.com/repos/Paither/discord-bot-backup/contents/items.json"
    r = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code == 200:
        try:
            content = base64.b64decode(r.json()["content"])
            with open("items.json", "wb") as f:
                f.write(content)
            logging.info("✅ items.json downloaded")
        except Exception as e:
            logging.error(f"❌ Error while saving items.json: {e}")
    else:
        logging.warning(f"⚠ Nie udało się pobrać items.json, status: {r.status_code}")

def load_items():
    global items_data
    try:
        with open("items.json", "r", encoding="utf-8") as f:
            items_data = json.load(f)
        logging.info("✅ Items fetched from database")
    except Exception as e:
        logging.error(f"❌ Failed to fetched items from database: {e}")

# --- Połączenie z SQLite ---
download_db()
conn = sqlite3.connect("luckydoors.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL;")
cursor = conn.cursor()
download_items()
load_items()


correct_door = None
trap_door = None
choices = {}
bonus_round = False
trap_round = False
jackpot_round = False

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class MyBot(commands.Bot):
    async def setup_hook(self):
        if not auto_backup.is_running():
            auto_backup.start()
        if not round.is_running():
            round.start()
        if not weekly_ranking.is_running():
            weekly_ranking.start()
            
bot = MyBot(command_prefix=None, intents=intents)

# --- Event: bot ready ---
@bot.event
async def on_ready():
    logging.info(f"logged in as {bot.user}")
    guild_id = 1478885390407434455
    guild = discord.Object(id=guild_id)
    try:
        synced = await bot.tree.sync(guild=guild)
        logging.info(f"✅ {len(synced)} command on guild: {guild_id} synchronized")
    except Exception as e:
        logging.error(f"❌ sync error: {e}")

# --- Event: filtrowanie wiadomości ---
@bot.event
async def on_message(message):
    # ignorujemy wiadomości od botów
    if message.author.bot:
        return
    if message.channel.name == CHANNEL_NAME:
        if message.content and not message.content.startswith("/drzwi"):
            await message.delete()
# --- Event: usuwanie użytkownika z bazy danych po wyjściu z serwera ---
@bot.event
async def on_member_remove(member):
    user_id = member.id
    async with db_lock:
        cursor.execute("DELETE FROM pouch WHERE user_id = ?", (user_id,))
        conn.commit()
    logger.info(f"🗑 User points of {member.name} ({user_id}) deleted from the database")
# --- obsługa kliknięcia przycisku ---

@bot.event
async def on_button_click(interaction):
    if interaction.custom_id.startswith("open_chest_"):
        user_id = int(interaction.custom_id.split("_")[-1])
        if interaction.user.id != user_id:
            await interaction.respond(type=6)  # ignorujemy kliknięcia innych
            return

        # sprawdzamy, czy użytkownik ma złoty klucz
        cursor.execute("SELECT items FROM pouch WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            user_items = json.loads(result[0])
        else:
            user_items = {}

        if user_items.get("golden_key", 0) > 0:
            # odejmujemy klucz
            user_items["golden_key"] -= 1
            if user_items["golden_key"] == 0:
                del user_items["golden_key"]
            cursor.execute("UPDATE pouch SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
            conn.commit()

            # losowe Doorcal 40-80
            doorcal_reward = random.randint(40, 80)
            cursor.execute("""
                INSERT INTO pouch (user_id, doorcal)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                doorcal = doorcal + ?
            """, (user_id, doorcal_reward, doorcal_reward))
            conn.commit()

            await interaction.respond(content=f"🎉 You opened the chest and gained +{doorcal_reward} Doorcal!")
        else:
            await interaction.respond(content="❌ You don't have a Golden Key!")

# --- Drop chances depend of the formula---
def drop_item(user_id, items_json):
    # --- Szansa na drop ---
    roll = random.random()
    if roll < 0.01:
        rarity_roll = "legendary"
    elif roll < 0.04:
        rarity_roll = "epic"
    elif roll < 0.10:
        rarity_roll = "rare"
    elif roll < 0.21:
        rarity_roll = "uncommon"
    elif roll < 0.41:
        rarity_roll = "common"
    else:
        return None  # brak dropa

    # --- Szanse dla poszczególnych rzadkości ---
    drop_chances = {
        "common": 0.15,
        "uncommon": 0.10,
        "rare": 0.05,
        "epic": 0.02,
        "legendary": 0.01
    }

    # --- Wybór kandydatów do dropa ---
    drop_candidates = [
        key for key, data in items_json.items()
        if data.get("rarity", "common").lower() == rarity_roll
    ]

    if not drop_candidates:
        return None  # brak itemów w tej rzadkości

    # --- Losowy wybór przedmiotu ---
    chosen_item = random.choice(drop_candidates)

    # --- Pobranie aktualnych przedmiotów użytkownika ---
    cursor.execute("SELECT items FROM pouch WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        user_items = json.loads(result[0])
    else:
        user_items = {}

    # --- Dodanie przedmiotu ---
    user_items[chosen_item] = user_items.get(chosen_item, 0) + 1
    cursor.execute("UPDATE pouch SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
    conn.commit()

    return chosen_item
@tasks.loop(hours=24)
async def auto_backup():
    async with db_lock:
        conn.commit()
        upload_db()
        logging.info("💾 Automatic backup executed")

# --- rounds loop ---
@tasks.loop(minutes=5)
async def round():
    chest_chance = 0.1
    chest_door = None
    chest_winner = None
    global correct_door, choices, trap_door
    global trap_round
    global bonus_round
    global jackpot_round
    used_items_this_round.clear()
    if game_rounds.stopped:
        return
    channel = discord.utils.get(bot.get_all_channels(), name=CHANNEL_NAME)
    if channel is None:
        logger.warning("channel not found")
        return
        
    if random.random() < chest_chance:
        # możliwe drzwi na skrzyni, bez correct i trap
        possible_doors = [d for d in range(1, 6) if d != correct_door and d != trap_door]
        if possible_doors:
            chest_door = random.choice(possible_doors)
            # szukamy użytkownika, który wybrał te drzwi
            chest_winners = [user_id for user_id, choice in choices.items() if choice == chest_door]
            if chest_winners:
                chest_winner = random.choice(chest_winners)

    # --- Previous round completed ---
    if correct_door is not None:
        outcome = f"🎮 **Round finished**\n\nCorrect door: **{correct_door}**\n\n"

        if not choices:
            outcome += "No one participated in this round."
        else:
            async with db_lock: 
                for user_id, choice in choices.items():
                    member = channel.guild.get_member(user_id)

                    if member:
                        user_mention = member.mention
                    else:
                        user_mention = f"<@{user_id}>"

                    if choice == correct_door:

                        if jackpot_round:
                            doorcal = random.randint(15, 40)
                            points = 15
                        elif bonus_round:
                            doorcal = random.randint(5, 20)
                            points = 5
                        else:
                            doorcal = random.randint(1, 4)
                            points = 1

                        # adding points to both columns
                        cursor.execute("""
                            INSERT INTO pouch (user_id, week_points, alltime_points, doorcal)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                            week_points = week_points + ?,
                            alltime_points = alltime_points + ?,
                            doorcal = doorcal + ?
                            """, (user_id, points, points, doorcal, points, points, doorcal))
                    
                            # --- Drop item ---
                        dropped_item = drop_item(user_id, items_data)
                        if dropped_item:
                            outcome += f"{user_mention} — ✅ acquired (+{points} pts, found +{doorcal} Doorcal and retrieved **{items_data[dropped_item]['name']}**)!\n"
                        else:
                            outcome += f"{user_mention} — ✅ acquired (+{points} pts and found +{doorcal} Doorcal)\n"
                        if chest_winner:
                            member = channel.guild.get_member(chest_winner)
                            user_mention = member.mention if member else f"<@{chest_winner}>"

                            # wiadomość z przyciskiem otwarcia skrzyni
                            chest_msg = await channel.send(
                                f"🎁 {user_mention}, you found a **chest**! You need a **Golden Key** to open it.",
                                components=[
                                Button(label="Open Chest", custom_id=f"open_chest_{chest_winner}")
                                ]
                            )

                    elif trap_round and choice == trap_door:
                        points = 1
                        cursor.execute("""
                            INSERT INTO pouch (user_id, week_points, alltime_points)
                            VALUES (?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                            week_points = week_points - ?,
                            alltime_points = alltime_points - ?
                            """, (user_id, points, points, points, points))
                        outcome += f"{user_mention} — ☠️ TRAP. (-1 pts)\n"
                    else:
                        outcome += f"{user_mention} — ❌ only silence...\n"
            conn.commit()
        await channel.send(outcome, delete_after=60)

    # --- round draw ---
    jackpot_round = random.random() < 0.01
    bonus_round = False
    if not jackpot_round:
        bonus_round = random.random() < 0.05
    trap_round = random.random() < 0.2
    

    # --- New round ---
    correct_door = random.randint(1, 5)
    if trap_round:
        trap_door = random.randint(1, 5)
        while trap_door == correct_door:
            trap_door = random.randint(1, 5)
    elif not trap_round:
        trap_door = None
    
    choices = {}

    if bonus_round:
        logging.info("✅ Bonus round occurred!")
        text = """**New round LUCKY DOORS**

Seems like luck is on your side 💰

🚪 Choose your path **1-5**

Write:
`/door number`

⏳ Time: 5 minutes"""

    elif jackpot_round:
        logging.info("✅ Jackpot round occurred!")
        text = """🎮 **New round LUCKY DOORS**

This time the fates bleed gold! 💰💰💰...

🚪 Choose your path **1-5**

Write:
`/door number`

⏳ Time: 5 minutes"""

    else:
        text = """ **New round LUCKY DOORS**

empty path... empty pouch...

🚪 Choose your path **1-5**

Write:
`/door number`

⏳ Time: 5 minutes"""

    await channel.send(text, delete_after=299)
    if trap_round:
        await channel.send("""you need to sharpen your intuition""", delete_after=299)

def shutdown_backup():
    try:
        logging.info("⚠ Bot shutting down - starting backup")

        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(FULL)")

        upload_db()

        conn.close()

        logging.info("💾 Backup on bot shutdown completed")
    except Exception as e:
        logging.error(f"❌ Shutdown backup failed: {e}")
    
@tasks.loop(time=time(hour=23, minute=59, tzinfo=ZoneInfo("Europe/Warsaw")))
async def weekly_ranking():

    if datetime.now(ZoneInfo("Europe/Warsaw")).weekday() != 6:
        return
        
    channel = discord.utils.get(bot.get_all_channels(), name="❰❰📣❱❱annoucements")

    if channel is None:
        logger.warning("annoucements channel not found")
        return
    async with db_lock:
        cursor.execute(
            "SELECT user_id, week_points FROM pouch ORDER BY week_points DESC LIMIT 10"
        )

        top = cursor.fetchall()

    if not top:
        await channel.send("📊 Brak danych do rankingu.")
        return

    msg = "🏆 **TOP 10 dwellers - LUCKY DOORS**\n\n"

    for i, (user_id, points) in enumerate(top, start=1):
        member = channel.guild.get_member(user_id)

        if member:
            user_mention = member.mention
        else:
            user_mention = f"<@{user_id}>"
            
        msg += f"**{i}.** {user_mention} — {points} pkt\n"

    await channel.send(msg)
    async with db_lock:
        cursor.execute("UPDATE pouch SET week_points = 0")
        conn.commit()
    upload_db()
    
# --- command /door ---
@bot.tree.command(name="door", description="Select a door", guild=discord.Object(id=1478885390407434455))
async def door(interaction: discord.Interaction, number: int):
    if interaction.channel.name != CHANNEL_NAME:
        return
    choices[interaction.user.id] = number
    await interaction.response.send_message("✅ your choice was saved!", ephemeral=True, delete_after=3)
    
@bot.tree.command(
    name="pouch_view",
    description="Show your points, Doorcal and inventory",
    guild=discord.Object(id=1478885390407434455)
)
@app_commands.describe(target_user="View stats for another user (Admins/Mods)")
async def Pouch_view(interaction: discord.Interaction, target_user: discord.Member = None):
    # Sprawdzenie kanału
    if interaction.channel.name != CHANNEL_NAMEX:
        await interaction.response.send_message(
            "❌ This command works only in the game channel.", ephemeral=True, delete_after=5
        )
        return

    # Sprawdzenie, czy użytkownik podał target_user
    if target_user:
        # Sprawdzenie ról użytkownika
        allowed = any(role.name in MODERATOR_ROLES for role in interaction.user.roles)
        if not allowed:
            await interaction.response.send_message(
                "❌ You can't view other users' stats.", ephemeral=True, delete_after=5
            )
            return
        user_id = target_user.id
        display_user = target_user
    else:
        user_id = interaction.user.id
        display_user = interaction.user

    # Pobranie danych z bazy
    async with db_lock:
        cursor.execute(
            "SELECT week_points, alltime_points, doorcal, items FROM pouch WHERE user_id = ?", 
            (user_id,)
        )
        result = cursor.fetchone()

    if result:
        week_points, alltime_points, doorcal, items_json = result
        items = json.loads(items_json) if items_json else {}
    else:
        week_points = alltime_points = doorcal = 0
        items = {}

    # Tworzymy wiadomość
    msg = f"📊 **Stats for {display_user.mention}**\n\n"
    msg += f"**Points:** {week_points} this week | {alltime_points} all-time\n"
    msg += f"**Doorcal:** {doorcal}\n"

    if items:
        msg += "**Inventory:**\n"
        for item_name, amount in items.items():
            msg += f"- {item_name}: {amount}\n"
    else:
        msg += "You have no items in your pouch. Time to fill it.\n"

    await interaction.response.send_message(msg, ephemeral=True, delete_after=20)

# global variable to track used items per round
used_items_this_round = set() # przechowuje user_id

@bot.tree.command(name="use", description="Use an item", guild=discord.Object(id=1478885390407434455))
@app_commands.describe(item_name="Name of the item to use")
async def use(interaction: discord.Interaction, item_name: str):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message(
            "❌ You can only use items in the game channel.", ephemeral=True
        )
        return

    user_id = interaction.user.id

    # check if user already used an item this round
    if user_id in used_items_this_round:
        await interaction.response.send_message(
            "❌ You have already used an item this round.", ephemeral=True
        )
        return

    async with db_lock:
        cursor.execute("SELECT items FROM pouch WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        user_items = json.loads(result[0]) if result and result[0] else {}

        if item_name not in user_items or user_items[item_name] <= 0:
            await interaction.response.send_message("❌ You don't have this item.", ephemeral=True)
            return

        # --- Shield – pasywny ---
        if item_name.lower() == "shield":
            await interaction.response.send_message(
                "🛡 Shield is passive and will protect you automatically from trap doors.", ephemeral=True
            )

        # --- Golden Key – pasywny przy /use ---
        elif item_name.lower() == "golden_key":
            await interaction.response.send_message(
                "🗝 Golden Key is used automatically when opening a golden chest with /open golden_chest.", ephemeral=True
            )

        # --- Prophecy ---
        elif item_name.lower() == "prophecy":
            # wybieramy 2 drzwi które nie są niczym
            possible_doors = [d for d in range(1, 6)
                              if d != correct_door
                              and d != trap_door
                              and (chest_door is None or d != chest_door)]
            if not possible_doors:
                await interaction.response.send_message(
                    "Nothing to reveal... all doors have something!", ephemeral=True
                )
                return
            empty_doors = random.sample(possible_doors, min(2, len(possible_doors)))

            # odejmujemy item z ekwipunku
            user_items[item_name.lower()] -= 1
            if user_items[item_name.lower()] <= 0:
                del user_items[item_name.lower()]
            cursor.execute("UPDATE pouch SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
            conn.commit()

            await interaction.response.send_message(
                f"🔮 Prophecy reveals: doors {empty_doors[0]} and {empty_doors[1]} are empty.", ephemeral=True
            )

        # --- Eavesdrop ---
        elif item_name.lower() == "eavesdrop":
            if correct_door is None:
                await interaction.response.send_message(
                    "Round hasn't started yet!", ephemeral=True
                )
                return

            # odejmujemy item z ekwipunku
            user_items[item_name.lower()] -= 1
            if user_items[item_name.lower()] <= 0:
                del user_items[item_name.lower()]
            cursor.execute("UPDATE pouch SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
            conn.commit()

            await interaction.response.send_message(
                f"👂 Eavesdrop reveals: the correct door is {correct_door}.", ephemeral=True
            )

        # --- nieznany item ---
        else:
            await interaction.response.send_message("❌ Unknown item.", ephemeral=True)
            return

        # mark user as having used an item this round
        used_items_this_round.add(user_id)
# ------------------------------------------------------------------------------------------------- admin commands -------------------------------------------------------------------------------------------------

# ------------------------------------------------------------------------------------------------- Komenda /top  -------------------------------------------------------------------------------------------------
@bot.tree.command(name="top", description="Pokaż TOP 20 graczy all-time", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def top(interaction: discord.Interaction):
    async with db_lock:
        cursor.execute("SELECT user_id, alltime_points FROM pouch ORDER BY alltime_points DESC LIMIT 20")
        top_all = cursor.fetchall()

    if not top_all:
        await interaction.response.send_message("📊 Brak danych do rankingu all-time.")
        return

    msg = "🏆 **TOP 20 GRACZY ALL-TIME - LUCKY DOORS**\n\n"
    for i, (user_id, points) in enumerate(top_all, start=1):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member else f"<@{user_id}>"
        msg += f"**{i}.** {name} — {points} pkt\n"

    await interaction.response.send_message(msg)

# ------------------------------------------------------------------------------------------------------ give ------------------------------------------------------------------------------------------------------
@bot.tree.command(name="give", description="Give currency, points or item to user", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
@app_commands.describe(
    target="points / currency / item",
    member="Target user",
    amount="Amount",
    item_key="Item key (only for items)"
)
async def give(interaction: discord.Interaction, target: str, member: discord.Member, amount: int, item_key: str = None):

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    user_id = member.id

    async with db_lock:

        # POINTS
        if target == "points":

            cursor.execute("""
                INSERT INTO pouch (user_id, week_points, alltime_points)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                week_points = week_points + ?,
                alltime_points = alltime_points + ?
            """, (user_id, amount, amount, amount, amount))

            conn.commit()

            await interaction.response.send_message(
                f"✅ Gave **{amount} points** to {member.mention}.",
                ephemeral=True
            )

        # CURRENCY
        elif target == "currency":

            cursor.execute("SELECT doorcal FROM pouch WHERE user_id=?", (user_id,))
            result = cursor.fetchone()

            current = result[0] if result else 0

            if result:
                cursor.execute(
                    "UPDATE pouch SET doorcal=? WHERE user_id=?",
                    (current + amount, user_id)
                )
            else:
                cursor.execute(
                    "INSERT INTO pouch (user_id, week_points, alltime_points, doorcal) VALUES (?,0,0,?)",
                    (user_id, amount)
                )

            conn.commit()

            await interaction.response.send_message(
                f"✅ Gave **{amount} Doorcal** to {member.mention}.",
                ephemeral=True
            )

        # ITEM
        elif target == "item":

            if not item_key:
                await interaction.response.send_message("❌ Provide item_key.", ephemeral=True)
                return

            if item_key not in items_data:
                await interaction.response.send_message("❌ Item does not exist.", ephemeral=True)
                return

            cursor.execute("SELECT items FROM pouch WHERE user_id=?", (user_id,))
            result = cursor.fetchone()

            user_items = json.loads(result[0]) if result and result[0] else {}

            user_items[item_key] = user_items.get(item_key, 0) + amount

            cursor.execute(
                "UPDATE pouch SET items=? WHERE user_id=?",
                (json.dumps(user_items), user_id)
            )

            conn.commit()

            await interaction.response.send_message(
                f"✅ Gave **{amount} x {items_data[item_key]['name']}** to {member.mention}.",
                ephemeral=True
            )

        else:
            await interaction.response.send_message("❌ Invalid target type.", ephemeral=True)
            
@give.autocomplete("item_key")
async def item_autocomplete(interaction: discord.Interaction, current: str):

    choices = [
        app_commands.Choice(name=item['name'], value=key)
        for key, item in items_data.items()
        if current.lower() in key.lower()
    ]

    return choices[:25]
# ------------------------------------------------------------------------------------------------------ take ------------------------------------------------------------------------------------------------------
@bot.tree.command(name="take", description="Remove currency, points or item from user", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def take(interaction: discord.Interaction, target: str, member: discord.Member, amount: int, item_key: str = None):

    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    user_id = member.id

    async with db_lock:

        # POINTS
        if target == "points":

            cursor.execute("SELECT week_points, alltime_points FROM pouch WHERE user_id=?", (user_id,))
            result = cursor.fetchone()

            if not result:
                await interaction.response.send_message("❌ User has no points.", ephemeral=True)
                return

            week, alltime = result

            new_week = max(week - amount, 0)
            new_alltime = max(alltime - amount, 0)

            cursor.execute(
                "UPDATE pouch SET week_points=?, alltime_points=? WHERE user_id=?",
                (new_week, new_alltime, user_id)
            )

            conn.commit()

            await interaction.response.send_message(
                f"✅ Removed **{amount} points** from {member.mention}.",
                ephemeral=True
            )

        # CURRENCY
        elif target == "currency":

            cursor.execute("SELECT doorcal FROM pouch WHERE user_id=?", (user_id,))
            result = cursor.fetchone()

            if not result:
                await interaction.response.send_message("❌ User has no Doorcal.", ephemeral=True)
                return

            current = result[0]
            new_amount = max(current - amount, 0)

            cursor.execute(
                "UPDATE pouch SET doorcal=? WHERE user_id=?",
                (new_amount, user_id)
            )

            conn.commit()

            await interaction.response.send_message(
                f"✅ Removed **{amount} Doorcal** from {member.mention}.",
                ephemeral=True
            )

        # ITEM
        elif target == "item":

            if not item_key:
                await interaction.response.send_message("❌ Provide item_key.", ephemeral=True)
                return

            cursor.execute("SELECT items FROM pouch WHERE user_id=?", (user_id,))
            result = cursor.fetchone()

            items = json.loads(result[0]) if result and result[0] else {}

            if items.get(item_key, 0) < amount:
                await interaction.response.send_message("❌ User does not have enough items.", ephemeral=True)
                return

            items[item_key] -= amount

            if items[item_key] <= 0:
                del items[item_key]

            cursor.execute(
                "UPDATE pouch SET items=? WHERE user_id=?",
                (json.dumps(items), user_id)
            )

            conn.commit()

            await interaction.response.send_message(
                f"✅ Removed **{amount} x {item_key}** from {member.mention}.",
                ephemeral=True
            )

        else:
            await interaction.response.send_message("❌ Invalid target type.", ephemeral=True)
            
@take.autocomplete("item_key")
async def item_autocomplete_take(interaction: discord.Interaction, current: str):

    choices = [
        app_commands.Choice(name=item['name'], value=key)
        for key, item in items_data.items()
        if current.lower() in key.lower()
    ]

    return choices[:25]
 
# --- Komenda /remove_record ---
@bot.tree.command(name="remove_record", description="Remove all user data from the database", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def remove_record(interaction: discord.Interaction, member: discord.Member):
    async with db_lock:
        cursor.execute("DELETE FROM pouch WHERE user_id = ?", (member.id,))
        conn.commit()
    await interaction.response.send_message(f"🗑 {member.mention}'s data has been removed from the database.", ephemeral=True)

# --- Komenda /points_reset ---
@bot.tree.command(name="points_reset", description="Reset weekly points from all users", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def points_reset(interaction: discord.Interaction):
    async with db_lock:
        cursor.execute("UPDATE pouch SET week_points = 0")
        conn.commit()
    await interaction.response.send_message("♻️ Weekly points from all users have been reset")

# ------------------------------------------------------------------------ round_stop / round_start ---------------------------------------------------------------------------------------------------------------
class GameRounds:
    def __init__(self):
        self.stopped = False
        self.stop_msg = None

    async def stop(self, channel):
        self.stopped = True
        if channel:
            self.stop_msg = await channel.send(
                "⏹ The current round has been stopped. Subsequent rounds will not start"
            )

    async def resume(self, channel):
        if self.stopped and self.stop_msg:
            self.stopped = False
            try:
                await self.stop_msg.delete()
            except discord.NotFound:
                pass
            self.stop_msg = None
            if channel:
                await channel.send(
                    "▶️ The round has been resumed. Wait for the new round message",
                    delete_after=299
                )
            return True
        return False

# --- Inicjalizacja obiektu ---
game_rounds = GameRounds()

# --- Komendy administracyjne ---
@bot.tree.command(name="round_stop", description="Stop the current and upcoming game rounds", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def round_stop(interaction: discord.Interaction):
    channel = discord.utils.get(interaction.guild.text_channels, name=CHANNEL_NAME)
    await game_rounds.stop(channel)

@bot.tree.command(name="round_start", description="Resume the game", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def round_start(interaction: discord.Interaction):
    channel = discord.utils.get(interaction.guild.text_channels, name=CHANNEL_NAME)
    resumed = await game_rounds.resume(channel)
    if not resumed:
        await interaction.response.send_message("❌ The game is already running.", ephemeral=True)
        
# --- Command /shop ---
@bot.tree.command(name="shop", description="Show available items in the shop", guild=discord.Object(id=1478885390407434455))
@has_moderator_role()
async def shop(interaction: discord.Interaction):

    msg = "🛒 **LUCKY DOORS SHOP**\n\n"
    for key, item in items_data.items():
        msg += f"**{item['name']}** — {item['price']} pts\n{item['description']}\n\n"

    await interaction.response.send_message(msg)
  
# ------------------------------------------------------------------------------------------------ Trade Command ------------------------------------------------------------------------


@bot.tree.command(name="trade", description="Create a trade offer", guild=discord.Object(id=1478885390407434455))
@app_commands.describe(
    have="What you offer",
    have_amount="How many units you offer",
    want="What you want",
    want_amount="How many units you want"
)
async def trade(interaction: discord.Interaction, have: str, have_amount: int, want: str, want_amount: int):

    if interaction.channel.name != TRADE_CHANNEL:
        await interaction.response.send_message(
            f"❌ This command works only in {TRADE_CHANNEL}",
            ephemeral=True
        )
        return

    if have_amount <= 0 or want_amount <= 0:
        await interaction.response.send_message(
            "❌ Amounts must be greater than 0!",
            ephemeral=True
        )
        return

    user_id = interaction.user.id

    # --- Check if items exist ---
    if have.lower() != "doorcal" and have not in items_data:
        await interaction.response.send_message(
            f"❌ Invalid item `{have}`!",
            ephemeral=True
        )
        return

    if want.lower() != "doorcal" and want not in items_data:
        await interaction.response.send_message(
            f"❌ Invalid item `{want}`!",
            ephemeral=True
        )
        return

    async with db_lock:
        cursor.execute("SELECT items, doorcal FROM pouch WHERE user_id=?", (user_id,))
        result = cursor.fetchone()

    items = json.loads(result[0]) if result and result[0] else {}
    doorcal = result[1] if result else 0
    def take(item_dict, key, amount):
        item_dict[key] = item_dict.get(key, 0) - amount
        if item_dict[key] <= 0:
            del item_dict[key]

    # --- Check if user owns offered items ---
    if have.lower() == "doorcal":
        if doorcal < have_amount:
            await interaction.response.send_message("❌ You don't have enough Doorcal!", ephemeral=True)
            return
    else:
        if items.get(have, 0) < have_amount:
            await interaction.response.send_message(
                f"❌ You don't have {have_amount} x {items_data[have]['name']}",
                ephemeral=True
            )
            return
            
    async with db_lock:
        if have == "doorcal":
            doorcal -= have_amount
        else:
            take(items, have, have_amount)
        cursor.execute(
            "UPDATE pouch SET items=?, doorcal=? WHERE user_id=?",
            (json.dumps(items), doorcal, user_id)
        )
        conn.commit()
        
    # names for display
    have_name = items_data[have]['name'] if have != "doorcal" else "Doorcal"
    want_name = items_data[want]['name'] if want != "doorcal" else "Doorcal"

    # --- Trade View ---
    class TradeView(View):
        def __init__(self):
            super().__init__(timeout=600)  # 10 minutes
            self.finished = False
        async def on_timeout(self):
            if self.finished:
                return

            self.finished = True

            for child in self.children:
                child.disabled = True

            try:
                await self.message.edit(
                    content=self.message.content + "\n⌛ Trade offer expired.",
                    view=self
                )
                async with db_lock:

                    cursor.execute("SELECT items, doorcal FROM pouch WHERE user_id=?", (user_id,))
                    result = cursor.fetchone()

                    items_o = json.loads(result[0]) if result and result[0] else {}
                    doorcal_o = result[1] if result else 0

                    if have == "doorcal":
                        doorcal_o += have_amount
                    else:
                        items_o[have] = items_o.get(have, 0) + have_amount

                    cursor.execute(
                        "UPDATE pouch SET items=?, doorcal=? WHERE user_id=?",
                        (json.dumps(items_o), doorcal_o, user_id)
                    )

                    conn.commit()
            except Exception:
                pass
                
        @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
        async def accept(self, interaction_btn: discord.Interaction, button: Button):

            if self.finished:
                await interaction_btn.response.send_message("❌ This trade is already finished.", ephemeral=True)
                return

            if interaction_btn.user.id == user_id:
                await interaction_btn.response.send_message("❌ You cannot accept your own offer!", ephemeral=True)
                return

            async with db_lock:

                # accepter data
                cursor.execute("SELECT items, doorcal FROM pouch WHERE user_id=?", (interaction_btn.user.id,))
                result_a = cursor.fetchone()

                items_a = json.loads(result_a[0]) if result_a and result_a[0] else {}
                doorcal_a = result_a[1] if result_a else 0

                # check accepter resources
                if want.lower() == "doorcal":
                    if doorcal_a < want_amount:
                        await interaction_btn.response.send_message("❌ You don't have enough Doorcal!", ephemeral=True)
                        return
                else:
                    if items_a.get(want, 0) < want_amount:
                        await interaction_btn.response.send_message(
                            f"❌ You don't have {want_amount} x {want_name}",
                            ephemeral=True
                        )
                        return

                # offerer data
                cursor.execute("SELECT items, doorcal FROM pouch WHERE user_id=?", (user_id,))
                result_o = cursor.fetchone()

                items_o = json.loads(result_o[0]) if result_o and result_o[0] else {}
                doorcal_o = result_o[1] if result_o else 0

                # safe item removal
                def take(item_dict, key, amount):
                    item_dict[key] = item_dict.get(key, 0) - amount
                    if item_dict[key] <= 0:
                        del item_dict[key]

                # accepter gives
                if want.lower() == "doorcal":
                    doorcal_a -= want_amount
                else:
                    take(items_a, want, want_amount)

                # offerer receives
                if want.lower() == "doorcal":
                    doorcal_o += want_amount
                else:
                    items_o[want] = items_o.get(want, 0) + want_amount

                # accepter receives
                if have.lower() == "doorcal":
                    doorcal_a += have_amount
                else:
                    items_a[have] = items_a.get(have, 0) + have_amount

                # save to database
                cursor.execute(
                    "UPDATE pouch SET items=?, doorcal=? WHERE user_id=?",
                    (json.dumps(items_o), doorcal_o, user_id)
                )

                cursor.execute(
                    "UPDATE pouch SET items=?, doorcal=? WHERE user_id=?",
                    (json.dumps(items_a), doorcal_a, interaction_btn.user.id)
                )

                conn.commit()

            self.finished = True

            await interaction_btn.message.edit(
                content=f"✅ {interaction.user.mention} traded with {interaction_btn.user.mention}",
                view=None
            )

            await interaction_btn.response.send_message("✅ Trade completed!", ephemeral=True)

        @discord.ui.button(label="Cancel Offer", style=discord.ButtonStyle.red)
        async def cancel(self, interaction_btn: discord.Interaction, button: Button):

            if interaction_btn.user.id != user_id:
                await interaction_btn.response.send_message(
                    "❌ Only the creator of the trade can cancel it.",
                    ephemeral=True
                )
                return

            if self.finished:
                await interaction_btn.response.send_message(
                    "❌ This trade is already finished.",
                    ephemeral=True
                )
                return

            self.finished = True

            await interaction_btn.message.edit(
                content=f"❌ Trade offer cancelled by {interaction.user.mention}.",
                view=None
            )

            await interaction_btn.response.send_message("Trade cancelled.", ephemeral=True)
            async with db_lock:

                cursor.execute("SELECT items, doorcal FROM pouch WHERE user_id=?", (user_id,))
                result = cursor.fetchone()

                items_o = json.loads(result[0]) if result and result[0] else {}
                doorcal_o = result[1] if result else 0

                if have == "doorcal":
                    doorcal_o += have_amount
                else:
                    items_o[have] = items_o.get(have, 0) + have_amount

                cursor.execute(
                    "UPDATE pouch SET items=?, doorcal=? WHERE user_id=?",
                    (json.dumps(items_o), doorcal_o, user_id)
                )

                conn.commit()

    view = TradeView()

    msg = await interaction.channel.send(
        f"💱 **TRADE OFFER**\n"
        f"{interaction.user.mention} offers **{have_amount} x {have_name}**\n"
        f"in exchange for **{want_amount} x {want_name}**",
        view=view
    )

    view.message = msg
    
    oferty[msg.id] = {
        "offerer": user_id,
        "have": have,
        "have_amount": have_amount,
        "want": want,
        "want_amount": want_amount
    }

    await interaction.response.send_message("✅ Trade offer created!", ephemeral=True)

# --- Autocomplete ---
@trade.autocomplete("have")
async def have_autocomplete(interaction: discord.Interaction, current: str):
    choices = [app_commands.Choice(name=item['name'], value=key)
               for key, item in items_data.items() if current.lower() in key.lower()]
    if "doorcal".startswith(current.lower()):
        choices.insert(0, app_commands.Choice(name="Doorcal", value="doorcal"))
    return choices[:25]  # <-- po prostu zwracasz listę, nie robisz żadnego send

@trade.autocomplete("want")
async def want_autocomplete(interaction: discord.Interaction, current: str):
    choices = [app_commands.Choice(name=item['name'], value=key)
               for key, item in items_data.items() if current.lower() in key.lower()]
    if "doorcal".startswith(current.lower()):
        choices.insert(0, app_commands.Choice(name="Doorcal", value="doorcal"))
    return choices[:25]

@bot.tree.command(name="backup", description="Manual database backup", guild=discord.Object(id=1478885390407434455))
async def backup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only admins can create a backup.", ephemeral=True)
        return

    await interaction.response.send_message("💾 Creating backup...", ephemeral=True)

    async with db_lock:
        conn.commit()                      # zapis wszystkich transakcji
        conn.execute("PRAGMA wal_checkpoint(FULL)")  # scalenie WAL → DB
        result = await asyncio.to_thread(upload_db)

    if result:
        await interaction.followup.send("✅ Backup saved to GitHub!", ephemeral=True)
    else:
        await interaction.followup.send("❌ Backup FAILED. Check the logs!", ephemeral=True)


@bot.tree.command(
    name="download_backup",
    description="Download the latest database backup from GitHub",
    guild=discord.Object(id=1478885390407434455)
)
@has_moderator_role()
async def download_backup(interaction: discord.Interaction):
    await interaction.response.send_message("⬇️ Downloading backup from GitHub...", ephemeral=True)
    try:
        # Download backup in a separate thread to avoid blocking the event loop
        result = await asyncio.to_thread(download_db)
        await interaction.followup.send("✅ Backup downloaded and saved locally!", ephemeral=True)
    except Exception as e:
        logging.error(f"❌ Error downloading backup: {e}")
        await interaction.followup.send(f"❌ Failed to download backup! {e}", ephemeral=True)

bot.run(TOKEN)














