import discord
from discord.ext import commands, tasks
import random
import sqlite3
import os
from keep_alive import keep_alive
import base64
import requests

TOKEN = os.environ["DISCORD_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

keep_alive()

REPO = "Paither/discord_bot"  # zamień na swój login/repo

def upload_db():
    with open("luckydoors.db", "rb") as f:
        content = base64.b64encode(f.read()).decode()

    data = {
        "message": "backup database",
        "content": content
    }

    url = f"https://api.github.com/repos/{REPO}/contents/luckydoors.db"

    r = requests.put(url, json=data, headers={
        "Authorization": f"token {GITHUB_TOKEN}"
    })

    if r.status_code in [200, 201]:
        print("✅ Baza wysłana na GitHub")
    else:
        print("❌ Błąd przy wysyłaniu bazy:", r.json())
CHANNEL_NAME = "❰❰🚪❱❱luckydoors"
CHANNEL_NAMEX = "❰❰🚪❱❱czat-gry"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="-", intents=intents)

poprawne_drzwi = None
wybory = {}
aktualna_wiadomosc = None

conn = sqlite3.connect("luckydoors.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS punkty (
    user_id INTEGER PRIMARY KEY,
    points INTEGER
)
""")

conn.commit()

@bot.event
async def on_ready():
    print(f"✅ Bot działa jako {bot.user}!")
    runda.start()

@bot.event
async def on_message(message):
    # ignoruj wiadomości bota
    if message.author.bot:
        return

    # tylko nasz kanał gry
    if message.channel.name != CHANNEL_NAME:
        return

    # tylko wiadomości zaczynające się od -drzwi
    if message.content.startswith("-drzwi"):
        # spróbuj wyciągnąć numer
        try:
            parts = message.content.split()
            numer = int(parts[1])  # drugi element powinien być numerem

            # jeśli numer jest poza zakresem
            if numer < 1 or numer > 10:
                await message.delete()
                await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 10!", delete_after=5)
                return

        except (IndexError, ValueError):
            # jeśli nie ma numeru lub jest coś niepoprawnego
            await message.delete()
            await message.channel.send(f"{message.author.mention} ❌ Wybierz drzwi od 1 do 10!", delete_after=5)
            return

    else:
        # jeśli wiadomość nie zaczyna się od -drzwi, usuń ją
        await message.delete()
        return

    # pozwól przetworzyć poprawną komendę normalnie
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
                    cursor.execute(
                    "INSERT INTO punkty (user_id, points) VALUES (?, 10) ON CONFLICT(user_id) DO UPDATE SET points = points + 10",
                    (user_id,)
                    )

                    conn.commit()
                   
                    wynik += f"{user.mention} — ✅ trafił ({wybor})\n"
                else:
                    wynik += f"{user.mention} — ❌ pudło ({wybor})\n"

        await channel.send(wynik)
        upload_db()  # backup bazy na GitHub
            # usuń wiadomość po 60 sekundach
        await asyncio.sleep(60)
        try:
            await msg_koniec.delete()
        except:
            pass

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
    )

    # odpinanie starej wiadomości
    await asyncio.sleep(5*60)
    try:
        await msg_nowa.delete()
    except:
        pass

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
    cursor.execute("SELECT points FROM punkty WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        await ctx.send(f"{ctx.author.mention}, masz **{result[0]} punktów** 🎉")
    else:
        await ctx.send(f"{ctx.author.mention}, jeszcze nie masz punktów. Zacznij grać!")
        
bot.run(TOKEN)





