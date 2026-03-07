import discord
from discord.ext import commands, tasks
import random
import sqlite3
import os
from keep_alive import keep_alive
import base64
import requests
import logging

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
def upload_db():
    try:
        with open("luckydoors.db", "rb") as f:
            content = base64.b64encode(f.read()).decode()
        url = "https://api.github.com/repos/Paither/discord-bot/contents/luckydoors.db"

        # Sprawdź czy plik istnieje, żeby pobrać SHA
        r_get = requests.get(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        sha = r_get.json()["sha"] if r_get.status_code == 200 else None

        data = {"message": "backup database", "content": content}
        if sha:
            data["sha"] = sha

        r = requests.put(url, json=data, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        if r.status_code in [200, 201]:
            logger.info("✅ Baza wysłana na GitHub")
        else:
            logger.error(f"❌ Błąd przy wysyłaniu bazy: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"❌ Upload DB error: {e}")

# --- Połączenie z SQLite ---
conn = sqlite3.connect("luckydoors.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS punkty (
    user_id INTEGER PRIMARY KEY,
    points INTEGER
)
""")
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
    logger.info(f"✅ Bot działa jako {bot.user}!")
    runda.start()

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

# --- Pętla rundy ---
@tasks.loop(minutes=5)
async def runda():
    global poprawne_drzwi, wybory

    channel = discord.utils.get(bot.get_all_channels(), name=CHANNEL_NAME)
    if channel is None:
        logger.warning("Nie znaleziono kanału")
        return

    # Zakończenie poprzedniej rundy
    if poprawne_drzwi is not None:
        wynik = f"🎮 **KONIEC RUNDY**\n\nPoprawne drzwi: **{poprawne_drzwi}**\n\n"
        if not wybory:
            wynik += "Nikt nie wybrał drzwi."
        else:
            for user_id, wybor in wybory.items():
                user = await bot.fetch_user(user_id)
                if wybor == poprawne_drzwi:
                    cursor.execute(
                        "INSERT INTO punkty (user_id, points) VALUES (?, 10) "
                        "ON CONFLICT(user_id) DO UPDATE SET points = points + 10",
                        (user_id,)
                    )
                    conn.commit()
                    wynik += f"{user.mention} — ✅ trafił ({wybor})\n"
                else:
                    wynik += f"{user.mention} — ❌ pudło ({wybor})\n"

        await channel.send(wynik)
        upload_db()  # backup po rundzie

    # Nowa runda
    poprawne_drzwi = random.randint(1, 10)
    wybory = {}
    await channel.send(
        """🎮 **NOWA RUNDA LUCKY DOORS**
🚪 Wybierz drzwi **1-10**
Wpisz:
`-drzwi numer`
⏳ Czas: 5 minut"""
    )

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

# --- Komenda -punkty ---
@bot.command()
async def punkty(ctx):
    if ctx.channel.name != CHANNEL_NAMEX:
        return
    user_id = ctx.author.id
    cursor.execute("SELECT points FROM punkty WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        await ctx.send(f"{ctx.author.mention}, masz **{result[0]} punktów** 🎉")
    else:
        await ctx.send(f"{ctx.author.mention}, jeszcze nie masz punktów. Zacznij grać!")

# --- Start bota ---
bot.run(TOKEN)
