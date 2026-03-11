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
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from discord import app_commands

# --- Konfiguracja ---
TOKEN = os.environ["DISCORD_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

CHANNEL_NAME = "❰❰🚪❱❱luckydoors"
CHANNEL_NAMEX = "❰❰🚪❱❱czat-gry"
HANDEL_CHANNEL = "❰❰💼❱❱handel"
db_lock = asyncio.Lock()

# --- Logowanie ---
keep_alive()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
stop_runda = False
items_data = {}
oferty = {}

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

poprawne_drzwi = None
pulapka_drzwi = None
wybory = {}
bonusowa_runda = False
pulapka_runda= False
jackpot_runda = False

# --- Event: bot ready ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class MyBot(commands.Bot):
    async def setup_hook(self):
        # synchronizacja komend
        try:
            synced = await self.tree.sync()
            logging.info(f"✅ Zsynchronizowano {len(synced)} komend slash")
        except Exception as e:
            logging.error(f"❌ Błąd przy sync komend: {e}")

        # uruchomienie pętli/loopów
        if not auto_backup.is_running():
            auto_backup.start()
        if not runda.is_running():
            runda.start()
        if not tygodniowy_ranking.is_running():
            tygodniowy_ranking.start()
            
bot = MyBot(command_prefix=None, intents=intents)

@bot.event
async def on_ready():
    logging.info(f"Zalogowano jako {bot.user}")

# --- Event: filtrowanie wiadomości ---
@bot.event
async def on_message(message):
    # ignorujemy wiadomości od botów
    if message.author.bot:
        return

    # kanał gry — usuwamy wszystko, co nie jest slash command
    if message.channel.name == CHANNEL_NAME:
        # slash commands nie zaczynają się od "/" w treści wiadomości,
        # więc nie wantmy niczego usuwać jeśli to komenda slash
        # (Discord API same obsługuje slashy)
        if message.content and not message.content.startswith("/drzwi"):
            await message.delete()
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
    
@tasks.loop(hours=24)
async def auto_backup():
    async with db_lock:
        conn.commit()
        upload_db()
        logging.info("💾 Automatyczny backup wykonany")

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
                            doorcal = random.randint(15, 40)
                            punkty = 15
                        elif bonusowa_runda:
                            doorcal = random.randint(5, 20)
                            punkty = 5
                        else:
                            doorcal = random.randint(1, 4)
                            punkty = 1

                        # Dodanie punktów do obu kolumn
                        cursor.execute("""
                            INSERT INTO punkty (user_id, week_points, alltime_points, doorcal)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                            week_points = week_points + ?,
                            alltime_points = alltime_points + ?,
                            doorcal = doorcal + ?
                            """, (user_id, punkty, punkty, doorcal, punkty, punkty, doorcal))
                    
                            # --- Drop przedmiotu ---
                        dropped_item = drop_item(user_id, items_data)
                        if dropped_item:
                            wynik += f"{user_mention} — ✅ trafił (+{punkty} pkt, +{doorcal} Doorcal i zdobył **{items_data[dropped_item]['name']}**)!\n"
                        else:
                            wynik += f"{user_mention} — ✅ trafił (+{punkty} pkt, +{doorcal} Doorcal)\n"
                                
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
`/drzwi numer`

⏳ Czas: 5 minut"""

    elif jackpot_runda:
        logging.info("✅ Wystąpiła runda Jackpot!")
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

Szykuje się ostre zarabianie 💰💰💰...

🚪 Wybierz drzwi **1-5**

Wpisz:
`/drzwi numer`

⏳ Czas: 5 minut"""

    else:
        tekst = """🎮 **NOWA RUNDA LUCKY DOORS**

Nic ciekawego...

🚪 Wybierz drzwi **1-5**

Wpisz:
`/drzwi numer`

⏳ Czas: 5 minut"""

    await channel.send(tekst, delete_after=299)
    if pulapka_runda:
        await channel.send("""🪤 Czuję również jakieś niebezpieczeństwo... Bądź ostrożny!""", delete_after=299)
def shutdown_backup():
    conn.commit()
    upload_db()
    print("💾 Backup przy zamykaniu bota")

atexit.register(shutdown_backup)
    
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
    
# --- Komenda /drzwi ---
@bot.tree.command(name="drzwi", description="Wybierz drzwi w aktualnej rundzie gry", guild=discord.Object(id=1478885390407434455))
async def drzwi(interaction: discord.Interaction, numer: int):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.defer(ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    wybory[interaction.user.id] = numer

# --- Komenda /punkty ---
@bot.tree.command(name="punkty", description="Sprawdź swoje punkty tygodniowe i all-time", guild=discord.Object(id=1478885390407434455))
async def punkty(interaction: discord.Interaction):
    if interaction.channel.name != CHANNEL_NAMEX:
        return
    user_id = interaction.user.id
    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
    if result:
        week, alltime = result
        await interaction.response.send_message(f"{interaction.user.mention}, masz **{week} punktów tygodniowych** i **{alltime} punktów all-time** 🎉", ephemeral=True)
    else:
        await interaction.response.send_message(f"{interaction.user.mention}, jeszcze nie masz punktów. Zacznij grać!", ephemeral=True)

# --- Komenda /top ---
@bot.tree.command(name="top", description="Pokaż TOP 20 graczy all-time", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def top(interaction: discord.Interaction):
    async with db_lock:
        cursor.execute("SELECT user_id, alltime_points FROM punkty ORDER BY alltime_points DESC LIMIT 20")
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

# --- Komenda /czas_ranking ---
@bot.tree.command(name="czas_ranking", description="Sprawdź, za ile czasu rozpocznie się kolejny ranking tygodniowy", guild=discord.Object(id=1478885390407434455))
async def czas_ranking(interaction: discord.Interaction):
    if not tygodniowy_ranking.is_running():
        await interaction.response.send_message("⏳ Ranking tygodniowy nie jest uruchomiony.")
        return

    next_time = tygodniowy_ranking.next_iteration
    now = datetime.now(timezone.utc)
    delta = next_time - now
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    await interaction.response.send_message(f"⏰ Kolejny ranking tygodniowy rozpocznie się za {hours}h {minutes}m {seconds}s.")

# --- Komendy administracyjne /punkty_dodaj i /punkty_usun ---
@bot.tree.command(name="punkty_dodaj", description="Dodaj punkty wybranemu użytkownikowi", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def punkty_dodaj(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią liczbę punktów!", ephemeral=True)
        return

    async with db_lock:
        cursor.execute("""
            INSERT INTO punkty (user_id, week_points, alltime_points)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            week_points = week_points + ?,
            alltime_points = alltime_points + ?
        """, (member.id, amount, amount, amount, amount))
        conn.commit()
    await interaction.response.send_message(f"✅ Dodano {amount} punktów użytkownikowi {member.mention}.")

@bot.tree.command(name="punkty_usun", description="Usuń punkty wybranemu użytkownikowi", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def punkty_usun(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią liczbę punktów!", ephemeral=True)
        return

    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
        if result:
            week, alltime = result
            new_week = max(week - amount, 0)
            new_alltime = max(alltime - amount, 0)
            cursor.execute("UPDATE punkty SET week_points = ?, alltime_points = ? WHERE user_id = ?",
                           (new_week, new_alltime, member.id))
            conn.commit()
            await interaction.response.send_message(f"✅ Usunięto {amount} punktów użytkownikowi {member.mention}.")
        else:
            await interaction.response.send_message(f"❌ Użytkownik {member.mention} nie ma punktów w bazie.")

# --- Komenda /usun_dane ---
@bot.tree.command(name="usun_dane", description="Usuń wszystkie dane użytkownika z bazy", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def usun_dane(interaction: discord.Interaction, member: discord.Member):
    async with db_lock:
        cursor.execute("DELETE FROM punkty WHERE user_id = ?", (member.id,))
        conn.commit()
    await interaction.response.send_message(f"🗑 Dane użytkownika {member.mention} zostały usunięte z bazy.")

# --- Komenda /punkty_reset ---
@bot.tree.command(name="punkty_reset", description="Zresetuj punkty tygodniowe wszystkich użytkowników", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def punkty_reset(interaction: discord.Interaction):
    async with db_lock:
        cursor.execute("UPDATE punkty SET week_points = 0")
        conn.commit()
    await interaction.response.send_message("♻️ Punkty tygodniowe wszystkich użytkowników zostały zresetowane.")

# --- Komenda /punkty_pokaz ---
@bot.tree.command(name="punkty_pokaz", description="Pokaż punkty wybranego użytkownika", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def punkty_pokaz(interaction: discord.Interaction, member: discord.Member):
    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
    if result:
        week, alltime = result
        await interaction.response.send_message(f"{member.mention} ma **{week} punktów tygodniowych** i **{alltime} punktów all-time**.")
    else:
        await interaction.response.send_message(f"{member.mention} nie ma punktów w bazie.")

# --- Komendy administracyjne: runda_stop / runda_start ---
@bot.tree.command(name="runda_stop", description="Zatrzymaj aktualną rundę gry", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def runda_stop(interaction: discord.Interaction):
    global stop_runda, stop_msg
    stop_runda = True
    channel = discord.utils.get(interaction.guild.text_channels, name=CHANNEL_NAME)
    if channel:
        stop_msg = await channel.send("⏹ Aktualna runda została zatrzymana. Kolejne rundy nie będą się rozpoczynać")

@bot.tree.command(name="runda_start", description="Wznów grę po zatrzymaniu rundy", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def runda_start(interaction: discord.Interaction):
    global stop_runda, stop_msg
    if stop_runda:
        stop_runda = False
        if stop_msg:
            try:
                await stop_msg.delete()
            except discord.NotFound:
                pass
            stop_msg = None
        channel = discord.utils.get(interaction.guild.text_channels, name=CHANNEL_NAME)
        if channel:
            await channel.send("▶️ Runda została wznowiona. Poczekaj na wiadomość o nowej rundzie", delete_after=299)
    else:
        await interaction.response.send_message("❌ Gra już działa.", ephemeral=True)

# --- Komenda /sklep ---
@bot.tree.command(name="sklep", description="Pokaż dostępne przedmioty w sklepie", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def sklep(interaction: discord.Interaction):
    
    msg = "🛒 **SKLEP LUCKY DOORS**\n\n"
    for key, item in items_data.items():
        msg += f"**{item['name']}** — {item['cena']} pkt\n{item['opis']}\n\n"
    await interaction.response.send_message(msg)

# --- Komenda /inventory ---
@bot.tree.command(name="itemy", description="Pokaż swoje przedmioty", guild=discord.Object(id=1478885390407434455))
async def itemy(interaction: discord.Interaction):
    user_id = interaction.user.id
    async with db_lock:
        cursor.execute("SELECT items FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()

    if result:
        items = json.loads(result[0]) if result[0] else {}
    else:
        items = {}

    if not items:
        await interaction.response.send_message(f"{interaction.user.mention}, nie masz jeszcze żadnych przedmiotów.", ephemeral=True)
    else:
        tekst = f"{interaction.user.mention}, oto Twoje przedmioty:\n"
        for item, amount in items.items():
            tekst += f"- {item}: {amount}\n"
        await interaction.response.send_message(tekst, ephemeral=True)

# --- Komenda administracyjna /przedmiot_dodaj ---
@bot.tree.command(name="przedmiot_dodaj", description="Dodaj określony przedmiot użytkownikowi", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def przedmiot_dodaj(interaction: discord.Interaction, member: discord.Member, item_key: str, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią liczbę przedmiotów!", ephemeral=True)
        return

    if item_key not in items_data:
        await interaction.response.send_message(f"❌ Nie znaleziono przedmiotu o kluczu `{item_key}`!", ephemeral=True)
        return

    user_id = member.id
    async with db_lock:
        cursor.execute("SELECT items FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        user_items = json.loads(result[0]) if result and result[0] else {}
        user_items[item_key] = user_items.get(item_key, 0) + amount
        cursor.execute("UPDATE punkty SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
        conn.commit()

    await interaction.response.send_message(f"✅ Dodano **{amount} x {items_data[item_key]['name']}** użytkownikowi {member.mention}.", ephemeral=True)

@bot.tree.command(name="dodaj_walute", description="Dodaj Doorcal wybranemu użytkownikowi", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def dodaj_walute(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią ilość Doorcal!", ephemeral=True)
        return

    async with db_lock:
        # Pobieramy aktualną ilość doorcal
        cursor.execute("SELECT doorcal FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
        current = result[0] if result else 0

        # Aktualizujemy bazę
        if result:
            cursor.execute("UPDATE punkty SET doorcal = ? WHERE user_id = ?", (current + amount, member.id))
        else:
            cursor.execute("INSERT INTO punkty (user_id, week_points, alltime_points, doorcal) VALUES (?, 0, 0, ?)", (member.id, amount))
        conn.commit()

    await interaction.response.send_message(f"✅ Dodano {amount} Doorcal użytkownikowi {member.mention}.", ephemeral=True)

# --- Komenda administracyjna /usun_walute ---
@bot.tree.command(name="usun_walute", description="Usuń Doorcal wybranemu użytkownikowi", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def usun_walute(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią ilość Doorcal!", ephemeral=True)
        return

    async with db_lock:
        cursor.execute("SELECT doorcal FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
        if result:
            current = result[0]
            new_amount = max(current - amount, 0)
            cursor.execute("UPDATE punkty SET doorcal = ? WHERE user_id = ?", (new_amount, member.id))
            conn.commit()
            await interaction.response.send_message(f"✅ Usunięto {amount} Doorcal użytkownikowi {member.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Użytkownik {member.mention} nie ma Doorcal.", ephemeral=True)

# --- Komenda /pokaz_walute ---
@bot.tree.command(name="pokaz_walute", description="Pokaż ilość Doorcal wybranego użytkownika", guild=discord.Object(id=1478885390407434455))
@app_commands.checks.has_role("Administrator")
async def pokaz_walute(interaction: discord.Interaction, member: discord.Member):
    async with db_lock:
        cursor.execute("SELECT doorcal FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
        amount = result[0] if result else 0

    await interaction.response.send_message(
        f"{member.mention} ma **{amount} Doorcal**.", 
        ephemeral=True)

@bot.tree.command(name="waluta", description="Sprawdź ilość waluty", guild=discord.Object(id=1478885390407434455))
async def waluta(interaction: discord.Interaction):
    if interaction.channel.name != CHANNEL_NAMEX:
        await interaction.response.send_message("❌ Ta komenda działa tylko w kanale gry.", ephemeral=True)
        return

    user_id = interaction.user.id
    async with db_lock:
        cursor.execute("SELECT doorcal FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
    doorcal = result[0] if result else 0
    await interaction.response.send_message(f"{interaction.user.mention}, masz **{doorcal} Doorcal**", ephemeral=True)

# --- Komenda handel z różnymi ilościami ---


@bot.tree.command(name="handel", description="Wystaw ofertę handlu", guild=discord.Object(id=1478885390407434455))
@app_commands.describe(
    have="Co oferujesz",
    have_amount="Ile jednostek oferujesz",
    want="Co chcesz otrzymać",
    want_amount="Ile jednostek chcesz otrzymać"
)
async def handel(interaction: discord.Interaction, have: str, have_amount: int, want: str, want_amount: int):
    if interaction.channel.name != HANDEL_CHANNEL:
        await interaction.response.send_message(f"❌ Ta komenda działa tylko w kanale {HANDEL_CHANNEL}", ephemeral=True)
        return

    if have_amount <= 0 or want_amount <= 0:
        await interaction.response.send_message("❌ Ilości muszą być większe od 0!", ephemeral=True)
        return

    user_id = interaction.user.id

    # --- Sprawdzenie czy przedmioty istnieją ---
    if have.lower() != "doorcal" and have not in items_data:
        await interaction.response.send_message(f"❌ Niepoprawny przedmiot `{have}`!", ephemeral=True)
        return
    if want.lower() != "doorcal" and want not in items_data:
        await interaction.response.send_message(f"❌ Niepoprawny przedmiot `{want}`!", ephemeral=True)
        return

    async with db_lock:
        cursor.execute("SELECT items, doorcal FROM punkty WHERE user_id=?", (user_id,))
        result = cursor.fetchone()

    items = json.loads(result[0]) if result and result[0] else {}
    doorcal = result[1] if result else 0

    # --- Sprawdzenie czy użytkownik ma tyle, ile oferuje ---
    if have.lower() == "doorcal":
        if doorcal < have_amount:
            await interaction.response.send_message("❌ Nie masz tyle Doorcal!", ephemeral=True)
            return
    else:
        if items.get(have, 0) < have_amount:
            await interaction.response.send_message(f"❌ Nie masz {have_amount} x {have}", ephemeral=True)
            return

    # --- Widok handlu ---
    class TradeView(View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Akceptuj", style=discord.ButtonStyle.green)
        async def accept(self, interaction_btn: discord.Interaction, button: Button):
            if interaction_btn.user.id == user_id:
                await interaction_btn.response.send_message("❌ Nie możesz zaakceptować własnej oferty!", ephemeral=True)
                return

            async with db_lock:
                # dane akceptora
                cursor.execute("SELECT items, doorcal FROM punkty WHERE user_id=?", (interaction_btn.user.id,))
                result_a = cursor.fetchone()
                items_a = json.loads(result_a[0]) if result_a and result_a[0] else {}
                doorcal_a = result_a[1] if result_a else 0

                # sprawdzenie czy akceptor ma wymagane
                if want.lower() == "doorcal":
                    if doorcal_a < want_amount:
                        await interaction_btn.response.send_message("❌ Nie masz tyle Doorcal!", ephemeral=True)
                        return
                else:
                    if items_a.get(want, 0) < want_amount:
                        await interaction_btn.response.send_message(f"❌ Nie masz {want_amount} x {want}", ephemeral=True)
                        return

                # dane oferenta
                cursor.execute("SELECT items, doorcal FROM punkty WHERE user_id=?", (user_id,))
                result_o = cursor.fetchone()
                items_o = json.loads(result_o[0]) if result_o and result_o[0] else {}
                doorcal_o = result_o[1] if result_o else 0

                # --- Funkcja bezpiecznego odejmowania przedmiotów ---
                def take(item_dict, key, amount):
                    item_dict[key] = item_dict.get(key, 0) - amount
                    if item_dict[key] <= 0:
                        del item_dict[key]

                # oferent oddaje
                if have.lower() == "doorcal":
                    doorcal_o -= have_amount
                else:
                    take(items_o, have, have_amount)

                # akceptor oddaje
                if want.lower() == "doorcal":
                    doorcal_a -= want_amount
                else:
                    take(items_a, want, want_amount)

                # oferent dostaje
                if want.lower() == "doorcal":
                    doorcal_o += want_amount
                else:
                    items_o[want] = items_o.get(want, 0) + want_amount

                # akceptor dostaje
                if have.lower() == "doorcal":
                    doorcal_a += have_amount
                else:
                    items_a[have] = items_a.get(have, 0) + have_amount

                # zapis do bazy
                cursor.execute("UPDATE punkty SET items=?, doorcal=? WHERE user_id=?",
                               (json.dumps(items_o), doorcal_o, user_id))
                cursor.execute("UPDATE punkty SET items=?, doorcal=? WHERE user_id=?",
                               (json.dumps(items_a), doorcal_a, interaction_btn.user.id))
                conn.commit()

            await interaction_btn.message.edit(
                content=f"✅ {interaction.user.mention} wymienił się z {interaction_btn.user.mention}",
                view=None
            )
            await interaction_btn.response.send_message("✅ Handel zakończony!", ephemeral=True)

    view = TradeView()
    msg = await interaction.channel.send(
        f"💱 **OFERTA HANDLU**\n"
        f"{interaction.user.mention} oferuje **{have_amount} x {have}**\n"
        f"w zamian za **{want_amount} x {want}**",
        view=view
    )

    oferty[msg.id] = {
        "oferent": user_id,
        "have": have,
        "have_amount": have_amount,
        "want": want,
        "want_amount": want_amount
    }

    await interaction.response.send_message("✅ Oferta została wystawiona!", ephemeral=True)

# --- Autocomplete ---
@handel.autocomplete("have")
async def have_autocomplete(interaction: discord.Interaction, current: str):
    choices = [app_commands.Choice(name=item['name'], value=key)
               for key, item in items_data.items() if current.lower() in key.lower()]
    if "doorcal".startswith(current.lower()):
        choices.insert(0, app_commands.Choice(name="Doorcal", value="doorcal"))
    # <- zmiana tutaj:
    await interaction.autocomplete(choices[:25])  # zamiast interaction.response.send_autocomplete

@handel.autocomplete("want")
async def want_autocomplete(interaction: discord.Interaction, current: str):
    choices = [app_commands.Choice(name=item['name'], value=key)
               for key, item in items_data.items() if current.lower() in key.lower()]
    if "doorcal".startswith(current.lower()):
        choices.insert(0, app_commands.Choice(name="Doorcal", value="doorcal"))
    # <- zmiana tutaj:
    await interaction.autocomplete(choices[:25])  # zamiast interaction.response.send_autocomplete

@bot.tree.command(name="backup", description="Ręczny backup bazy danych", guild=discord.Object(id=1478885390407434455))
async def backup(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tylko admin może zrobić backup.", ephemeral=True)
        return

    await interaction.response.send_message("💾 Tworzę backup...", ephemeral=True)

    async with db_lock:
        conn.commit()
        upload_db()

    await interaction.followup.send("✅ Backup zapisany na GitHub!", ephemeral=True)

bot.run(TOKEN)
