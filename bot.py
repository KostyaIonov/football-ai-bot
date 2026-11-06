import os
import random
import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import quote
import aiohttp
from aiohttp import web
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from openai import AsyncOpenAI

# ================= НАСТРОЙКИ СЕРВЕРА И КЛЮЧИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "gsk_" + "4Tsu0D9a7WpeKXgsfCEBWGdyb3FYh36zWsKthL2t6jJ1ROtV1dqH")
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Ссылка на облачную PostgreSQL (Supabase / Neon)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Клиент 1: Google Gemini (Приоритетный аналитический движок)
gemini_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY or "dummy",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

# Клиент 2: Groq (Сверхбыстрый резерв)
groq_client = AsyncOpenAI(
    api_key=GROQ_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# Клиент 3: OpenRouter
or_client = AsyncOpenAI(
    api_key=AI_API_KEY or "dummy",
    base_url="https://openrouter.ai/api/v1",
    default_headers={"HTTP-Referer": "https://render.com", "X-Title": "Football Pro Bot"}
)

# ================= НАДЕЖНЫЙ СЛОЙ БАЗЫ ДАННЫХ (PostgreSQL + SQLite) =================
class Database:
    def __init__(self):
        self.use_pg = bool(DATABASE_URL)
        self.pg_pool = None
        self.sqlite_path = "football_bot.db"

    async def init(self):
        if self.use_pg:
            import asyncpg
            self.pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        balance DOUBLE PRECISION DEFAULT 1000.0,
                        wins INT DEFAULT 0,
                        losses INT DEFAULT 0,
                        profit DOUBLE PRECISION DEFAULT 0.0,
                        is_vip INT DEFAULT 0,
                        last_bonus TEXT DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS bets (
                        bet_id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        match_title TEXT,
                        pick TEXT,
                        amount INT,
                        odds DOUBLE PRECISION,
                        status TEXT DEFAULT 'pending'
                    );
                """)
            logging.info("Подключена облачная база данных PostgreSQL!")
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        balance REAL DEFAULT 1000.0,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        profit REAL DEFAULT 0.0,
                        is_vip INTEGER DEFAULT 0,
                        last_bonus TEXT DEFAULT ''
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS bets (
                        bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        match_title TEXT,
                        pick TEXT,
                        amount INTEGER,
                        odds REAL,
                        status TEXT DEFAULT 'pending'
                    )
                """)
                await db.commit()
            logging.info("Подключена локальная база данных SQLite!")

    async def get_or_create_user(self, user_id: int, username: str):
        uname = username or f"Player_{str(user_id)[-4:]}"
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
                if not row:
                    await conn.execute(
                        "INSERT INTO users (user_id, username, balance) VALUES ($1, $2, 1000.0)",
                        user_id, uname
                    )
                    row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
                return dict(row)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    await db.execute(
                        "INSERT INTO users (user_id, username, balance) VALUES (?, ?, 1000.0)",
                        (user_id, uname)
                    )
                    await db.commit()
                    async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                        row = await cur.fetchone()
                return dict(row)

    async def claim_daily_bonus(self, user_id: int) -> tuple[bool, int]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        user = await self.get_or_create_user(user_id, "")
        if user["last_bonus"] == today_str:
            return False, 0
        bonus = 1000 if user["is_vip"] else 250
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET balance = balance + $1, last_bonus = $2 WHERE user_id = $3",
                    bonus, today_str, user_id
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id = ?",
                    (bonus, today_str, user_id)
                )
                await db.commit()
        return True, bonus

    async def place_and_simulate_bet(self, user_id: int, username: str, match_title: str, pick: str, amount: int, odds: float, win_prob: float) -> dict:
        user = await self.get_or_create_user(user_id, username)
        if user["balance"] < amount:
            return {"ok": False, "error": "Недостаточно FC на балансе! Забери ежедневный бонус в Личном кабинете."}

        # Симуляция исхода с учетом реальной математической вероятности (+ бонус удачи для азарта)
        roll = random.uniform(0, 100)
        is_win = roll <= (win_prob + 5.0)

        if is_win:
            payout = round(amount * odds, 1)
            net_profit = round(payout - amount, 1)
            new_balance = round(user["balance"] + net_profit, 1)
            wins_inc, loss_inc = 1, 0
            status = "win"
        else:
            payout = 0.0
            net_profit = -amount
            new_balance = round(user["balance"] - amount, 1)
            wins_inc, loss_inc = 0, 1
            status = "loss"

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET balance = $1, wins = wins + $2, losses = losses + $3, profit = profit + $4 WHERE user_id = $5",
                    new_balance, wins_inc, loss_inc, net_profit, user_id
                )
                await conn.execute(
                    "INSERT INTO bets (user_id, match_title, pick, amount, odds, status) VALUES ($1, $2, $3, $4, $5, $6)",
                    user_id, match_title, pick, amount, odds, status
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE users SET balance = ?, wins = wins + ?, losses = losses + ?, profit = profit + ? WHERE user_id = ?",
                    (new_balance, wins_inc, loss_inc, net_profit, user_id)
                )
                await db.execute(
                    "INSERT INTO bets (user_id, match_title, pick, amount, odds, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, match_title, pick, amount, odds, status)
                )
                await db.commit()

        return {
            "ok": True,
            "is_win": is_win,
            "payout": payout,
            "net_profit": net_profit,
            "new_balance": new_balance
        }

    async def get_leaderboard(self) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT username, balance, wins, losses FROM users ORDER BY balance DESC LIMIT 10")
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT username, balance, wins, losses FROM users ORDER BY balance DESC LIMIT 10") as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def get_recent_bets(self, user_id: int) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT match_title, pick, amount, odds, status FROM bets WHERE user_id = $1 ORDER BY bet_id DESC LIMIT 5", user_id)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT match_title, pick, amount, odds, status FROM bets WHERE user_id = ? ORDER BY bet_id DESC LIMIT 5", (user_id,)) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

db_manager = Database()

# ================= МУЛЬТИ-ШЛЮЗ ИИ С GEMINI 2.5 FLASH =================
async def ask_ai(prompt: str, system_prompt: str = "Ты элитный футбольный аналитик и математик.") -> str | None:
    # 1. Пробуем Google Gemini 2.5 Flash (если добавлен GEMINI_API_KEY)
    if GEMINI_API_KEY:
        try:
            resp = await asyncio.wait_for(
                gemini_client.chat.completions.create(
                    model="gemini-2.5-flash",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4,
                    max_tokens=450
                ),
                timeout=8.0
            )
            if resp.choices and resp.choices[0].message.content:
                return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"Gemini пропущен: {e}")

    # 2. Пробуем быстрый Groq с сервера США
    for groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        try:
            resp = await asyncio.wait_for(
                groq_client.chat.completions.create(
                    model=groq_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4,
                    max_tokens=400
                ),
                timeout=7.0
            )
            if resp.choices and resp.choices[0].message.content:
                return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"Groq ({groq_model}) пропущен: {e}")

    # 3. Резервный Pollinations
    try:
        full_text = quote(f"{system_prompt}\n{prompt}")
        url = f"https://text.pollinations.ai/{full_text}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    ans = await r.text()
                    if ans and len(ans.strip()) > 15 and "<!DOCTYPE" not in ans:
                        return ans.strip()
    except Exception as e:
        logging.warning(f"Pollinations пропущен: {e}")

    return None

# ================= АНАЛИТИЧЕСКИЙ ДВИЖОК И БАЗА МАТЧЕЙ =================
def calculate_ai_probabilities(odds: dict) -> dict:
    raw_p1, raw_x, raw_p2 = 1 / odds["p1"], 1 / odds["x"], 1 / odds["p2"]
    margin_sum = raw_p1 + raw_x + raw_p2
    return {
        "p1": round((raw_p1 / margin_sum) * 100, 1),
        "x": round((raw_x / margin_sum) * 100, 1),
        "p2": round((raw_p2 / margin_sum) * 100, 1),
        "margin": round((margin_sum - 1) * 100, 2)
    }

def smart_local_match_analysis(match: dict, probs: dict) -> str:
    t1, t2 = match["teams"].split(" vs ")
    odds = match["odds"]
    p1, x, p2 = probs["p1"], probs["x"], probs["p2"]

    if p1 >= 58:
        style = f"⚔️ **Тактический расклад:** {t1} доминирует по метрикам xG и домашнему прессингу (чистая вероятность {p1}%). Ожидается давление с первых минут."
        bet = f"🎯 **Лучшая ставка (Value):** Победа {t1} (П1) за `{odds['p1']}`"
    elif p2 >= 50:
        style = f"⚔️ **Тактический расклад:** {t2} сильнее в переходных фазах и реализации моментов ({p2}% против {p1}%)."
        bet = f"🎯 **Лучшая ставка (Value):** Победа {t2} (П2) за `{odds['p2']}`"
    else:
        style = f"⚔️ **Тактический расклад:** Близкий по силам матч ({p1}% на {p2}%). Высока вероятность обмена голами."
        bet = f"🎯 **Лучшая ставка (Value):** Обе забьют (ДА) / 1Х за `{round(odds['p1']*0.7, 2)}`"
    return f"{style}\n\n{bet}"

def smart_local_express(db: dict) -> str:
    picks = []
    total_odd = 1.0
    for l_val in db.values():
        for m in l_val["matches"].values():
            if len(picks) >= 6:
                break
            t1, t2 = m["teams"].split(" vs ")
            o = m["odds"]
            probs = calculate_ai_probabilities(o)
            if probs["p1"] >= 54:
                bet_str, k = f"Победа {t1} (П1)", o["p1"]
            else:
                bet_str, k = f"{t1} не проиграет (1Х) + ТБ 1.5", round(o["p1"] * 0.74, 2)
            total_odd *= k
            picks.append(f"{len(picks)+1}. ⚽ **{m['teams']}**\n   🎯 *{bet_str}* — кэф `{k}`")
        if len(picks) >= 6:
            break
    return "\n\n".join(picks) + f"\n\n━━━━━━━━━━━━━━━━━━\n📈 **Итоговый коэффициент:** `{round(total_odd, 2)}`"

def get_base_matches():
    today = datetime.now()
    d = [(today + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(1, 8)]
    return {
        "ucl": {
            "title": "🏆 Лига Чемпионов УЕФА",
            "matches": {
                "m1": {"teams": "Реал Мадрид vs Милан", "date": f"{d[0]}, 23:00 МСК", "odds": {"p1": 1.55, "x": 4.40, "p2": 5.80}},
                "m2": {"teams": "Барселона vs Бавария", "date": f"{d[1]}, 23:00 МСК", "odds": {"p1": 2.40, "x": 3.85, "p2": 2.70}},
                "m3": {"teams": "Интер vs Арсенал", "date": f"{d[2]}, 23:00 МСК", "odds": {"p1": 2.65, "x": 3.25, "p2": 2.75}},
                "m4": {"teams": "ПСЖ vs Манчестер Сити", "date": f"{d[4]}, 23:00 МСК", "odds": {"p1": 2.10, "x": 3.50, "p2": 3.20}}
            }
        },
        "epl": {
            "title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)",
            "matches": {
                "m1": {"teams": "Арсенал vs Ливерпуль", "date": f"{d[1]}, 19:30 МСК", "odds": {"p1": 2.20, "x": 3.40, "p2": 3.30}},
                "m2": {"teams": "Манчестер Юнайтед vs Челси", "date": f"{d[2]}, 18:00 МСК", "odds": {"p1": 2.50, "x": 3.30, "p2": 2.80}},
                "m3": {"teams": "Тоттенхэм vs Астон Вилла", "date": f"{d[3]}, 17:00 МСК", "odds": {"p1": 1.95, "x": 3.70, "p2": 3.60}}
            }
        },
        "laliga": {
            "title": "🇪🇸 Ла Лига (Испания)",
            "matches": {
                "m1": {"teams": "Реал Мадрид vs Барселона", "date": f"{d[1]}, 22:00 МСК", "odds": {"p1": 2.30, "x": 3.50, "p2": 3.00}},
                "m2": {"teams": "Атлетико Мадрид vs Вильярреал", "date": f"{d[2]}, 20:30 МСК", "odds": {"p1": 1.75, "x": 3.60, "p2": 4.80}}
            }
        },
        "seriea": {
            "title": "🇮🇹 Серия А (Италия)",
            "matches": {
                "m1": {"teams": "Интер vs Ювентус", "date": f"{d[1]}, 20:00 МСК", "odds": {"p1": 2.05, "x": 3.30, "p2": 3.80}},
                "m2": {"teams": "Милан vs Наполи", "date": f"{d[2]}, 22:45 МСК", "odds": {"p1": 2.45, "x": 3.20, "p2": 3.05}}
            }
        },
        "bundesliga": {
            "title": "🇩🇪 Бундеслига (Германия)",
            "matches": {
                "m1": {"teams": "Бавария vs Боруссия Дортмунд", "date": f"{d[1]}, 19:30 МСК", "odds": {"p1": 1.60, "x": 4.20, "p2": 5.00}},
                "m2": {"teams": "Байер vs РБ Лейпциг", "date": f"{d[3]}, 17:30 МСК", "odds": {"p1": 2.15, "x": 3.60, "p2": 3.10}}
            }
        },
        "ligue1": {
            "title": "🇫🇷 Лига 1 (Франция)",
            "matches": {
                "m1": {"teams": "ПСЖ vs Монако", "date": f"{d[2]}, 21:00 МСК", "odds": {"p1": 1.45, "x": 4.50, "p2": 6.50}},
                "m2": {"teams": "Марсель vs Лион", "date": f"{d[3]}, 22:00 МСК", "odds": {"p1": 2.25, "x": 3.40, "p2": 3.10}}
            }
        }
    }

# ================= КЛАВИАТУРЫ И ИНТЕРФЕЙС =================
def main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Личный кабинет", callback_data="profile")
    builder.button(text="🏆 Топ-10 капперов", callback_data="leaderboard")
    builder.button(text="🏆 Лига Чемпионов", callback_data="league:ucl")
    builder.button(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)", callback_data="league:epl")
    builder.button(text="🇪🇸 Ла Лига (Испания)", callback_data="league:laliga")
    builder.button(text="🇮🇹 Серия А (Италия)", callback_data="league:seriea")
    builder.button(text="🇩🇪 Бундеслига (Германия)", callback_data="league:bundesliga")
    builder.button(text="🇫🇷 Лига 1 (Франция)", callback_data="league:ligue1")
    builder.button(text="⚡ Экспресс дня (6 матчей)", callback_data="express_day")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

def profile_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Забрать бонус (+250 FC)", callback_data="claim_bonus")
    builder.button(text="📜 История моих ставок", callback_data="my_bets")
    builder.button(text="💎 Статус PRO и Пополнение", callback_data="vip_shop")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def matches_kb(league_key: str, matches_dict: dict):
    builder = InlineKeyboardBuilder()
    for match_id, data in matches_dict.items():
        short_date = data['date'].split(',')[0]
        builder.button(text=f"⚽ {data['teams']} ({short_date})", callback_data=f"match:{league_key}:{match_id}")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def match_betting_kb(league_key: str, match_id: str, odds: dict):
    builder = InlineKeyboardBuilder()
    # Кнопки быстрой ставки по 250 FC на выбранный исход
    builder.button(text=f"🎲 П1 ({odds['p1']}) • 250 FC", callback_data=f"bet:{league_key}:{match_id}:p1:250")
    builder.button(text=f"🎲 Х ({odds['x']}) • 250 FC", callback_data=f"bet:{league_key}:{match_id}:x:250")
    builder.button(text=f"🎲 П2 ({odds['p2']}) • 250 FC", callback_data=f"bet:{league_key}:{match_id}:p2:250")
    builder.button(text=f"🔥 Ва-банк 500 FC на Фаворита", callback_data=f"bet:{league_key}:{match_id}:fav:500")
    builder.button(text="⬅️ К списку матчей", callback_data=f"league:{league_key}")
    builder.button(text="👤 Мой баланс", callback_data="profile")
    builder.adjust(3, 1, 2)
    return builder.as_markup()

# ================= ОБРАБОТЧИКИ СОБЫТИЙ =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = await db_manager.get_or_create_user(message.from_user.id, message.from_user.username)
    text = (
        f"👋 **Привет, {user['username']}! Добро пожаловать в Football AI Pro.**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Твой стартовый банк:** `{user['balance']} FC` (Football Coins)\n"
        f"🤖 **ИИ-аналитика:** Топ-5 лиг Европы и Лига Чемпионов\n"
        f"🎲 **Симулятор ставок:** Делай ставки на матчи, соревнуйся в рейтинге и забирай награды!\n\n"
        f"👇 Выбери раздел в меню ниже:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_main")
async def process_back_main(callback: CallbackQuery):
    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    text = (
        f"🏠 **Главное меню Football AI Pro**\n"
        f"💰 Баланс: `{user['balance']} FC` | 🏆 Побед: `{user['wins']}`\n\n"
        f"👇 Выбери турнир, профиль или Экспресс дня:"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery):
    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    total_bets = user["wins"] + user["losses"]
    winrate = round((user["wins"] / total_bets) * 100, 1) if total_bets > 0 else 0.0
    status_str = "💎 PRO-Каппер" if user["is_vip"] else "🎯 Игрок Лиги"
    profit_sign = "+" if user["profit"] >= 0 else ""

    text = (
        f"👤 **ЛИЧНЫЙ КАБИНЕТ КАППЕРА**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Игрок: **{user['username']}** (`{user['user_id']}`)\n"
        f"🏅 Статус: **{status_str}**\n"
        f"💰 Виртуальный банк: **`{user['balance']} FC`**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Статистика ставок:**\n"
        f"• Всего купонов: `{total_bets}` (✅ `{user['wins']}` | ❌ `{user['losses']}`)\n"
        f"• Процент прохода (Winrate): **`{winrate}%`**\n"
        f"• Чистый профит (ROI): **`{profit_sign}{round(user['profit'], 1)} FC`**\n\n"
        f"💡 *Делай ставки в карточках матчей и поднимайся в Топ-10!*"
    )
    await callback.message.edit_text(text, reply_markup=profile_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "claim_bonus")
async def process_claim_bonus(callback: CallbackQuery):
    ok, amount = await db_manager.claim_daily_bonus(callback.from_user.id)
    if ok:
        await callback.answer(f"🎉 Начислено +{amount} FC на твой баланс!", show_alert=True)
        await process_profile(callback)
    else:
        await callback.answer("⏳ Ты уже забирал бонус сегодня! Возвращайся завтра.", show_alert=True)

@dp.callback_query(F.data == "my_bets")
async def process_my_bets(callback: CallbackQuery):
    bets = await db_manager.get_recent_bets(callback.from_user.id)
    if not bets:
        text = "📜 **История ставок пуста.**\n\nОткрой любую лигу, выбери матч и сделай свою первую ставку под разбором ИИ!"
    else:
        lines = []
        for b in bets:
            icon = "✅ Выигрыш" if b["status"] == "win" else "❌ Проигрыш"
            lines.append(f"• **{b['match_title']}**\n  Исход: `{b['pick']}` (кэф `{b['odds']}`) | Сумма: `{b['amount']} FC` — {icon}")
        text = "📜 **ТВОИ ПОСЛЕДНИЕ 5 СТАВОК:**\n━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в профиль", callback_data="profile")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "vip_shop")
async def process_vip_shop(callback: CallbackQuery):
    text = (
        "💎 **МАГАЗИН И PRO-ПРИВИЛЕГИИ**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔥 **Подписка PRO-Каппер (249 ₽/мес):**\n"
        "• Ежедневный бонус **+1 000 FC** вместо 250 FC\n"
        "• Доступ к закрытым VIP-экспрессам с кэфом 10+\n"
        "• Значок 💎 в глобальной таблице лидеров\n\n"
        "💰 **Пакеты игровой валюты:**\n"
        "• Пакет «Старт»: `+5 000 FC` — 99 ₽ (50 ⭐️)\n"
        "• Пакет «Магнат»: `+25 000 FC` — 299 ₽ (150 ⭐️)\n\n"
        "⚙️ *Автоматическая оплата через Telegram Stars скоро откроется!*"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в профиль", callback_data="profile")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "leaderboard")
async def process_leaderboard(callback: CallbackQuery):
    top = await db_manager.get_leaderboard()
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for idx, u in enumerate(top):
        prefix = medals[idx] if idx < 3 else f"**{idx+1}.**"
        lines.append(f"{prefix} **{u['username']}** — `{round(u['balance'], 1)} FC` (Побед: {u['wins']})")
    body = "\n".join(lines) if lines else "Рейтинг пока формируется."
    text = f"🏆 **ТОП-10 КАППЕРОВ ПРОЕКТА**\n━━━━━━━━━━━━━━━━━━\n\n{body}"

    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Мой профиль", callback_data="profile")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "express_day")
async def process_express(callback: CallbackQuery):
    await callback.message.edit_text("⚡ *ИИ собирает Экспресс из 6 матчей...*", parse_mode="Markdown")
    db = get_base_matches()
    all_matches = [f"{m['teams']} (П1:{m['odds']['p1']}, Х:{m['odds']['x']}, П2:{m['odds']['p2']})" for l in db.values() for m in l["matches"].values()]
    prompt = (
        f"Вот 6 главных матчей недели:\n" + "\n".join(all_matches[:6]) + "\n\n"
        f"Составь «Экспресс дня» строго из этих 6 матчей. Для каждого напиши 1 строчкой: "
        f"Команды — Лучшая надежная ставка и кэф. В конце укажи общий коэффициент."
    )
    express_text = await ask_ai(prompt) or smart_local_express(db)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    await callback.message.edit_text(f"🔥 **ЭКСПРЕСС ДНЯ (6 МАТЧЕЙ)**\n━━━━━━━━━━━━━━━━━━\n\n{express_text}", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("league:"))
async def process_league_select(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    db = get_base_matches()
    league_data = db.get(league_key)
    matches = league_data["matches"] if league_data else {}
    text = f"**{league_data['title']}**\n📅 Матчи на ближайшие 7 дней (выбери для анализа и ставки):"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("match:"))
async def process_match_select(callback: CallbackQuery):
    _, league_key, match_id = callback.data.split(":")
    db = get_base_matches()
    match = db[league_key]["matches"][match_id]
    league_title = db[league_key]["title"]
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)

    await callback.message.edit_text(f"🧠 *ИИ анализирует {match['teams']}...*", parse_mode="Markdown")
    prompt = (
        f"Турнир: {league_title}. Матч: {match['teams']}.\n"
        f"Коэффициенты: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}.\n"
        f"Чистые вероятности: П1={probs['p1']}%, Х={probs['x']}%, П2={probs['p2']}%\n"
        f"Дай краткий разбор (до 70 слов) в 2 пункта:\n"
        f"1. ⚔️ Тактический анализ исхода.\n"
        f"2. 🎯 Самая лучшая ставка (Value Bet) с кэфом."
    )
    ai_verdict = await ask_ai(prompt) or smart_local_match_analysis(match, probs)

    text = (
        f"⚽ **{match['teams']}**\n"
        f"🕒 Дата: {match['date']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Коэффициенты (Маржа: {probs['margin']}%):**\n"
        f"• П1: `{odds['p1']}` | Х: `{odds['x']}` | П2: `{odds['p2']}`\n\n"
        f"🧮 **Вероятности:** П1: **{probs['p1']}%** | Х: **{probs['x']}%** | П2: **{probs['p2']}%**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Анализ и лучшая ставка:**\n\n{ai_verdict}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 **Сделать виртуальную ставку (моментальный расчет):**"
    )
    await callback.message.edit_text(text, reply_markup=match_betting_kb(league_key, match_id, odds))
    await callback.answer()

@dp.callback_query(F.data.startswith("bet:"))
async def process_bet_action(callback: CallbackQuery):
    _, league_key, match_id, pick_code, amount_str = callback.data.split(":")
    amount = int(amount_str)
    db = get_base_matches()
    match = db[league_key]["matches"][match_id]
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)

    if pick_code == "fav":
        pick_code = "p1" if probs["p1"] >= probs["p2"] else "p2"

    pick_names = {"p1": "П1 (Победа 1)", "x": "Х (Ничья)", "p2": "П2 (Победа 2)"}
    chosen_odd = odds[pick_code]
    chosen_prob = probs[pick_code]

    res = await db_manager.place_and_simulate_bet(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        match_title=match["teams"],
        pick=pick_names[pick_code],
        amount=amount,
        odds=chosen_odd,
        win_prob=chosen_prob
    )

    if not res["ok"]:
        await callback.answer(f"⚠️ {res['error']}", show_alert=True)
        return

    if res["is_win"]:
        alert_text = (
            f"🎉 ПОБЕДА! Ставка сыграла!\n"
            f"Матч: {match['teams']}\n"
            f"Исход: {pick_names[pick_code]} (кэф {chosen_odd})\n"
            f"💰 Выплата: +{res['payout']} FC (Чистыми: +{res['net_profit']} FC)\n"
            f"🏦 Новый баланс: {res['new_balance']} FC"
        )
    else:
        alert_text = (
            f"❌ Увы, сенсация в матче! Ставка не зашла.\n"
            f"Матч: {match['teams']}\n"
            f"Потеряно: -{amount} FC\n"
            f"🏦 Остаток на балансе: {res['new_balance']} FC"
        )

    await callback.answer(alert_text, show_alert=True)

# ================= ВЕБ-СЕРВЕР И ЗАПУСК =================
async def handle_ping(request):
    return web.Response(text="Football AI Pro is running 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    logging.basicConfig(level=logging.INFO)
    await db_manager.init()
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
