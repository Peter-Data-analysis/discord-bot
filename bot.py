import discord
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
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

# --- Konfiguracja ---
TOKEN = os.environ["DISCORD_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

CHANNEL_NAME = "❰❰🚪❱❱luckydoors"
CHANNEL_NAMEX = "❰❰🚪❱❱czat-gry"
db_lock = asyncio.Lock()

# --- Logowanie ---
keep_alive()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
stop_runda = False
items_data = {}
# --- Funkcja backupu bazy na GitHub ---
def download_db():
    url = f"https://api.github.com/repos/Paither/discord-bot-backup/contents/luckydoors.db"
    r = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code == 200:
        content = base64.b64decode(r.json()["content"])
        with open("luckydoors.db", "wb") as f:
            f.write(content)
        logging.info("✅ Pobrano backup bazy")
    else:
        logging.warning("⚠ Nie znaleziono backupu bazy, tworzę nową")

def upload_db():
    with open("luckydoors.db", "rb") as f:
        content = base64.b64encode(f.read()).decode()

    url = f"https://api.github.com/repos/Paither/discord-bot-backup/contents/luckydoors.db"
    r_get = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r_get.status_code == 200:
        sha = r_get.json()["sha"]
    else:
        sha = None

    data = {"message": "backup database", "content": content}
    if sha:
        data["sha"] = sha

    r = requests.put(url, json=data, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code in [200, 201]:
        logging.info("✅ Baza wysłana do repo backupowego")
    else:
        try:
            err = r.json()
        except:
            err = r.text
        logging.error(f"❌ Błąd przy wysyłaniu bazy: {r.status_code} {err}")

def download_items():
    url = "https://api.github.com/repos/Paither/discord-bot-backup/contents/items.json"
    r = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    if r.status_code == 200:
        try:
            content = base64.b64decode(r.json()["content"])
            with open("items.json", "wb") as f:
                f.write(content)
            logging.info("✅ Pobrano items.json")
        except Exception as e:
            logging.error(f"❌ Błąd przy zapisie items.json: {e}")
    else:
        logging.warning(f"⚠ Nie udało się pobrać items.json, status: {r.status_code}")

def load_items():
    global items_data
    try:
        with open("items.json", "r", encoding="utf-8") as f:
            items_data = json.load(f)
        logging.info("✅ Items załadowane")
    except Exception as e:
        logging.error(f"❌ Błąd ładowania items: {e}")

# --- Połączenie z SQLite ---
download_db()
download_items()
load_items()
conn = sqlite3.connect("luckydoors.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL;")
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(punkty)")
kolumny = [kol[1] for kol in cursor.fetchall()]
if "week_points" not in kolumny:
    cursor.execute("ALTER TABLE punkty ADD COLUMN week_points INTEGER DEFAULT 0")
if "alltime_points" not in kolumny:
    cursor.execute("ALTER TABLE punkty ADD COLUMN alltime_points INTEGER DEFAULT 0")
if "items" not in kolumny:
    cursor.execute("ALTER TABLE punkty ADD COLUMN items TEXT DEFAULT '{}'")
conn.commit()

# --- Bot ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

poprawne_drzwi = None
pulapka_drzwi = None
wybory = {}
bonusowa_runda = False
pulapka_runda= False
jackpot_runda = False

# --- Event: bot ready ---
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")

    if not runda.is_running():
        runda.start()
    if not tygodniowy_ranking.is_running():
        tygodniowy_ranking.start()

# --- Event: filtrowanie wiadomości ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Kanał gry — tylko komendy -drzwi
    if message.channel.name == CHANNEL_NAME:
        if message.content.startswith("/drzwi"):
            try:
                numer = int(message.content.split()[1])
                if numer < 1 or numer > 5:
                    await message.delete()
                    await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 5!", delete_after=5)
                    return
            except (IndexError, ValueError):
                await message.delete()
                await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 5!", delete_after=5)
                return
        else:
            await message.delete()
            return

    await bot.process_commands(message)
    
# --- Event: usuwanie użytkownika z bazy danych po wyjściu z serwera ---
@bot.event
async def on_member_remove(member):
    user_id = member.id
    async with db_lock:
        cursor.execute("DELETE FROM punkty WHERE user_id = ?", (user_id,))
        conn.commit()
    logger.info(f"🗑 Usunięto punkty użytkownika {member.name} ({user_id}) z bazy")

# --- Szanse dropu w zależności od rarity---
def drop_item(user_id, items_json):
    drop_chances = {
        "common": 0.20,
        "uncommon": 0.15,
        "rare": 0.10,
        "epic": 0.05,
        "legendary": 0.01
    }

    drop_candidates = []

    for key, data in items_json.items():
        rarity = data.get("rarity", "common").lower()
        chance = drop_chances.get(rarity, 0)
        if random.random() < chance:
            drop_candidates.append(key)

    if drop_candidates:
        chosen_item = random.choice(drop_candidates)

        # Pobranie aktualnych przedmiotów użytkownika
        cursor.execute("SELECT items FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            user_items = json.loads(result[0])
        else:
            user_items = {}

        # Dodanie przedmiotu
        user_items[chosen_item] = user_items.get(chosen_item, 0) + 1
        cursor.execute("UPDATE punkty SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
        conn.commit()

        return chosen_item
    return None

# --- Pętla rundy ---
@tasks.loop(minutes=5)
async def runda():
    global poprawne_drzwi, wybory, pulapka_drzwi
    global pulapka_runda
    global bonusowa_runda
    global jackpot_runda
    if stop_runda:
        return  # nic nie robimy, runda nie startuje
    channel = discord.utils.get(bot.get_all_channels(), name=CHANNEL_NAME)
    if channel is None:
        logger.warning("Nie znaleziono kanału")
        return

    # --- Zakończenie poprzedniej rundy ---
    if poprawne_drzwi is not None:
        wynik = f"🎮 **KONIEC RUNDY**\n\nPoprawne drzwi: **{poprawne_drzwi}**\n\n"

        if not wybory:
            wynik += "Nikt nie wybrał drzwi."
        else:
            async with db_lock: 
                for user_id, wybor in wybory.items():
                    member = channel.guild.get_member(user_id)

                    if member:
                        user_mention = member.mention
                    else:
                        user_mention = f"<@{user_id}>"

                    if wybor == poprawne_drzwi:

                        if jackpot_runda:
                            punkty = 15
                        elif bonusowa_runda:
                            punkty = 5
                        else:
                            punkty = 1

                        # Dodanie punktów do obu kolumn
                        cursor.execute("""
                            INSERT INTO punkty (user_id, week_points, alltime_points)
                            VALUES (?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                            week_points = week_points + ?,
                            alltime_points = alltime_points + ?
                            """, (user_id, punkty, punkty, punkty, punkty))
                    
                            # --- Drop przedmiotu ---
                        dropped_item = drop_item(user_id, items_data)
                        if dropped_item:
                            wynik += f"{user_mention} — ✅ trafił (+{punkty} pkt) i zdobył **{items_data[dropped_item]['name']}**!\n"
                        else:
                            wynik += f"{user_mention} — ✅ trafił (+{punkty} pkt)\n"
                                
                    elif pulapka_runda and wybor == pulapka_drzwi:
                        punkty = 1
                        cursor.execute("""
                            INSERT INTO punkty (user_id, week_points, alltime_points)
                            VALUES (?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                            week_points = week_points - ?,
                            alltime_points = alltime_points - ?
                            """, (user_id, punkty, punkty, punkty, punkty))
                        wynik += f"{user_mention} — ☠️ PUŁAPKA. (-1 pkt)\n"
                    else:
                        wynik += f"{user_mention} — ❌ pudło\n"
            conn.commit()
        await channel.send(wynik, delete_after=60)
        upload_db()

    # --- Losowanie rundy ---
    jackpot_runda = random.random() < 0.005
    bonusowa_runda = False
    if not jackpot_runda:
        bonusowa_runda = random.random() < 0.05
    pulapka_runda = random.random() < 0.2
    

    # --- Nowa runda ---
    poprawne_drzwi = random.randint(1, 5)
    if pulapka_runda:
        pulapka_drzwi = random.randint(1, 5)
        while pulapka_drzwi == poprawne_drzwi:
            pulapka_drzwi = random.randint(1, 5)
    elif not pulapka_runda:
        pulapka_drzwi = None
    
    wybory = {}

    if bonusowa_runda:
        logging.info("✅ Wystąpiła bonusowa runda!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

Wyczuwam jakieś bonusy 💰...

🚪 Wybierz drzwi **1-5**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    elif jackpot_runda:
        logging.info("✅ Wystąpiła runda Jackpot!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

Szykuje się ostre zarabianie 💰💰💰...

🚪 Wybierz drzwi **1-5**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    else:
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

Nic ciekawego...

🚪 Wybierz drzwi **1-5**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    await channel.send(tekst, delete_after=299)
    if pulapka_runda:
        await channel.send("""🪤 Czuję również jakieś niebezpieczeństwo... Bądź ostrożny!""", delete_after=299)
    
@tasks.loop(time=time(hour=23, minute=59, tzinfo=ZoneInfo("Europe/Warsaw")))
async def tygodniowy_ranking():

    if datetime.now(ZoneInfo("Europe/Warsaw")).weekday() != 6:
        return
        
    channel = discord.utils.get(bot.get_all_channels(), name="❰❰📣❱❱-ogłoszenia")

    if channel is None:
        logger.warning("Nie znaleziono kanału ogłoszeń")
        return
    async with db_lock:
        cursor.execute(
            "SELECT user_id, week_points FROM punkty ORDER BY week_points DESC LIMIT 10"
        )

        top = cursor.fetchall()

    if not top:
        await channel.send("📊 Brak danych do rankingu.")
        return

    msg = "🏆 **TOP 10 GRACZY TYGODNIA - LUCKY DOORS**\n\n"

    for i, (user_id, points) in enumerate(top, start=1):
        member = channel.guild.get_member(user_id)

        if member:
            user_mention = member.mention
        else:
            user_mention = f"<@{user_id}>"
            
        msg += f"**{i}.** {user_mention} — {points} pkt\n"

    await channel.send(msg)
    async with db_lock:
        cursor.execute("UPDATE punkty SET week_points = 0")
        conn.commit()
    upload_db()
    
# --- Komenda -drzwi ---
@bot.command()
async def drzwi(ctx, numer: int):
    await ctx.message.delete()
    if ctx.channel.name != CHANNEL_NAME:
        return
    # --- sprawdzamy, czy gra nie jest wstrzymana ---
    global stop_runda
    if stop_runda:
        msg = await ctx.send("⏸ Gra została wstrzymana!", delete_after=5)
        return
    elif numer < 1 or numer > 5:
        await ctx.send("❌ Wybierz drzwi od 1 do 5!", delete_after=5)
        return
    elif ctx.author.id in wybory:
        await ctx.send("❌ Już wybrałeś drzwi w tej rundzie!", delete_after=5)
        return
    wybory[ctx.author.id] = numer
    msg = await ctx.send(f"{ctx.author.mention} wybrał drzwi **{numer}** 🚪", delete_after=5)

# --- Komenda -punkty (zmieniona) ---
@bot.command()
async def punkty(ctx):
    if ctx.channel.name != CHANNEL_NAMEX:
        return
    user_id = ctx.author.id
    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
    if result:
        week, alltime = result
        await ctx.send(f"{ctx.author.mention}, masz **{week} punktów tygodniowych** i **{alltime} punktów all-time** 🎉")
    else:
        await ctx.send(f"{ctx.author.mention}, jeszcze nie masz punktów. Zacznij grać!")

@bot.command()
@commands.has_role("Administrator")
async def top(ctx):
    async with db_lock:
        cursor.execute(
            "SELECT user_id, alltime_points FROM punkty ORDER BY alltime_points DESC LIMIT 20"
        )
        top_all = cursor.fetchall()

    if not top_all:
        await ctx.send("📊 Brak danych do rankingu all-time.")
        return

    msg = "🏆 **TOP 20 GRACZY ALL-TIME - LUCKY DOORS**\n\n"

    for i, (user_id, points) in enumerate(top_all, start=1):
        member = ctx.guild.get_member(user_id)

        if member:
            name = member.display_name   # nick z serwera (z dużymi literami)
        else:
            name = f"<@{user_id}>"

        msg += f"**{i}.** {name} — {points} pkt\n"

    await ctx.send(msg)

@bot.command()
async def czas_ranking(ctx):
    """Pokazuje, za ile czasu rozpocznie się kolejny ranking tygodniowy"""
    if not tygodniowy_ranking.is_running():
        await ctx.send("⏳ Ranking tygodniowy nie jest uruchomiony.")
        return

    # next_iteration to datetime w UTC
    next_time = tygodniowy_ranking.next_iteration

    # aktualny czas w UTC
    now = datetime.now(timezone.utc)

    # różnica czasu
    delta = next_time - now

    # format w godzinach, minutach, sekundach
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    await ctx.send(f"⏰ Kolejny ranking tygodniowy rozpocznie się za {hours}h {minutes}m {seconds}s.")
    
# --- Komenda administracyjna: dodaj punkty ---
@bot.command()
@commands.has_role("Administrator")
async def punkty_dodaj(ctx, member: discord.Member, ilosc: int):
    if ilosc <= 0:
        await ctx.send("❌ Podaj dodatnią liczbę punktów!")
        return
    async with db_lock:
        cursor.execute("""
            INSERT INTO punkty (user_id, week_points, alltime_points)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            week_points = week_points + ?,
            alltime_points = alltime_points + ?
        """, (member.id, ilosc, ilosc, ilosc, ilosc))
        conn.commit()
    await ctx.send(f"✅ Dodano {ilosc} punktów użytkownikowi {member.mention}.")

# --- Komenda administracyjna: usuń punkty ---
@bot.command()
@commands.has_role("Administrator")
async def punkty_usun(ctx, member: discord.Member, ilosc: int):
    if ilosc <= 0:
        await ctx.send("❌ Podaj dodatnią liczbę punktów!")
        return
    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
        if result:
            week, alltime = result
            new_week = max(week - ilosc, 0)
            new_alltime = max(alltime - ilosc, 0)
            cursor.execute("""
                UPDATE punkty SET week_points = ?, alltime_points = ? WHERE user_id = ?
            """, (new_week, new_alltime, member.id))
            conn.commit()
            await ctx.send(f"✅ Usunięto {ilosc} punktów użytkownikowi {member.mention}.")
        else:
            await ctx.send(f"❌ Użytkownik {member.mention} nie ma punktów w bazie.")

# --- Komenda administracyjna: usuń dane użytkownika ---
@bot.command()
@commands.has_role("Administrator")
async def data_usun(ctx, member: discord.Member):
    async with db_lock:
        cursor.execute("DELETE FROM punkty WHERE user_id = ?", (member.id,))
        conn.commit()
    await ctx.send(f"🗑 Dane użytkownika {member.mention} zostały usunięte z bazy.")

# --- Komenda administracyjna: zresetuj punkty ---
@bot.command()
@commands.has_role("Administrator")
async def punkty_reset(ctx):
    async with db_lock:
        cursor.execute("UPDATE punkty SET week_points = 0")
        conn.commit()
    await ctx.send("♻️ Punkty tygodniowe wszystkich użytkowników zostały zresetowane.")
    
# --- Komenda administracyjna: pokaż punkty użytkownika ---
@bot.command()
@commands.has_role("Administrator")
async def punkty_pokaz(ctx, member: discord.Member):
    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
    if result:
        week, alltime = result
        await ctx.send(f"{member.mention} ma **{week} punktów tygodniowych** i **{alltime} punktów all-time**.")
    else:
        await ctx.send(f"{member.mention} nie ma punktów w bazie.")

@bot.command()
@commands.has_role("Administrator")
async def runda_stop(ctx):
    """Kończy aktualną rundę i blokuje kolejne."""
    global stop_runda, stop_msg
    stop_runda = True
    channel = discord.utils.get(ctx.guild.text_channels, name=CHANNEL_NAME)
    if channel:
        stop_msg = await channel.send("⏹ Aktualna runda została zatrzymana. Kolejne rundy nie będą się rozpoczynać")

@bot.command()
@commands.has_role("Administrator")
async def reload_items(ctx):
    download_items()
    load_items()
    await ctx.send("🔄 Przedmioty zostały przeładowane.")

@bot.command()
@commands.has_role("Administrator")
async def runda_start(ctx):
    global stop_runda, stop_msg
    if stop_runda:
        stop_runda = False
        # usuwanie starej wiadomości stop
        if stop_msg:
            try:
                await stop_msg.delete()
            except discord.NotFound:
                pass
            stop_msg = None
        channel = discord.utils.get(ctx.guild.text_channels, name=CHANNEL_NAME)
        if channel:
            await channel.send("▶️ Runda została wznowiona. Poczekaj na wiadomość o nowej rundzie", delete_after=299)
    else:
        await ctx.send("❌ Gra już działa.")

@bot.command()
async def sklep(ctx):
    msg = "🛒 **SKLEP LUCKY DOORS**\n\n"

    for key, item in items_data.items():
        msg += f"**{item['name']}** — {item['cena']} pkt\n"
        msg += f"{item['opis']}\n\n"

    await ctx.send(msg)

@bot.command()
async def inventory(ctx):
    user_id = ctx.author.id
    async with db_lock:
        cursor.execute("SELECT items FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()

    if result:
        items = json.loads(result[0])
    else:
        items = {}

    if not items:
        await ctx.send(f"{ctx.author.mention}, nie masz jeszcze żadnych przedmiotów.")
    else:
        tekst = f"{ctx.author.mention}, oto Twoje przedmioty:\n"
        for item, ilosc in items.items():
            tekst += f"- {item}: {ilosc}\n"
        await ctx.send(tekst)

@bot.command()
@commands.has_role("Administrator")
async def przedmiot_dodaj(ctx, member: discord.Member, item_key: str, ilosc: int):
    """Dodaje określony przedmiot użytkownikowi."""
    if ilosc <= 0:
        await ctx.send("❌ Podaj dodatnią liczbę przedmiotów!", delete_after=5)
        return

    if item_key not in items_data:
        await ctx.send(f"❌ Nie znaleziono przedmiotu o kluczu `{item_key}`!", delete_after=5)
        return

    user_id = member.id
    async with db_lock:
        cursor.execute("SELECT items FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            user_items = json.loads(result[0])
        else:
            user_items = {}

        user_items[item_key] = user_items.get(item_key, 0) + ilosc
        cursor.execute("UPDATE punkty SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
        conn.commit()

    await ctx.send(f"✅ Dodano **{ilosc} x {items_data[item_key]['name']}** użytkownikowi {member.mention}.", delete_after=10)
        
# --- Start bota ---
bot.run(TOKEN)

































