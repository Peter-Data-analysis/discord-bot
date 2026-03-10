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
from discord import app_commands

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
bot.tree.sync()

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
    # ignorujemy wiadomości od botów
    if message.author.bot:
        return

    # Kanał gry — usuwamy wszystko, co nie jest slash command
    if message.channel.name == CHANNEL_NAME:
        if not message.content.startswith("/drzwi"):
            await message.delete()
            return

    # reszta bot.process_commands tylko dla prefixowych (jeśli jeszcze są jakieś)
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
@bot.tree.command(name="drzwi", description="Wybierz drzwi w aktualnej rundzie gry")
async def drzwi(interaction: discord.Interaction, numer: int):
    if interaction.channel.name != CHANNEL_NAME:
        return

    global stop_runda
    if stop_runda:
        await interaction.response.send_message("⏸ Gra została wstrzymana!", ephemeral=True)
        return

    if numer < 1 or numer > 5:
        await interaction.response.send_message("❌ Wybierz drzwi od 1 do 5!", ephemeral=True)
        return

    if interaction.user.id in wybory:
        await interaction.response.send_message("❌ Już wybrałeś drzwi w tej rundzie!", ephemeral=True)
        return

    wybory[interaction.user.id] = numer
    await interaction.response.send_message(f"{interaction.user.mention} wybrał drzwi **{numer}** 🚪", ephemeral=True)

# --- Komenda /punkty ---
@bot.tree.command(name="punkty", description="Sprawdź swoje punkty tygodniowe i all-time")
async def punkty(interaction: discord.Interaction):
    if interaction.channel.name != CHANNEL_NAMEX:
        return
    user_id = interaction.user.id
    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
    if result:
        week, alltime = result
        await interaction.response.send_message(f"{interaction.user.mention}, masz **{week} punktów tygodniowych** i **{alltime} punktów all-time** 🎉")
    else:
        await interaction.response.send_message(f"{interaction.user.mention}, jeszcze nie masz punktów. Zacznij grać!")

# --- Komenda /top ---
@bot.tree.command(name="top", description="Pokaż TOP 20 graczy all-time")
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
@bot.tree.command(name="czas_ranking", description="Sprawdź, za ile czasu rozpocznie się kolejny ranking tygodniowy")
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
@bot.tree.command(name="punkty_dodaj", description="Dodaj punkty wybranemu użytkownikowi")
@app_commands.checks.has_role("Administrator")
async def punkty_dodaj(interaction: discord.Interaction, member: discord.Member, ilosc: int):
    if ilosc <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią liczbę punktów!", ephemeral=True)
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
    await interaction.response.send_message(f"✅ Dodano {ilosc} punktów użytkownikowi {member.mention}.")

@bot.tree.command(name="punkty_usun", description="Usuń punkty wybranemu użytkownikowi")
@app_commands.checks.has_role("Administrator")
async def punkty_usun(interaction: discord.Interaction, member: discord.Member, ilosc: int):
    if ilosc <= 0:
        await interaction.response.send_message("❌ Podaj dodatnią liczbę punktów!", ephemeral=True)
        return

    async with db_lock:
        cursor.execute("SELECT week_points, alltime_points FROM punkty WHERE user_id = ?", (member.id,))
        result = cursor.fetchone()
        if result:
            week, alltime = result
            new_week = max(week - ilosc, 0)
            new_alltime = max(alltime - ilosc, 0)
            cursor.execute("UPDATE punkty SET week_points = ?, alltime_points = ? WHERE user_id = ?",
                           (new_week, new_alltime, member.id))
            conn.commit()
            await interaction.response.send_message(f"✅ Usunięto {ilosc} punktów użytkownikowi {member.mention}.")
        else:
            await interaction.response.send_message(f"❌ Użytkownik {member.mention} nie ma punktów w bazie.")

# --- Komenda /usun_dane ---
@bot.tree.command(name="usun_dane", description="Usuń wszystkie dane użytkownika z bazy")
@app_commands.checks.has_role("Administrator")
async def usun_dane(interaction: discord.Interaction, member: discord.Member):
    async with db_lock:
        cursor.execute("DELETE FROM punkty WHERE user_id = ?", (member.id,))
        conn.commit()
    await interaction.response.send_message(f"🗑 Dane użytkownika {member.mention} zostały usunięte z bazy.")

# --- Komenda /punkty_reset ---
@bot.tree.command(name="punkty_reset", description="Zresetuj punkty tygodniowe wszystkich użytkowników")
@app_commands.checks.has_role("Administrator")
async def punkty_reset(interaction: discord.Interaction):
    async with db_lock:
        cursor.execute("UPDATE punkty SET week_points = 0")
        conn.commit()
    await interaction.response.send_message("♻️ Punkty tygodniowe wszystkich użytkowników zostały zresetowane.")

# --- Komenda /punkty_pokaz ---
@bot.tree.command(name="punkty_pokaz", description="Pokaż punkty wybranego użytkownika")
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
@bot.tree.command(name="runda_stop", description="Zatrzymaj aktualną rundę gry")
@app_commands.checks.has_role("Administrator")
async def runda_stop(interaction: discord.Interaction):
    global stop_runda, stop_msg
    stop_runda = True
    channel = discord.utils.get(interaction.guild.text_channels, name=CHANNEL_NAME)
    if channel:
        stop_msg = await channel.send("⏹ Aktualna runda została zatrzymana. Kolejne rundy nie będą się rozpoczynać")

@bot.tree.command(name="runda_start", description="Wznów grę po zatrzymaniu rundy")
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
@bot.tree.command(name="sklep", description="Pokaż dostępne przedmioty w sklepie")
async def sklep(interaction: discord.Interaction):
    msg = "🛒 **SKLEP LUCKY DOORS**\n\n"
    for key, item in items_data.items():
        msg += f"**{item['name']}** — {item['cena']} pkt\n{item['opis']}\n\n"
    await interaction.response.send_message(msg)

# --- Komenda /inventory ---
@bot.tree.command(name="itemy", description="Pokaż swoje przedmioty")
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
        await interaction.response.send_message(f"{interaction.user.mention}, nie masz jeszcze żadnych przedmiotów.")
    else:
        tekst = f"{interaction.user.mention}, oto Twoje przedmioty:\n"
        for item, ilosc in items.items():
            tekst += f"- {item}: {ilosc}\n"
        await interaction.response.send_message(tekst)

# --- Komenda administracyjna /przedmiot_dodaj ---
@bot.tree.command(name="przedmiot_dodaj", description="Dodaj określony przedmiot użytkownikowi")
@app_commands.checks.has_role("Administrator")
async def przedmiot_dodaj(interaction: discord.Interaction, member: discord.Member, item_key: str, ilosc: int):
    if ilosc <= 0:
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
        user_items[item_key] = user_items.get(item_key, 0) + ilosc
        cursor.execute("UPDATE punkty SET items=? WHERE user_id=?", (json.dumps(user_items), user_id))
        conn.commit()

    await interaction.response.send_message(f"✅ Dodano **{ilosc} x {items_data[item_key]['name']}** użytkownikowi {member.mention}.", ephemeral=True)































