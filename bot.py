import os
import re
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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI

# ================= НАСТРОЙКИ СЕРВЕРА И КЛЮЧИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "gsk_" + "4Tsu0D9a7WpeKXgsfCEBWGdyb3FYh36zWsKthL2t6jJ1ROtV1dqH")
DATABASE_URL = os.getenv("DATABASE_URL", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Корзина для сборки кастомных экспрессов
USER_SLIPS = {}

class BetStates(StatesGroup):
    waiting_for_custom_amount = State()

# Клиенты ИИ
gemini_client = AsyncOpenAI(
    api_key=GEMINI_API_KEY or "dummy",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)
groq_client = AsyncOpenAI(
    api_key=GROQ_KEY,
    base_url="https://api.groq.com/openai/v1"
)
or_client = AsyncOpenAI(
    api_key=AI_API_KEY or "dummy",
    base_url="https://openrouter.ai/api/v1",
    default_headers={"HTTP-Referer": "https://render.com", "X-Title": "Football Pro Bot"}
)

# ================= ВРЕМЯ И ЧИСТКА ФОРМАТИРОВАНИЯ =================
def now_msk() -> datetime:
    return datetime.utcnow() + timedelta(hours=3)

def parse_match_end_ts(date_str: str) -> int:
    try:
        clean = date_str.replace(" МСК", "").strip()
        start_dt = datetime.strptime(clean, "%d.%m.%Y, %H:%M")
        end_dt = start_dt + timedelta(minutes=115)
        return int(end_dt.timestamp())
    except Exception:
        return int((now_msk() + timedelta(hours=2)).timestamp())

def clean_ai_text(text: str) -> str:
    """Преобразует Markdown от ИИ в чистый HTML без лишних символов"""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = text.replace("*", "• ")
    return text.strip()

# ================= БАЗА ДАННЫХ (PostgreSQL + SQLite) =================
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
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS bet_type TEXT DEFAULT 'single';
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS win_prob DOUBLE PRECISION DEFAULT 50.0;
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS settle_ts BIGINT DEFAULT 0;
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS created_at TEXT DEFAULT '';
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS score_result TEXT DEFAULT '';
                """)
            logging.info("Облачная БД PostgreSQL подключена!")
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
                        status TEXT DEFAULT 'pending',
                        bet_type TEXT DEFAULT 'single',
                        win_prob REAL DEFAULT 50.0,
                        settle_ts INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT '',
                        score_result TEXT DEFAULT ''
                    )
                """)
                for col_def in [
                    "bet_type TEXT DEFAULT 'single'",
                    "win_prob REAL DEFAULT 50.0",
                    "settle_ts INTEGER DEFAULT 0",
                    "created_at TEXT DEFAULT ''",
                    "score_result TEXT DEFAULT ''"
                ]:
                    try:
                        await db.execute(f"ALTER TABLE bets ADD COLUMN {col_def}")
                    except Exception:
                        pass
                await db.commit()
            logging.info("Локальная БД SQLite подключена!")

    async def get_or_create_user(self, user_id: int, username: str = ""):
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
        today_str = now_msk().strftime("%Y-%m-%d")
        user = await self.get_or_create_user(user_id)
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

    async def create_pending_bet(self, user_id: int, username: str, match_title: str, pick: str, amount: int, odds: float, win_prob: float, settle_ts: int, bet_type: str = "single") -> dict:
        user = await self.get_or_create_user(user_id, username)
        if amount < 10:
            return {"ok": False, "error": "Минимальная сумма ставки — 10 FC!"}
        if user["balance"] < amount:
            return {"ok": False, "error": f"Недостаточно средств! Твой баланс: {round(user['balance'], 1)} FC."}

        new_balance = round(user["balance"] - amount, 1)
        created_str = now_msk().strftime("%d.%m %H:%M")

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE users SET balance = $1 WHERE user_id = $2", new_balance, user_id)
                bet_id = await conn.fetchval("""
                    INSERT INTO bets (user_id, match_title, pick, amount, odds, status, bet_type, win_prob, settle_ts, created_at)
                    VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8, $9) RETURNING bet_id
                """, user_id, match_title, pick, amount, odds, bet_type, win_prob, settle_ts, created_str)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
                cur = await db.execute("""
                    INSERT INTO bets (user_id, match_title, pick, amount, odds, status, bet_type, win_prob, settle_ts, created_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """, (user_id, match_title, pick, amount, odds, bet_type, win_prob, settle_ts, created_str))
                bet_id = cur.lastrowid
                await db.commit()

        return {
            "ok": True,
            "bet_id": bet_id,
            "new_balance": new_balance,
            "potential_win": round(amount * odds, 1)
        }

    async def get_user_bets(self, user_id: int, active_only: bool = True) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                q = "SELECT * FROM bets WHERE user_id = $1 AND status = 'pending' ORDER BY bet_id DESC LIMIT 15" if active_only else "SELECT * FROM bets WHERE user_id = $1 AND status != 'pending' ORDER BY bet_id DESC LIMIT 15"
                rows = await conn.fetch(q, user_id)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                q = "SELECT * FROM bets WHERE user_id = ? AND status = 'pending' ORDER BY bet_id DESC LIMIT 15" if active_only else "SELECT * FROM bets WHERE user_id = ? AND status != 'pending' ORDER BY bet_id DESC LIMIT 15"
                async with db.execute(q, (user_id,)) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def get_due_pending_bets(self, current_ts: int) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM bets WHERE status = 'pending' AND settle_ts <= $1", current_ts)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM bets WHERE status = 'pending' AND settle_ts <= ?", (current_ts,)) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def settle_bet_in_db(self, bet: dict, is_win: bool, score_str: str) -> dict:
        user = await self.get_or_create_user(bet["user_id"])
        amount = bet["amount"]
        odds = bet["odds"]

        if is_win:
            payout = round(amount * odds, 1)
            net_profit = round(payout - amount, 1)
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc = 1, 0
            status = "win"
        else:
            payout = 0.0
            net_profit = -amount
            new_balance = round(user["balance"], 1)
            w_inc, l_inc = 0, 1
            status = "loss"

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE bets SET status = $1, score_result = $2 WHERE bet_id = $3", status, score_str, bet["bet_id"])
                await conn.execute(
                    "UPDATE users SET balance = $1, wins = wins + $2, losses = losses + $3, profit = profit + $4 WHERE user_id = $5",
                    new_balance, w_inc, l_inc, net_profit, bet["user_id"]
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE bets SET status = ?, score_result = ? WHERE bet_id = ?", (status, score_str, bet["bet_id"]))
                await db.execute(
                    "UPDATE users SET balance = ?, wins = wins + ?, losses = losses + ?, profit = profit + ? WHERE user_id = ?",
                    (new_balance, w_inc, l_inc, net_profit, bet["user_id"])
                )
                await db.commit()

        return {"payout": payout, "net_profit": net_profit, "new_balance": new_balance}

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

db_manager = Database()

# ================= МУЛЬТИ-ШЛЮЗ ИИ =================
async def ask_ai(prompt: str, system_prompt: str = "Ты элитный футбольный аналитик.") -> str | None:
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
                    max_tokens=400
                ),
                timeout=8.0
            )
            if resp.choices and resp.choices[0].message.content:
                return clean_ai_text(resp.choices[0].message.content)
        except Exception as e:
            logging.warning(f"Gemini пропущен: {e}")

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
                    max_tokens=380
                ),
                timeout=7.0
            )
            if resp.choices and resp.choices[0].message.content:
                return clean_ai_text(resp.choices[0].message.content)
        except Exception as e:
            logging.warning(f"Groq ({groq_model}) пропущен: {e}")

    try:
        full_text = quote(f"{system_prompt}\n{prompt}")
        url = f"https://text.pollinations.ai/{full_text}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    ans = await r.text()
                    if ans and len(ans.strip()) > 15 and "<!DOCTYPE" not in ans:
                        return clean_ai_text(ans)
    except Exception:
        pass
    return None

# ================= ФОНОВЫЙ ИИ-АГЕНТ РАСЧЕТА МАТЧЕЙ =================
def generate_realistic_score(pick: str, is_win: bool, bet_type: str) -> str:
    if bet_type == "express":
        return "Все события прошли ✅" if is_win else "Одно из событий не прошло ❌"
    win_p1_scores = ["2:0", "2:1", "3:1", "1:0", "3:0"]
    win_x_scores = ["1:1", "2:2", "0:0"]
    win_p2_scores = ["0:2", "1:2", "1:3", "0:1"]

    if "П1" in pick:
        return random.choice(win_p1_scores) if is_win else random.choice(win_x_scores + win_p2_scores)
    elif "Х" in pick or "Ничья" in pick:
        return random.choice(win_x_scores) if is_win else random.choice(win_p1_scores + win_p2_scores)
    else:
        return random.choice(win_p2_scores) if is_win else random.choice(win_p1_scores + win_x_scores)

async def settle_single_bet_and_notify(bet: dict):
    prob = float(bet.get("win_prob") or 50.0)
    roll = random.uniform(0, 100)
    is_win = roll <= (prob + 4.0)
    score_str = generate_realistic_score(bet["pick"], is_win, bet.get("bet_type", "single"))

    res = await db_manager.settle_bet_in_db(bet, is_win, score_str)
    type_label = "⚡ ЭКСПРЕСС" if bet.get("bet_type") == "express" else "⚽ ОРДИНАР"

    if is_win:
        msg = (
            f"🎉 <b>СТАВКА СЫГРАЛА! ({type_label})</b>\n\n"
            f"<blockquote>🎫 <b>Купон:</b> <code>#{bet['bet_id']}</code>\n"
            f"🏟 <b>Матч:</b> {bet['match_title']}\n"
            f"🎯 <b>Прогноз:</b> <code>{bet['pick']}</code> (кэф <code>{bet['odds']}</code>)\n"
            f"🏁 <b>Счет / Итог:</b> <code>{score_str}</code></blockquote>\n"
            f"💵 <b>Сумма ставки:</b> <code>{bet['amount']} FC</code>\n"
            f"💰 <b>Выплата:</b> <b><code>+{res['payout']} FC</code></b> <i>(чистыми: +{res['net_profit']} FC)</i>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )
    else:
        msg = (
            f"📢 <b>МАТЧ ЗАВЕРШЕН ({type_label})</b>\n\n"
            f"<blockquote>🎫 <b>Купон:</b> <code>#{bet['bet_id']}</code> — ❌ <i>Не сыграл</i>\n"
            f"🏟 <b>Матч:</b> {bet['match_title']}\n"
            f"🎯 <b>Прогноз:</b> <code>{bet['pick']}</code> (кэф <code>{bet['odds']}</code>)\n"
            f"🏁 <b>Счет / Итог:</b> <code>{score_str}</code></blockquote>\n"
            f"💸 <b>Списано:</b> <code>-{bet['amount']} FC</code>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )

    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
        builder.button(text="👤 Личный кабинет", callback_data="profile")
        builder.adjust(2)
        await bot.send_message(bet["user_id"], msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Не удалось отправить пуш пользователю {bet['user_id']}: {e}")

async def match_settlement_worker():
    while True:
        try:
            current_ts = int(now_msk().timestamp())
            due_bets = await db_manager.get_due_pending_bets(current_ts)
            for b in due_bets:
                await settle_single_bet_and_notify(b)
        except Exception as e:
            logging.error(f"Ошибка фонового расчета ставок: {e}")
        await asyncio.sleep(30)

# ================= БАЗА МАТЧЕЙ И МАТЕМАТИКА =================
def calculate_ai_probabilities(odds: dict) -> dict:
    raw_p1, raw_x, raw_p2 = 1 / odds["p1"], 1 / odds["x"], 1 / odds["p2"]
    margin_sum = raw_p1 + raw_x + raw_p2
    return {
        "p1": round((raw_p1 / margin_sum) * 100, 1),
        "x": round((raw_x / margin_sum) * 100, 1),
        "p2": round((raw_p2 / margin_sum) * 100, 1),
        "margin": round((margin_sum - 1) * 100, 2)
    }

def get_base_matches():
    today = now_msk()
    d = [(today + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(0, 7)]
    return {
        "ucl": {
            "title": "🏆 Лига Чемпионов УЕФА",
            "matches": {
                "m1": {"teams": "Реал Мадрид vs Милан", "date": f"{d[0]}, 23:00 МСК", "odds": {"p1": 1.55, "x": 4.40, "p2": 5.80}},
                "m2": {"teams": "Барселона vs Бавария", "date": f"{d[1]}, 23:00 МСК", "odds": {"p1": 2.40, "x": 3.85, "p2": 2.70}},
                "m3": {"teams": "Интер vs Арсенал", "date": f"{d[2]}, 23:00 МСК", "odds": {"p1": 2.65, "x": 3.25, "p2": 2.75}},
                "m4": {"teams": "ПСЖ vs Манчестер Сити", "date": f"{d[3]}, 23:00 МСК", "odds": {"p1": 2.10, "x": 3.50, "p2": 3.20}}
            }
        },
        "epl": {
            "title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)",
            "matches": {
                "m1": {"teams": "Арсенал vs Ливерпуль", "date": f"{d[0]}, 22:30 МСК", "odds": {"p1": 2.20, "x": 3.40, "p2": 3.30}},
                "m2": {"teams": "Манчестер Юнайтед vs Челси", "date": f"{d[1]}, 19:30 МСК", "odds": {"p1": 2.50, "x": 3.30, "p2": 2.80}},
                "m3": {"teams": "Тоттенхэм vs Астон Вилла", "date": f"{d[2]}, 17:00 МСК", "odds": {"p1": 1.95, "x": 3.70, "p2": 3.60}}
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
                "m1": {"teams": "Интер vs Ювентус", "date": f"{d[0]}, 22:45 МСК", "odds": {"p1": 2.05, "x": 3.30, "p2": 3.80}},
                "m2": {"teams": "Милан vs Наполи", "date": f"{d[2]}, 22:45 МСК", "odds": {"p1": 2.45, "x": 3.20, "p2": 3.05}}
            }
        },
        "bundesliga": {
            "title": "🇩🇪 Бундеслига (Германия)",
            "matches": {
                "m1": {"teams": "Бавария vs Боруссия Дортмунд", "date": f"{d[1]}, 19:30 МСК", "odds": {"p1": 1.60, "x": 4.20, "p2": 5.00}},
                "m2": {"teams": "Байер vs РБ Лейпциг", "date": f"{d[2]}, 17:30 МСК", "odds": {"p1": 2.15, "x": 3.60, "p2": 3.10}}
            }
        },
        "ligue1": {
            "title": "🇫🇷 Лига 1 (Франция)",
            "matches": {
                "m1": {"teams": "ПСЖ vs Монако", "date": f"{d[1]}, 21:00 МСК", "odds": {"p1": 1.45, "x": 4.50, "p2": 6.50}},
                "m2": {"teams": "Марсель vs Лион", "date": f"{d[3]}, 22:00 МСК", "odds": {"p1": 2.25, "x": 3.40, "p2": 3.10}}
            }
        }
    }

def build_daily_express_data(db: dict) -> dict:
    picks_text = []
    short_titles = []
    total_odd = 1.0
    combined_prob = 100.0
    max_end_ts = 0

    for l_val in db.values():
        for m in l_val["matches"].values():
            if len(picks_text) >= 6:
                break
            t1, t2 = m["teams"].split(" vs ")
            o = m["odds"]
            probs = calculate_ai_probabilities(o)
            end_ts = parse_match_end_ts(m["date"])
            if end_ts > max_end_ts:
                max_end_ts = end_ts

            if probs["p1"] >= 54:
                bet_str, k, p = f"П1 ({t1})", o["p1"], probs["p1"]
            else:
                bet_str, k, p = f"1Х ({t1})", round(o["p1"] * 0.74, 2), min(82.0, probs["p1"] + probs["x"] - 8)

            total_odd *= k
            combined_prob = combined_prob * (p / 100.0)
            picks_text.append(f"<b>{len(picks_text)+1}. {m['teams']}</b> <i>({m['date']})</i>\n   🎯 Исход: <code>{bet_str}</code> • Кэф: <b><code>{k}</code></b>")
            short_titles.append(f"{m['teams']} ({bet_str})")
        if len(picks_text) >= 6:
            break

    final_odd = round(total_odd, 2)
    playable_prob = max(18.0, round(combined_prob * 100 * 2.2, 1))
    return {
        "text": "\n\n".join(picks_text) + f"\n\n<blockquote>📈 <b>Итоговый коэффициент:</b> <code>{final_odd}</code></blockquote>",
        "total_odd": final_odd,
        "prob": playable_prob,
        "end_ts": max_end_ts,
        "summary_title": "Экспресс дня (6 топ-матчей)",
        "summary_pick": " + ".join(short_titles[:3]) + " и др. (6 событий)"
    }

def smart_local_match_analysis(match: dict, probs: dict) -> str:
    t1, t2 = match["teams"].split(" vs ")
    odds = match["odds"]
    p1, x, p2 = probs["p1"], probs["x"], probs["p2"]
    if p1 >= 58:
        style = f"⚔️ <b>Расклад сил:</b> {t1} доминирует по метрикам xG и домашнему прессингу (вероятность {p1}%)."
        bet = f"🎯 <b>Value-прогноз:</b> П1 ({t1}) за <code>{odds['p1']}</code>"
    elif p2 >= 50:
        style = f"⚔️ <b>Расклад сил:</b> {t2} сильнее в переходных фазах и реализации моментов ({p2}% против {p1}%)."
        bet = f"🎯 <b>Value-прогноз:</b> П2 ({t2}) за <code>{odds['p2']}</code>"
    else:
        style = f"⚔️ <b>Расклад сил:</b> Равный матч ({p1}% на {p2}%) с высокой плотностью в центре поля."
        bet = f"🎯 <b>Value-прогноз:</b> П1 / Двойной шанс 1Х (базовый кэф <code>{odds['p1']}</code>)"
    return f"{style}\n\n{bet}"

# ================= КЛАВИАТУРЫ (ОБНОВЛЕННЫЙ ДИЗАЙН) =================
def main_menu_kb(user_id: int = 0):
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()
    # 1-я строка: Личный кабинет во всю ширину экрана
    builder.button(text="👤 Личный кабинет", callback_data="profile")
    # 2-4 строки: Турниры по 2 в ряд
    builder.button(text="🏆 Лига Чемпионов", callback_data="league:ucl")
    builder.button(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)", callback_data="league:epl")
    builder.button(text="🇪🇸 Ла Лига (Испания)", callback_data="league:laliga")
    builder.button(text="🇮🇹 Серия А (Италия)", callback_data="league:seriea")
    builder.button(text="🇩🇪 Бундеслига", callback_data="league:bundesliga")
    builder.button(text="🇫🇷 Лига 1 (Франция)", callback_data="league:ligue1")
    # 5-6 строки: Экспресс дня и Рейтинг
    builder.button(text="⚡ Экспресс дня (6 матчей)", callback_data="express_day")
    builder.button(text="🏆 Топ-10 капперов", callback_data="leaderboard")

    if slip_count > 0:
        builder.button(text=f"🧺 Мой купон экспресса ({slip_count})", callback_data="view_slip")
        builder.adjust(1, 2, 2, 2, 1, 1, 1)
    else:
        builder.adjust(1, 2, 2, 2, 1, 1)
    return builder.as_markup()

def profile_kb(active_count: int = 0):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⏳ Активные ставки ({active_count})", callback_data="active_bets")
    builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
    builder.button(text="🎁 Забрать бонус (+250 FC)", callback_data="claim_bonus")
    builder.button(text="💎 PRO-статус и Магазин", callback_data="vip_shop")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()

def matches_kb(league_key: str, matches_dict: dict):
    builder = InlineKeyboardBuilder()
    for match_id, data in matches_dict.items():
        short_date = data['date'].split(',')[0]
        builder.button(text=f"⚽ {data['teams']} ({short_date})", callback_data=f"match:{league_key}:{match_id}")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def match_outcomes_kb(league_key: str, match_id: str, odds: dict, user_id: int):
    """Компактные кнопки П1 | Х | П2 без лишних слов, чтобы кэфы всегда были видны полностью"""
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()
    # Ряд 1: Ординар (просто П1, Х, П2 и коэффициент)
    builder.button(text=f"П1 ({odds['p1']})", callback_data=f"pick:{league_key}:{match_id}:p1")
    builder.button(text=f"Х ({odds['x']})", callback_data=f"pick:{league_key}:{match_id}:x")
    builder.button(text=f"П2 ({odds['p2']})", callback_data=f"pick:{league_key}:{match_id}:p2")
    # Ряд 2: Добавление в свой экспресс
    builder.button(text="➕ П1", callback_data=f"slipadd:{league_key}:{match_id}:p1")
    builder.button(text="➕ Х", callback_data=f"slipadd:{league_key}:{match_id}:x")
    builder.button(text="➕ П2", callback_data=f"slipadd:{league_key}:{match_id}:p2")

    if slip_count > 0:
        builder.button(text=f"🧺 Открыть купон экспресса ({slip_count})", callback_data="view_slip")

    builder.button(text="⬅️ К матчам лиги", callback_data=f"league:{league_key}")
    builder.button(text="🏠 Меню", callback_data="back_to_main")

    if slip_count > 0:
        builder.adjust(3, 3, 1, 2)
    else:
        builder.adjust(3, 3, 2)
    return builder.as_markup()

def amount_selection_kb(target_code: str, balance: float):
    builder = InlineKeyboardBuilder()
    for amt in [100, 250, 500, 1000]:
        builder.button(text=f"{amt} FC", callback_data=f"place:{target_code}:{amt}")
    all_in = int(balance) if balance >= 10 else 0
    if all_in >= 10:
        builder.button(text=f"🔥 Ва-банк ({all_in} FC)", callback_data=f"place:{target_code}:{all_in}")
    builder.button(text="✍️ Ввести свою сумму", callback_data=f"custom_amt:{target_code}")

    # Кнопка возврата прямо к матчу или экспрессу
    if target_code == "express-day":
        builder.button(text="⬅️ Назад к Экспрессу", callback_data="express_day")
    elif target_code == "custom-slip":
        builder.button(text="⬅️ Назад к купону", callback_data="view_slip")
    else:
        l_key, m_id, _ = target_code.split("-")
        builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{l_key}:{m_id}")

    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()

# ================= ОБРАБОТЧИКИ СОБЫТИЙ =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await db_manager.get_or_create_user(message.from_user.id, message.from_user.username)
    text = (
        f"⚽ <b>FOOTBALL AI PRO — АНАЛИТИКА И СТАВКИ</b>\n\n"
        f"<blockquote>👤 Игрок: <b>{user['username']}</b>\n"
        f"💰 Доступный банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"🏆 Выиграно купонов: <b><code>{user['wins']}</code></b></blockquote>\n"
        f"🤖 ИИ-разборы матчей, математический расчет вероятностей и Live-купоны с выплатой по финальному свистку.\n\n"
        f"👇 <b>Выбери раздел:</b>"
    )
    await message.answer(text, reply_markup=main_menu_kb(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_main")
async def process_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    text = (
        f"⚽ <b>ГЛАВНОЕ МЕНЮ • FOOTBALL AI PRO</b>\n\n"
        f"<blockquote>💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>  |  🏆 Побед: <b><code>{user['wins']}</code></b></blockquote>\n"
        f"👇 <b>Выбери турнир или открой Личный кабинет:</b>"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb(callback.from_user.id), parse_mode="HTML")
    await callback.answer()

# ================= ЛИЧНЫЙ КАБИНЕТ И АРХИВ СТАВОК =================
@dp.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery):
    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    active_bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    total_settled = user["wins"] + user["losses"]
    winrate = round((user["wins"] / total_settled) * 100, 1) if total_settled > 0 else 0.0
    status_str = "💎 PRO-Каппер" if user["is_vip"] else "🎯 Игрок Лиги"
    profit_sign = "+" if user["profit"] >= 0 else ""

    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n\n"
        f"<blockquote>🆔 Игрок: <b>{user['username']}</b> (<code>{user['user_id']}</code>)\n"
        f"🏅 Статус: <b>{status_str}</b>\n"
        f"💰 Свободный банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"⏳ Ставок в игре: <b><code>{len(active_bets)}</code></b></blockquote>\n"
        f"📊 <b>Статистика каппера:</b>\n"
        f"• Рассчитано ставок: <code>{total_settled}</code> (✅ <code>{user['wins']}</code> | ❌ <code>{user['losses']}</code>)\n"
        f"• Процент побед (Winrate): <b><code>{winrate}%</code></b>\n"
        f"• Чистый профит (ROI): <b><code>{profit_sign}{round(user['profit'], 1)} FC</code></b>\n\n"
        f"<i>🔔 ИИ-агент автоматически пришлет уведомление в чат по завершении каждого матча.</i>"
    )
    await callback.message.edit_text(text, reply_markup=profile_kb(len(active_bets)), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "active_bets")
async def process_active_bets(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    builder = InlineKeyboardBuilder()

    if not bets:
        text = (
            "⏳ <b>АКТИВНЫЕ СТАВКИ</b>\n\n"
            "<blockquote>Сейчас у тебя нет купонов в игре.</blockquote>\n"
            "Открой любую лигу или «⚡ Экспресс дня», чтобы сделать ставку!"
        )
    else:
        lines = []
        for b in bets:
            end_dt = datetime.fromtimestamp(b["settle_ts"]).strftime("%d.%m в %H:%M МСК")
            btype = "⚡ Экспресс" if b.get("bet_type") == "express" else "⚽ Ординар"
            pot_win = round(b["amount"] * b["odds"], 1)
            lines.append(
                f"<blockquote>🎫 <b>Купон #{b['bet_id']}</b> ({btype})\n"
                f"🏟 <b>{b['match_title']}</b>\n"
                f"🎯 Исход: <code>{b['pick']}</code>  •  Кэф: <b><code>{b['odds']}</code></b>\n"
                f"💵 Ставка: <code>{b['amount']} FC</code> ➔ Выплата: <b><code>{pot_win} FC</code></b>\n"
                f"⏱ Расчет: <i>{end_dt}</i></blockquote>"
            )
        text = "⏳ <b>МОИ АКТИВНЫЕ КУПОНЫ В ИГРЕ:</b>\n\n" + "\n".join(lines)
        builder.button(text="🤖 ИИ-Агент: Проверить результаты сейчас", callback_data="force_check_matches")

    builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
    builder.button(text="⬅️ В кабинет", callback_data="profile")
    if bets:
        builder.adjust(1, 2)
    else:
        builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "force_check_matches")
async def process_force_check(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    if not bets:
        await callback.answer("У тебя нет активных купонов!", show_alert=True)
        return
    await callback.answer("🤖 ИИ-агент проверяет результаты матчей и рассчитывает купоны...", show_alert=True)
    for b in bets:
        await settle_single_bet_and_notify(b)
    await process_profile(callback)

@dp.callback_query(F.data == "archive_bets")
async def process_archive_bets(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=False)
    if not bets:
        text = (
            "🗄 <b>АРХИВ СТАВОК ПУСТ</b>\n\n"
            "<blockquote>Сюда попадают все завершенные купоны после расчета ИИ-агентом.</blockquote>"
        )
    else:
        lines = []
        for b in bets:
            is_win = b["status"] == "win"
            badge = f"✅ ВЫИГРЫШ (+{round(b['amount']*b['odds'], 1)} FC)" if is_win else f"❌ ПРОИГРЫШ (-{b['amount']} FC)"
            score_info = f"\n🏁 Счет: <code>{b['score_result']}</code>" if b.get("score_result") else ""
            lines.append(
                f"<blockquote>🎫 <b>Купон #{b['bet_id']}</b> — <b>{badge}</b>\n"
                f"🏟 {b['match_title']}{score_info}\n"
                f"🎯 Исход: <code>{b['pick']}</code> (кэф <code>{b['odds']}</code>) | Сумма: <code>{b['amount']} FC</code></blockquote>"
            )
        text = "🗄 <b>АРХИВ РАССЧИТАННЫХ СТАВОК:</b>\n\n" + "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ Активные ставки", callback_data="active_bets")
    builder.button(text="⬅️ В кабинет", callback_data="profile")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "claim_bonus")
async def process_claim_bonus(callback: CallbackQuery):
    ok, amount = await db_manager.claim_daily_bonus(callback.from_user.id)
    if ok:
        await callback.answer(f"🎉 Начислено +{amount} FC на твой баланс!", show_alert=True)
        await process_profile(callback)
    else:
        await callback.answer("⏳ Ты уже забирал бонус сегодня! Возвращайся завтра.", show_alert=True)

@dp.callback_query(F.data == "vip_shop")
async def process_vip_shop(callback: CallbackQuery):
    text = (
        "💎 <b>PRO-СТАТУС И МАГАЗИН</b>\n\n"
        "<blockquote>🔥 <b>Подписка PRO-Каппер (249 ₽/мес):</b>\n"
        "• Ежедневный бонус <b>+1 000 FC</b> вместо 250 FC\n"
        "• Доступ к закрытым VIP-экспрессам\n"
        "• Значок 💎 в таблице лидеров</blockquote>\n"
        "💰 <b>Пакеты игровой валюты:</b>\n"
        "• Пакет «Старт»: <code>+5 000 FC</code> — 99 ₽ (50 ⭐️)\n"
        "• Пакет «Магнат»: <code>+25 000 FC</code> — 299 ₽ (150 ⭐️)"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "leaderboard")
async def process_leaderboard(callback: CallbackQuery):
    top = await db_manager.get_leaderboard()
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i] if i < 3 else f'<b>{i+1}.</b>'} <b>{u['username']}</b> — <code>{round(u['balance'], 1)} FC</code> <i>(Побед: {u['wins']})</i>"
        for i, u in enumerate(top)
    ]
    body = "\n".join(lines) if lines else "Рейтинг пока формируется."
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Личный кабинет", callback_data="profile")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(2)
    await callback.message.edit_text(f"🏆 <b>ТОП-10 КАППЕРОВ ПРОЕКТА</b>\n\n<blockquote>{body}</blockquote>", reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

# ================= ЭКСПРЕСС ДНЯ И КОРЗИНА ЭКСПРЕССА =================
@dp.callback_query(F.data == "express_day")
async def process_express(callback: CallbackQuery):
    await callback.message.edit_text("⚡ <i>ИИ собирает Экспресс дня из 6 матчей...</i>", parse_mode="HTML")
    db = get_base_matches()
    exp_data = build_daily_express_data(db)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🔥 Поставить на Экспресс (Кэф {exp_data['total_odd']})",
        callback_data="pick:express_day:all:exp"
    )
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)

    text = (
        f"⚡ <b>ЭКСПРЕСС ДНЯ (6 МАТЧЕЙ)</b>\n\n"
        f"{exp_data['text']}\n\n"
        f"👇 <i>Нажми кнопку ниже, чтобы поставить на весь экспресс одним купоном:</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("slipadd:"))
async def process_slip_add(callback: CallbackQuery):
    _, league_key, match_id, pick_code = callback.data.split(":")
    db = get_base_matches()
    match = db[league_key]["matches"][match_id]
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)
    pick_names = {"p1": "П1", "x": "Х", "p2": "П2"}

    uid = callback.from_user.id
    slip = USER_SLIPS.get(uid, [])
    slip = [item for item in slip if item["match_title"] != match["teams"]]
    if len(slip) >= 6:
        await callback.answer("⚠️ В один экспресс можно добавить максимум 6 матчей!", show_alert=True)
        return

    slip.append({
        "match_title": match["teams"],
        "pick": pick_names[pick_code],
        "odds": odds[pick_code],
        "prob": probs[pick_code],
        "end_ts": parse_match_end_ts(match["date"])
    })
    USER_SLIPS[uid] = slip
    await callback.answer(f"✅ Добавлено в экспресс: {match['teams']} — {pick_names[pick_code]} ({odds[pick_code]}). Событий в купоне: {len(slip)}", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=match_outcomes_kb(league_key, match_id, odds, uid))

@dp.callback_query(F.data == "view_slip")
async def process_view_slip(callback: CallbackQuery):
    uid = callback.from_user.id
    slip = USER_SLIPS.get(uid, [])
    if not slip:
        await callback.answer("Твоя корзина экспресса пуста!", show_alert=True)
        return

    total_odd = 1.0
    lines = []
    for i, item in enumerate(slip):
        total_odd *= item["odds"]
        lines.append(f"<b>{i+1}. {item['match_title']}</b>\n   🎯 Исход: <code>{item['pick']}</code> • Кэф: <b><code>{item['odds']}</code></b>")
    total_odd = round(total_odd, 2)

    text = (
        f"🧺 <b>ТВОЙ КУПОН ЭКСПРЕССА ({len(slip)} МАТЧЕЙ)</b>\n\n" +
        "\n\n".join(lines) +
        f"\n\n<blockquote>📈 <b>Общий коэффициент:</b> <code>{total_odd}</code></blockquote>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Оформить ставку (Кэф {total_odd})", callback_data="pick:custom_slip:all:exp")
    builder.button(text="🗑 Очистить купон", callback_data="clear_slip")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1, 2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "clear_slip")
async def process_clear_slip(callback: CallbackQuery, state: FSMContext):
    USER_SLIPS.pop(callback.from_user.id, None)
    await callback.answer("🗑 Купон экспресса очищен!", show_alert=True)
    await process_back_main(callback, state)

# ================= КАРТОЧКА МАТЧА И ОФОРМЛЕНИЕ СТАВКИ =================
@dp.callback_query(F.data.startswith("league:"))
async def process_league_select(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    db = get_base_matches()
    league_data = db.get(league_key)
    matches = league_data["matches"] if league_data else {}
    text = f"<b>{league_data['title']}</b>\n📅 Выбери матч для ИИ-разбора и ставки:"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("match:"))
async def process_match_select(callback: CallbackQuery):
    _, league_key, match_id = callback.data.split(":")
    db = get_base_matches()
    match = db[league_key]["matches"][match_id]
    league_title = db[league_key]["title"]
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)

    await callback.message.edit_text(f"🧠 <i>ИИ анализирует матч {match['teams']}...</i>", parse_mode="HTML")
    prompt = (
        f"Турнир: {league_title}. Матч: {match['teams']}.\n"
        f"Коэффициенты: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}.\n"
        f"Чистые вероятности: П1={probs['p1']}%, Х={probs['x']}%, П2={probs['p2']}%\n"
        f"Дай краткий разбор (до 60 слов) в 2 пункта:\n"
        f"1. ⚔️ Тактический анализ исхода.\n"
        f"2. 🎯 Самая лучшая ставка (Value Bet) с кэфом."
    )
    ai_verdict = await ask_ai(prompt) or smart_local_match_analysis(match, probs)

    text = (
        f"⚽ <b>{match['teams']}</b>\n"
        f"🕒 Начало: <code>{match['date']}</code>\n\n"
        f"<blockquote>📊 <b>Коэффициенты (Маржа {probs['margin']}%):</b>\n"
        f"П1: <b><code>{odds['p1']}</code></b>  |  Х: <b><code>{odds['x']}</code></b>  |  П2: <b><code>{odds['p2']}</code></b>\n"
        f"🧮 <b>Вероятности ИИ:</b>\n"
        f"П1: <b>{probs['p1']}%</b>  |  Х: <b>{probs['x']}%</b>  |  П2: <b>{probs['p2']}%</b></blockquote>\n"
        f"🤖 <b>Экспертный разбор ИИ:</b>\n{ai_verdict}\n\n"
        f"👇 <b>Сделать ставку (1-й ряд — ординар, 2-й ряд — в экспресс):</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=match_outcomes_kb(league_key, match_id, odds, callback.from_user.id),
        parse_mode="HTML"
    )
    await callback.answer()

def resolve_bet_target(target_code: str, user_id: int) -> dict | None:
    db = get_base_matches()
    if target_code == "express-day":
        exp = build_daily_express_data(db)
        return {
            "match_title": exp["summary_title"],
            "pick": exp["summary_pick"],
            "odds": exp["total_odd"],
            "prob": exp["prob"],
            "end_ts": exp["end_ts"],
            "bet_type": "express"
        }
    elif target_code == "custom-slip":
        slip = USER_SLIPS.get(user_id, [])
        if not slip:
            return None
        total_odd = 1.0
        comb_prob = 1.0
        max_ts = 0
        titles = []
        for s in slip:
            total_odd *= s["odds"]
            comb_prob *= (s["prob"] / 100.0)
            if s["end_ts"] > max_ts:
                max_ts = s["end_ts"]
            titles.append(f"{s['match_title']} ({s['pick']})")
        return {
            "match_title": f"Персональный экспресс ({len(slip)} матчей)",
            "pick": " + ".join(titles),
            "odds": round(total_odd, 2),
            "prob": max(20.0, round(comb_prob * 100 * 2.0, 1)),
            "end_ts": max_ts,
            "bet_type": "express"
        }
    else:
        l_key, m_id, p_code = target_code.split("-")
        match = db[l_key]["matches"][m_id]
        odds = match["odds"]
        probs = calculate_ai_probabilities(odds)
        pick_names = {"p1": "П1", "x": "Х", "p2": "П2"}
        return {
            "match_title": f"{match['teams']} ({match['date']})",
            "pick": pick_names[p_code],
            "odds": odds[p_code],
            "prob": probs[p_code],
            "end_ts": parse_match_end_ts(match["date"]),
            "bet_type": "single"
        }

@dp.callback_query(F.data.startswith("pick:"))
async def process_pick_outcome(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, p1, p2, p3 = callback.data.split(":")
    if p1 == "express_day":
        target_code = "express-day"
    elif p1 == "custom_slip":
        target_code = "custom-slip"
    else:
        target_code = f"{p1}-{p2}-{p3}"

    info = resolve_bet_target(target_code, callback.from_user.id)
    if not info:
        await callback.answer("Купон пуст!", show_alert=True)
        return

    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    end_str = datetime.fromtimestamp(info["end_ts"]).strftime("%d.%m.%Y в %H:%M МСК")

    text = (
        f"🎫 <b>ОФОРМЛЕНИЕ СТАВКИ</b>\n\n"
        f"<blockquote>🏟 <b>Событие:</b> {info['match_title']}\n"
        f"🎯 <b>Исход:</b> <code>{info['pick']}</code>\n"
        f"📈 <b>Коэффициент:</b> <b><code>{info['odds']}</code></b>\n"
        f"⏱ <b>Расчет купона:</b> <i>{end_str}</i></blockquote>\n"
        f"💰 <b>Доступный баланс:</b> <code>{round(user['balance'], 1)} FC</code>\n\n"
        f"👇 <b>Выбери сумму ставки или введи свою:</b>"
    )
    await callback.message.edit_text(text, reply_markup=amount_selection_kb(target_code, user["balance"]), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("place:"))
async def process_place_fixed_amount(callback: CallbackQuery):
    _, target_code, amt_str = callback.data.split(":")
    amount = int(amt_str)
    info = resolve_bet_target(target_code, callback.from_user.id)
    if not info:
        await callback.answer("Ошибка купона! Попробуй заново.", show_alert=True)
        return

    res = await db_manager.create_pending_bet(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        match_title=info["match_title"],
        pick=info["pick"],
        amount=amount,
        odds=info["odds"],
        win_prob=info["prob"],
        settle_ts=info["end_ts"],
        bet_type=info["bet_type"]
    )

    if not res["ok"]:
        await callback.answer(f"⚠️ {res['error']}", show_alert=True)
        return

    if target_code == "custom-slip":
        USER_SLIPS.pop(callback.from_user.id, None)

    end_str = datetime.fromtimestamp(info["end_ts"]).strftime("%d.%m в %H:%M МСК")
    text = (
        f"✅ <b>СТАВКА ПРИНЯТА! (КУПОН #{res['bet_id']})</b>\n\n"
        f"<blockquote>🏟 <b>Событие:</b> {info['match_title']}\n"
        f"🎯 <b>Прогноз:</b> <code>{info['pick']}</code>  •  Кэф: <b><code>{info['odds']}</code></b>\n"
        f"💵 <b>Сумма ставки:</b> <code>{amount} FC</code>\n"
        f"💰 <b>Возможная выплата:</b> <b><code>{res['potential_win']} FC</code></b></blockquote>\n"
        f"🏦 <b>Остаток на балансе:</b> <code>{res['new_balance']} FC</code>\n"
        f"⏱ <b>Расчет по окончании матча:</b> <i>{end_str}</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ Мои активные ставки", callback_data="active_bets")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer("🎫 Купон зарегистрирован!")

@dp.callback_query(F.data.startswith("custom_amt:"))
async def process_custom_amount_prompt(callback: CallbackQuery, state: FSMContext):
    target_code = callback.data.split(":")[1]
    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    await state.set_state(BetStates.waiting_for_custom_amount)
    await state.update_data(target_code=target_code)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="back_to_main")
    await callback.message.edit_text(
        f"✍️ <b>ВВОД СВОЕЙ СУММЫ СТАВКИ</b>\n\n"
        f"<blockquote>💰 Доступный баланс: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"Минимальная сумма: <code>10 FC</code></blockquote>\n"
        f"Напиши в чат целое число, которое хочешь поставить:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(BetStates.waiting_for_custom_amount)
async def process_custom_amount_input(message: Message, state: FSMContext):
    data = await state.get_data()
    target_code = data.get("target_code")
    raw_text = (message.text or "").strip()

    if not raw_text.isdigit():
        await message.answer("⚠️ Введи сумму целым числом без букв (например: <code>350</code>):", parse_mode="HTML")
        return

    amount = int(raw_text)
    info = resolve_bet_target(target_code, message.from_user.id)
    if not info:
        await state.clear()
        await message.answer("⚠️ Купон устарел. Выбери матч заново.", reply_markup=main_menu_kb(message.from_user.id))
        return

    res = await db_manager.create_pending_bet(
        user_id=message.from_user.id,
        username=message.from_user.username,
        match_title=info["match_title"],
        pick=info["pick"],
        amount=amount,
        odds=info["odds"],
        win_prob=info["prob"],
        settle_ts=info["end_ts"],
        bet_type=info["bet_type"]
    )

    if not res["ok"]:
        await message.answer(f"⚠️ {res['error']}\nВведи другую сумму:")
        return

    await state.clear()
    if target_code == "custom-slip":
        USER_SLIPS.pop(message.from_user.id, None)

    end_str = datetime.fromtimestamp(info["end_ts"]).strftime("%d.%m в %H:%M МСК")
    text = (
        f"✅ <b>СТАВКА ПРИНЯТА! (КУПОН #{res['bet_id']})</b>\n\n"
        f"<blockquote>🏟 <b>Событие:</b> {info['match_title']}\n"
        f"🎯 <b>Прогноз:</b> <code>{info['pick']}</code>  •  Кэф: <b><code>{info['odds']}</code></b>\n"
        f"💵 <b>Сумма ставки:</b> <code>{amount} FC</code>\n"
        f"💰 <b>Возможная выплата:</b> <b><code>{res['potential_win']} FC</code></b></blockquote>\n"
        f"🏦 <b>Остаток на балансе:</b> <code>{res['new_balance']} FC</code>\n"
        f"⏱ <b>Расчет по окончании матча:</b> <i>{end_str}</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ Мои активные ставки", callback_data="active_bets")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ================= ВЕБ-СЕРВЕР И ЗАПУСК =================
async def handle_ping(request):
    return web.Response(text="Football AI Pro Live Bookmaker is running 24/7!")

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
    asyncio.create_task(match_settlement_worker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
