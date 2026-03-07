import discord
from discord.ext import commands, tasks
import random
import os
from keep_alive import keep_alive
import base64
import requests
import logging
from supabase import create_client, Client

TOKEN = os.environ["DISCORD_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
url: str = "https://db.baiogatzydwhsevnuori.supabase.co"
key: str = "sb_secret_kShwrjSlxUreGHuoZrRUfg_M_2TR-a8"  # secret key
supabase: Client = create_client(url, key)

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

@bot.event
async def on_ready():
    logging.info(f"✅ Bot działa jako {bot.user}!")
    runda.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Kanał gry — tylko -drzwi
    if message.channel.name == CHANNEL_NAME:
        if message.content.startswith("-drzwi"):
            try:
                parts = message.content.split()
                numer = int(parts[1])
                if numer < 1 or numer > 10:
                    await message.delete()
                    await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 10!", delete_after=5)
                    return
            except (IndexError, ValueError):
                await message.delete()
                await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 10!", delete_after=5)
                return
        else:
            # Usuń wszystko inne w kanale gry
            await message.delete()
            return

    # **WAŻNE:** przetwarzaj wszystkie komendy niezależnie od kanału
    await bot.process_commands(message)

@tasks.loop(minutes=5)
async def runda():

    global poprawne_drzwi
    global wybory
    global aktualna_wiadomosc

    channel = discord.utils.get(bot.get_all_channels(), name=CHANNEL_NAME)

    if channel is None:
        print("Nie znaleziono kanału")
        return

    # zakończenie poprzedniej rundy
    if poprawne_drzwi is not None:

        wynik = f"🎮 **KONIEC RUNDY**\n\nPoprawne drzwi: **{poprawne_drzwi}**\n\n"

        if len(wybory) == 0:
            wynik += "Nikt nie wybrał drzwi."

        else:
            for user_id, wybor in wybory.items():

                user = await bot.fetch_user(user_id)

                if wybor == poprawne_drzwi:
                # pobierz obecne punkty z Supabase
                    existing = supabase.table("punkty").select("*").eq("user_id", user_id).execute()
                    if existing.data:
                        supabase.table("punkty").update({"points": existing.data[0]['points'] + 10}).eq("user_id", user_id).execute()
                    else:
                        supabase.table("punkty").insert({"user_id": user_id, "points": 10}).execute()
    
                    wynik += f"{user.mention} — ✅ trafił ({wybor})\n"
                else:
                    wynik += f"{user.mention} — ❌ pudło ({wybor})\n"

        await channel.send(wynik, delete_after=60)

    # nowa runda
    poprawne_drzwi = random.randint(1, 10)
    wybory = {}

    msg = await channel.send(
        """
🎮 **NOWA RUNDA LUCKY DOORS**

🚪 Wybierz drzwi **1-10**

Wpisz:
`-drzwi numer`

⏳ Czas: 5 minut
"""
    , delete_after=300)

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
    await msg.delete(delay=5)  # wiadomość znika po 5 sekundach

@bot.command()
async def punkty(ctx):
    """Wyświetla aktualne punkty użytkownika tylko na kanale gry"""
    if ctx.channel.name != CHANNEL_NAMEX:
        return  # ignoruje komendę jeśli nie na odpowiednim kanale
    
    user_id = ctx.author.id
    result = supabase.table("punkty").select("*").eq("user_id", user_id).execute()
    
    if result.data:
        points = result.data[0]["points"]
        await ctx.send(f"{ctx.author.mention}, masz **{points} punktów** 🎉")
    else:
        await ctx.send(f"{ctx.author.mention}, jeszcze nie masz punktów. Zacznij grać!")
        
bot.run(TOKEN)















