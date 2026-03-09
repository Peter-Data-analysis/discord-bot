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

# --- Połączenie z SQLite ---
download_db()
conn = sqlite3.connect("luckydoors.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL;")
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(punkty)")
kolumny = [kol[1] for kol in cursor.fetchall()]
if "week_points" not in kolumny:
    cursor.execute("ALTER TABLE punkty ADD COLUMN week_points INTEGER DEFAULT 0")
if "alltime_points" not in kolumny:
    cursor.execute("ALTER TABLE punkty ADD COLUMN alltime_points INTEGER DEFAULT 0")
conn.commit()

# --- Bot ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="-", intents=intents)

poprawne_drzwi = None
wybory = {}
bonusowa_runda = False
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
        if message.content.startswith("-drzwi"):
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


# --- Pętla rundy ---
@tasks.loop(minutes=5)
async def runda():
    global poprawne_drzwi, wybory
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

                        if jackpot_runda:
                            wynik += f"{user_mention} — 💰💰💰 JACKPOT! (+15 pkt)\n"
                        elif bonusowa_runda:
                            wynik += f"{user_mention} — 💰 BONUS! (+5 pkt)\n"
                        else:
                            wynik += f"{user_mention} — ✅ trafił ({wybor}) (+1 pkt)\n"

                    else:
                        wynik += f"{user_mention} — ❌ pudło ({wybor})\n"
            conn.commit()
        await channel.send(wynik, delete_after=60)
        upload_db()

    # --- Losowanie rundy ---
    jackpot_runda = random.random() < 0.005
    bonusowa_runda = False

    if not jackpot_runda:
        bonusowa_runda = random.random() < 0.03

    # --- Nowa runda ---
    poprawne_drzwi = random.randint(1, 5)
    wybory = {}

    if bonusowa_runda:
        logging.info("✅ Wystąpiła bonusowa runda!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

💰 **BONUSOWA RUNDA!**
Za poprawne drzwi dostajesz **5 punktów**

🚪 Wybierz drzwi **1-5**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    elif jackpot_runda:
        logging.info("✅ Wystąpiła runda Jackpot!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

💰💰💰 **JACKPOT RUNDA!**
Za poprawne drzwi dostajesz **15 punktów**!!!

🚪 Wybierz drzwi **1-5**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    else:
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

🚪 Wybierz drzwi **1-5**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    await channel.send(tekst, delete_after=299)
    
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

@@bot.command()
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
        
# --- Start bota ---
bot.run(TOKEN)
























