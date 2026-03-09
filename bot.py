import discord
from discord.ext import commands, tasks
import random
import sqlite3
import os
from keep_alive import keep_alive
import base64
import requests
import logging
from datetime import datetime, timezone

# --- Konfiguracja ---
TOKEN = os.environ["DISCORD_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

CHANNEL_NAME = "❰❰🚪❱❱luckydoors"
CHANNEL_NAMEX = "❰❰🚪❱❱czat-gry"

# --- Logowanie ---
keep_alive()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        logging.error(f"❌ Błąd przy wysyłaniu bazy: {r.status_code} {r.json()}")

# --- Połączenie z SQLite ---
download_db()
conn = sqlite3.connect("luckydoors.db")
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
                if numer < 1 or numer > 10:
                    await message.delete()
                    await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 10!", delete_after=5)
                    return
            except (IndexError, ValueError):
                await message.delete()
                await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 10!", delete_after=5)
                return
        else:
            await message.delete()
            return

    await bot.process_commands(message)
    
# --- Event: usuwanie użytkownika z bazy danych po wyjściu z serwera ---
@bot.event
async def on_member_remove(member):
    user_id = member.id

    cursor.execute("DELETE FROM punkty WHERE user_id = ?", (user_id,))
    conn.commit()

    logger.info(f"🗑 Usunięto punkty użytkownika {member.name} ({user_id}) z bazy")


# --- Pętla rundy ---
@tasks.loop(minutes=5)
async def runda():
    global poprawne_drzwi, wybory
    global bonusowa_runda
    global jackpot_runda

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
            for user_id, wybor in wybory.items():
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)

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

                    conn.commit()

                    if jackpot_runda:
                        wynik += f"{user.mention} — 💰💰💰 JACKPOT! (+15 pkt)\n"
                    elif bonusowa_runda:
                        wynik += f"{user.mention} — 💰 BONUS! (+5 pkt)\n"
                    else:
                        wynik += f"{user.mention} — ✅ trafił ({wybor}) (+1 pkt)\n"

                else:
                    wynik += f"{user.mention} — ❌ pudło ({wybor})\n"

        await channel.send(wynik, delete_after=60)
        upload_db()

    # --- Losowanie rundy ---
    jackpot_runda = random.random() < 0.005
    bonusowa_runda = False

    if not jackpot_runda:
        bonusowa_runda = random.random() < 0.03

    # --- Nowa runda ---
    poprawne_drzwi = random.randint(1, 10)
    wybory = {}

    if bonusowa_runda:
        logging.info("✅ Wystąpiła bonusowa runda!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

💰 **BONUSOWA RUNDA!**
Za poprawne drzwi dostajesz **5 punktów**

🚪 Wybierz drzwi **1-10**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    elif jackpot_runda:
        logging.info("✅ Wystąpiła runda Jackpot!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

💰💰💰 **JACKPOT RUNDA!**
Za poprawne drzwi dostajesz **15 punktów**!!!

🚪 Wybierz drzwi **1-10**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    else:
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

🚪 Wybierz drzwi **1-10**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut"""

    await channel.send(tekst, delete_after=299)
    
@tasks.loop(hours=168)
async def tygodniowy_ranking():
    channel = discord.utils.get(bot.get_all_channels(), name="❰❰📣❱❱-ogłoszenia")

    if channel is None:
        logger.warning("Nie znaleziono kanału ogłoszeń")
        return

    cursor.execute(
        "SELECT user_id, week_points FROM punkty ORDER BY week_points DESC LIMIT 10"
    )

    top = cursor.fetchall()

    if not top:
        await channel.send("📊 Brak danych do rankingu.")
        return

    msg = "🏆 **TOP 10 GRACZY TYGODNIA - LUCKY DOORS**\n\n"

    for i, (user_id, points) in enumerate(top, start=1):
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        msg += f"**{i}.** {user.name} — {points} pkt\n"

    await channel.send(msg)
    cursor.execute("UPDATE punkty SET week_points = 0")
    conn.commit()
    upload_db()
    
# --- Komenda -drzwi ---
@bot.command()
async def drzwi(ctx, numer: int):
    await ctx.message.delete()
    if ctx.channel.name != CHANNEL_NAME:
        return
    if numer < 1 or numer > 10:
        await ctx.send("❌ Wybierz drzwi od 1 do 10!")
        return
    if ctx.author.id in wybory:
        await ctx.send("❌ Już wybrałeś drzwi w tej rundzie!")
        return
    wybory[ctx.author.id] = numer
    msg = await ctx.send(f"{ctx.author.mention} wybrał drzwi **{numer}** 🚪")
    await msg.delete(delay=5)

# --- Komenda -punkty (zmieniona) ---
@bot.command()
async def punkty(ctx):
    if ctx.channel.name != CHANNEL_NAMEX:
        return
    user_id = ctx.author.id
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
    
# --- Start bota ---
bot.run(TOKEN)















