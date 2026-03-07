import discord
from discord.ext import commands, tasks
import random
import os
import requests
import logging
from keep_alive import keep_alive

TOKEN = os.environ["DISCORD_TOKEN"]
EDGE_FUNCTION_URL = "https://baiogatzydwhsevnuori.supabase.co/functions/v1/punkty_api"

keep_alive()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_NAME = "❰❰🚪❱❱luckydoors"
CHANNEL_NAMEX = "❰❰🚪❱❱czat-gry"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="-", intents=intents)

poprawne_drzwi = None
wybory = {}
aktualna_wiadomosc = None

def add_points(user_id: int, points: int):
    """Wyślij żądanie do Edge Function, żeby dodać punkty"""
    try:
        r = requests.post(
            EDGE_FUNCTION_URL,
            json={"user_id": user_id, "points": points},
            timeout=5
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error adding points for {user_id}: {e}")
        return None

def get_points(user_id: int):
    """Wyślij żądanie do Edge Function, żeby pobrać punkty"""
    try:
        # dodaj 0 punktów, funkcja zwróci aktualne punkty
        r = requests.post(
            EDGE_FUNCTION_URL,
            json={"user_id": user_id, "points": 0},
            timeout=5
        )
        r.raise_for_status()
        return r.json().get("points", 0)
    except Exception as e:
        logger.error(f"Error getting points for {user_id}: {e}")
        return 0

@bot.event
async def on_ready():
    logger.info(f"✅ Bot działa jako {bot.user}!")
    runda.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

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

@tasks.loop(minutes=5)
async def runda():
    global poprawne_drzwi, wybory
    channel = discord.utils.get(bot.get_all_channels(), name=CHANNEL_NAME)
    if channel is None:
        return

    if poprawne_drzwi is not None:
        wynik = f"🎮 **KONIEC RUNDY**\n\nPoprawne drzwi: **{poprawne_drzwi}**\n\n"
        if len(wybory) == 0:
            wynik += "Nikt nie wybrał drzwi."
        else:
            for user_id, wybor in wybory.items():
                user = await bot.fetch_user(user_id)
                if wybor == poprawne_drzwi:
                    add_points(user_id, 10)
                    wynik += f"{user.mention} — ✅ trafił ({wybor})\n"
                else:
                    wynik += f"{user.mention} — ❌ pudło ({wybor})\n"
        await channel.send(wynik, delete_after=60)

    poprawne_drzwi = random.randint(1, 10)
    wybory = {}
    await channel.send(
        "🎮 **NOWA RUNDA LUCKY DOORS**\n\n🚪 Wybierz drzwi **1-10**\n\nWpisz:\n`-drzwi numer`\n\n⏳ Czas: 5 minut",
        delete_after=300
    )

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

@bot.command()
async def punkty(ctx):
    if ctx.channel.name != CHANNEL_NAMEX:
        return
    user_id = ctx.author.id
    points = get_points(user_id)
    if points:
        await ctx.send(f"{ctx.author.mention}, masz **{points} punktów** 🎉")
    else:
        await ctx.send(f"{ctx.author.mention}, jeszcze nie masz punktów. Zacznij grać!")

bot.run(TOKEN)
