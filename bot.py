import os
import re
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
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

# Корзина экспрессов и кэш ответов ИИ для мгновенной загрузки
USER_SLIPS = {}
AI_CACHE = {}

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

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

# ================= КОНФИГУРАЦИЯ ЛИГ И КЛУБНЫХ ЭМБЛЕМ =================
MSK_TZ = timezone(timedelta(hours=3))

LEAGUES_CONFIG = {
    "ucl": {"title": "🏆 Лига Чемпионов УЕФА", "slug": "uefa.champions"},
    "epl": {"title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)", "slug": "eng.1"},
    "laliga": {"title": "🇪🇸 Ла Лига (Испания)", "slug": "esp.1"},
    "seriea": {"title": "🇮🇹 Серия А (Италия)", "slug": "ita.1"},
    "bundesliga": {"title": "🇩🇪 Бундеслига", "slug": "ger.1"},
    "ligue1": {"title": "🇫🇷 Лига 1 (Франция)", "slug": "fra.1"}
}

# Названия клубов с фирменными эмблемами/цветами
TEAM_TRANSLATIONS = {
    # Англия
    "Arsenal": "🔴⚪ Арсенал", "Aston Villa": "🟣🔵 Астон Вилла", "Bournemouth": "🍒 Борнмут",
    "AFC Bournemouth": "🍒 Борнмут", "Brentford": "🐝 Брентфорд", "Brighton & Hove Albion": "🔵⚪ Брайтон",
    "Brighton": "🔵⚪ Брайтон", "Chelsea": "🔵🦁 Челси", "Crystal Palace": "🦅 Кристал Пэлас",
    "Everton": "🔵 Эвертон", "Fulham": "⚪⚫ Фулхэм", "Ipswich Town": "🔵⚪ Ипсвич",
    "Leicester City": "🦊 Лестер", "Liverpool": "🔴🦅 Ливерпуль", "Manchester City": "🩵 Ман Сити",
    "Manchester United": "🔴🔱 Ман Юнайтед", "Newcastle United": "⚫⚪ Ньюкасл",
    "Nottingham Forest": "🌲 Ноттингем", "Southampton": "🔴⚪ Саутгемптон",
    "Tottenham Hotspur": "⚪🐓 Тоттенхэм", "West Ham United": "⚒️ Вест Хэм",
    "Wolverhampton Wanderers": "🐺 Вулверхэмптон", "Leeds United": "⚪💛 Лидс",
    "Burnley": "🟣🩵 Бернли", "Sunderland": "🔴⚪ Сандерленд",
    # Испания
    "Real Madrid": "👑 Реал Мадрид", "Barcelona": "🔵🔴 Барселона", "Atlético Madrid": "🔴⚪ Атлетико М",
    "Atletico Madrid": "🔴⚪ Атлетико М", "Athletic Club": "🦁 Атлетик Б", "Real Sociedad": "🔵⚪ Реал Сосьедад",
    "Real Betis": "🟢⚪ Бетис", "Villarreal": "🟡 Вильярреал", "Valencia": "🦇 Валенсия",
    "Sevilla": "⚪🔴 Севилья", "Girona": "🔴⚪ Жирона", "Celta Vigo": "🩵 Сельта",
    "Osasuna": "🔴🔵 Осасуна", "Getafe": "🔵 Хетафе", "Rayo Vallecano": "⚡ Райо Вальекано",
    "Mallorca": "👹 Мальорка", "Las Palmas": "🟡🔵 Лас-Пальмас", "Alavés": "🔵⚪ Алавес",
    "Deportivo Alavés": "🔵⚪ Алавес", "Espanyol": "🔵⚪ Эспаньол", "Leganés": "🥒 Леганес",
    "Real Valladolid": "🟣⚪ Вальядолид",
    # Италия
    "Internazionale": "⚫🔵 Интер", "Inter Milan": "⚫🔵 Интер", "AC Milan": "🔴⚫ Милан",
    "Juventus": "⚪⚫ Ювентус", "Napoli": "🩵 Наполи", "AS Roma": "🐺 Рома", "Roma": "🐺 Рома",
    "Lazio": "🦅 Лацио", "Atalanta": "⚫🔵 Аталанта", "Fiorentina": "⚜️ Фиорентина",
    "Bologna": "🔴🔵 Болонья", "Torino": "🐂 Торино", "Udinese": "⚪⚫ Удинезе",
    "Genoa": "🔴🔵 Дженоа", "Como": "🔵⚪ Комо", "Parma": "🟡🔵 Парма",
    "Hellas Verona": "🟡🔵 Верона", "Empoli": "🔵 Эмполи", "Cagliari": "🔴🔵 Кальяри",
    "Lecce": "🟡🔴 Лечче", "Monza": "🔴⚪ Монца", "Venezia": "🟠🟢 Венеция",
    # Германия
    "Bayern Munich": "🔴⚪ Бавария", "Borussia Dortmund": "🐝 Боруссия Д", "Bayer Leverkusen": "🦁 Байер",
    "RB Leipzig": "🐂 РБ Лейпциг", "VfB Stuttgart": "⚪🔴 Штутгарт", "Eintracht Frankfurt": "🦅 Айнтрахт Ф",
    "SC Freiburg": "⚫⚪ Фрайбург", "TSG Hoffenheim": "🔵⚪ Хоффенхайм", "Werder Bremen": "🟢⚪ Вердер",
    "Heidenheim": "🔴🔵 Хайденхайм", "1. FC Heidenheim 1846": "🔴🔵 Хайденхайм", "FC Augsburg": "🔴🟢 Аугсбург",
    "VfL Wolfsburg": "🐺 Вольфсбург", "Borussia Mönchengladbach": "⚫⚪ Боруссия М", "Mainz": "🔴⚪ Майнц",
    "1. FSV Mainz 05": "🔴⚪ Майнц", "1. FC Union Berlin": "🔴⚙️ Унион Берлин", "VfL Bochum": "🔵⚪ Бохум",
    "FC St. Pauli": "🏴‍☠️ Санкт-Паули", "Holstein Kiel": "🔵⚪ Хольштайн", "Hamburger SV": "🔷 Гамбург", "FC Cologne": "🐐 Кельн",
    # Франция и ЛЧ
    "Paris Saint-Germain": "🔵🔴 ПСЖ", "AS Monaco": "🔴⚪ Монако", "Monaco": "🔴⚪ Монако",
    "Marseille": "⚪🩵 Марсель", "Olympique de Marseille": "⚪🩵 Марсель", "Lille": "🐕 Лилль",
    "LOSC Lille": "🐕 Лилль", "Lyon": "🦁 Лион", "Olympique Lyonnais": "🦁 Лион",
    "Nice": "🔴⚫ Ницца", "OGC Nice": "🔴⚫ Ницца", "Lens": "🟡🔴 Ланс", "RC Lens": "🟡🔴 Ланс",
    "Rennes": "🔴⚫ Ренн", "Stade Rennais": "🔴⚫ Ренн", "Stade Brestois 29": "🏴‍☠️ Брест", "Brest": "🏴‍☠️ Брест",
    "Reims": "🔴⚪ Реймс", "Stade de Reims": "🔴⚪ Реймс", "Strasbourg": "🔵⚪ Страсбур",
    "RC Strasbourg Alsace": "🔵⚪ Страсбур", "Toulouse": "🟣⚪ Тулуза", "Montpellier": "🟠🔵 Монпелье",
    "Nantes": "🟡🟢 Нант", "FC Nantes": "🟡🟢 Нант", "Auxerre": "⚪🔵 Осер", "AJ Auxerre": "⚪🔵 Осер",
    "Angers": "⚫⚪ Анже", "Saint-Étienne": "🟢 Сент-Этьен", "Le Havre": "🩵🔵 Гавр",
    # Клубы ЛЧ
    "Sporting CP": "🟢🦁 Спортинг", "Benfica": "🦅 Бенфика", "FC Porto": "🐉 Порту",
    "PSV Eindhoven": "🔴⚪ ПСВ", "Feyenoord": "🔴⚪ Фейеноорд", "Ajax": "⚪🔴 Аякс",
    "Celtic": "🍀 Селтик", "Club Brugge": "🔵⚫ Брюгге", "Shakhtar Donetsk": "⚒️ Шахтер",
    "Red Bull Salzburg": "🐂 Зальцбург", "Sturm Graz": "⚫⚪ Штурм", "Sparta Prague": "🔴🟡 Спарта Прага",
    "Slovan Bratislava": "🩵 Слован", "Young Boys": "🟡⚫ Янг Бойз", "Dinamo Zagreb": "🔵 Динамо Загреб",
    "Crvena Zvezda": "🔴⚪ Црвена Звезда", "Galatasaray": "🦁 Галатасарай"
}

ELITE_KEYWORDS = {
    "Реал Мадрид": 0.45, "Ман Сити": 0.45, "Бавария": 0.42, "Барселона": 0.40,
    "Ливерпуль": 0.40, "Арсенал": 0.38, "Интер": 0.36, "ПСЖ": 0.35, "Байер": 0.30,
    "Атлетико": 0.28, "Ювентус": 0.26, "Наполи": 0.26, "Челси": 0.24,
    "Милан": 0.22, "Боруссия Д": 0.22, "Аталанта": 0.20, "Астон Вилла": 0.18
}

PICK_LABELS = {
    "p1": "П1",
    "x": "Х (Ничья)",
    "p2": "П2",
    "1x": "1Х",
    "x2": "Х2",
    "tb15": "ТБ 1.5",
    "tb25": "ТБ 2.5",
    "tm25": "ТМ 2.5",
    "btts": "ОЗ: Да"
}

FALLBACK_BADGES = ["🛡️", "⚔️", "🔵⚪", "🔴⚪", "🟢⚪", "🟡⚫"]

def translate_team(name: str) -> str:
    if name in TEAM_TRANSLATIONS:
        return TEAM_TRANSLATIONS[name]
    badge = FALLBACK_BADGES[sum(ord(c) for c in name) % len(FALLBACK_BADGES)]
    return f"{badge} {name}"

def get_elite_bonus(ru_name: str) -> float:
    for kw, val in ELITE_KEYWORDS.items():
        if kw in ru_name:
            return val
    return 0.0

def now_msk() -> datetime:
    return datetime.now(MSK_TZ)

def clean_ai_text(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = text.replace("*", "• ")
    return text.strip()

# ================= ПОЛУЧЕНИЕ РЕАЛЬНЫХ МАТЧЕЙ И 7 РЫНКОВ КОЭФФИЦИЕНТОВ =================
SCHEDULE_CACHE = {"data": {}, "updated_at": 0}
CACHE_TTL = 900

def parse_american_odd(val) -> float | None:
    if val is None or isinstance(val, (dict, list, bool)):
        return None
    try:
        s = str(val).strip().upper()
        if s in ("EVEN", "EV"):
            return 2.00
        num = float(s)
        if 1.01 < num < 15.0:
            return round(num, 2)
        if num >= 100:
            return round(1.0 + (num / 100.0), 2)
        if num <= -100:
            return round(1.0 + (100.0 / abs(num)), 2)
    except Exception:
        pass
    return None

def parse_team_ppg(comp_dict: dict, ru_name: str) -> float:
    base = 1.45 + get_elite_bonus(ru_name)
    if not isinstance(comp_dict, dict):
        return base
    records = comp_dict.get("records") or []
    for r in records:
        if not isinstance(r, dict):
            continue
        summary = str(r.get("summary") or "")
        parts = summary.split("-")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            w, d, l = int(parts[0]), int(parts[1]), int(parts[2])
            games = w + d + l
            if games >= 3:
                ppg = (w * 3 + d) / games
                return (ppg * 0.7) + (base * 0.3)
    return base

def compute_realistic_odds(comp_obj: dict, home_comp: dict, away_comp: dict, h_name: str, a_name: str) -> dict:
    """Рассчитывает полную роспись: П1, Х, П2, ТБ 1.5, ТБ 2.5, ТМ 2.5 и ОЗ (Да)"""
    h_strength = parse_team_ppg(home_comp, h_name) + 0.22
    a_strength = parse_team_ppg(away_comp, a_name)
    diff = h_strength - a_strength

    # 1. Основные исходы (П1, Х, П2)
    p1_odd, x_odd, p2_odd = None, None, None
    try:
        odds_list = comp_obj.get("odds") or []
        for o in odds_list:
            if not isinstance(o, dict):
                continue
            h_dict = o.get("homeTeamOdds") if isinstance(o.get("homeTeamOdds"), dict) else {}
            a_dict = o.get("awayTeamOdds") if isinstance(o.get("awayTeamOdds"), dict) else {}
            d_raw = o.get("drawOdds")
            d_val = d_raw.get("moneyLine") if isinstance(d_raw, dict) else d_raw

            h_o = parse_american_odd(h_dict.get("moneyLine"))
            a_o = parse_american_odd(a_dict.get("moneyLine"))
            d_o = parse_american_odd(d_val)
            if h_o and a_o and d_o and 1.05 <= h_o <= 25 and 1.05 <= a_o <= 25:
                p1_odd, x_odd, p2_odd = h_o, d_o, a_o
                break
    except Exception:
        pass

    if not (p1_odd and x_odd and p2_odd):
        prob_x = max(0.17, min(0.31, 0.28 - abs(diff) * 0.07))
        rem = 1.0 - prob_x
        ratio = 1.0 / (1.0 + (2.71828 ** (-diff * 1.15)))
        prob_p1 = max(0.08, min(0.80, rem * ratio))
        prob_p2 = max(0.08, min(0.80, rem - prob_p1))
        margin = 1.045
        p1_odd = round(max(1.14, 1.0 / (prob_p1 * margin)), 2)
        x_odd = round(max(2.85, 1.0 / (prob_x * margin)), 2)
        p2_odd = round(max(1.14, 1.0 / (prob_p2 * margin)), 2)

    # 2. Расчет рынка голов (Тоталы и ОЗ) на основе атакующего потенциала пары
    attack_index = (h_strength + a_strength) / 3.1  # ~1.0 в среднем, >1.1 у топ-атак
    closeness = max(0.0, 1.0 - abs(diff) * 0.45)    # В близких матчах выше шанс ОЗ

    prob_tb25 = max(0.38, min(0.68, 0.49 * attack_index + 0.05))
    prob_tb15 = max(0.68, min(0.88, prob_tb25 + 0.24))
    prob_tm25 = 1.0 - prob_tb25
    prob_btts = max(0.40, min(0.67, 0.46 * attack_index + closeness * 0.09))

    m_goals = 1.045
    return {
        "p1": p1_odd,
        "x": x_odd,
        "p2": p2_odd,
        "tb15": round(max(1.14, 1.0 / (prob_tb15 * m_goals)), 2),
        "tb25": round(max(1.42, 1.0 / (prob_tb25 * m_goals)), 2),
        "tm25": round(max(1.45, 1.0 / (prob_tm25 * m_goals)), 2),
        "btts": round(max(1.44, 1.0 / (prob_btts * m_goals)), 2)
    }

def calculate_ai_probabilities(odds: dict) -> dict:
    raw_p1, raw_x, raw_p2 = 1 / odds["p1"], 1 / odds["x"], 1 / odds["p2"]
    margin_sum = raw_p1 + raw_x + raw_p2
    return {
        "p1": round((raw_p1 / margin_sum) * 100, 1),
        "x": round((raw_x / margin_sum) * 100, 1),
        "p2": round((raw_p2 / margin_sum) * 100, 1),
        "tb15": round(min(89.0, (1.0 / odds.get("tb15", 1.30)) * 96.0), 1),
        "tb25": round(min(75.0, (1.0 / odds.get("tb25", 1.85)) * 95.5), 1),
        "tm25": round(min(75.0, (1.0 / odds.get("tm25", 1.95)) * 95.5), 1),
        "btts": round(min(74.0, (1.0 / odds.get("btts", 1.75)) * 95.5), 1),
        "margin": round((margin_sum - 1) * 100, 2)
    }

def parse_event_object(ev: dict, league_key: str, cfg: dict, now_ts: int) -> dict | None:
    try:
        if not isinstance(ev, dict):
            return None
        comps = ev.get("competitions") or []
        comp = comps[0] if (comps and isinstance(comps[0], dict)) else {}

        st_obj = (comp.get("status") or ev.get("status") or {}).get("type") or {}
        status_state = str(st_obj.get("state", "pre")).lower()
        completed = bool(st_obj.get("completed", False))
        if completed or status_state in ("post", "in"):
            return None

        raw_date = str(ev.get("date") or comp.get("date") or "")
        if len(raw_date) < 16:
            return None
        dt_utc = datetime.strptime(raw_date[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK_TZ)
        start_ts = int(dt_msk.timestamp())

        if start_ts <= now_ts:
            return None

        competitors = comp.get("competitors") or []
        if len(competitors) < 2:
            return None

        home_c = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "away"), competitors[1])

        h_team_obj = home_c.get("team") or {}
        a_team_obj = away_c.get("team") or {}
        h_name = translate_team(h_team_obj.get("displayName") or h_team_obj.get("name") or "Команда 1")
        a_name = translate_team(a_team_obj.get("displayName") or a_team_obj.get("name") or "Команда 2")

        ev_id = str(ev.get("id") or "")
        if not ev_id:
            return None

        odds = compute_realistic_odds(comp, home_c, away_c, h_name, a_name)

        h_recs = home_c.get("records") or []
        a_recs = away_c.get("records") or []
        h_rec = h_recs[0].get("summary", "") if (h_recs and isinstance(h_recs[0], dict)) else ""
        a_rec = a_recs[0].get("summary", "") if (a_recs and isinstance(a_recs[0], dict)) else ""

        return {
            "event_id": ev_id,
            "league_key": league_key,
            "league_slug": cfg["slug"],
            "teams": f"{h_name} vs {a_name}",
            "home_team": h_name,
            "away_team": a_name,
            "records_info": f"{h_name} (В-Н-П: {h_rec or 'н/д'}), {a_name} (В-Н-П: {a_rec or 'н/д'})",
            "date": dt_msk.strftime("%d.%m.%Y, %H:%M МСК"),
            "start_ts": start_ts,
            "end_ts": start_ts + (115 * 60),
            "odds": odds
        }
    except Exception as e:
        logging.debug(f"Пропущено событие в {league_key}: {e}")
        return None

async def fetch_league_schedule(session: aiohttp.ClientSession, league_key: str, cfg: dict, now_dt: datetime, now_ts: int) -> tuple[str, dict]:
    all_upcoming = {}
    months_to_check = [now_dt.strftime("%Y%m")]
    next_month_dt = now_dt + timedelta(days=25)
    if next_month_dt.strftime("%Y%m") not in months_to_check:
        months_to_check.append(next_month_dt.strftime("%Y%m"))

    for ym in months_to_check:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{cfg['slug']}/scoreboard?dates={ym}&limit=200"
        try:
            async with session.get(url, headers=HTTP_HEADERS, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for ev in (data.get("events") or []):
                        parsed = parse_event_object(ev, league_key, cfg, now_ts)
                        if parsed:
                            all_upcoming[parsed["event_id"]] = parsed
        except Exception as e:
            logging.warning(f"Ошибка запроса месяца {ym} для {league_key}: {e}")

    if not all_upcoming:
        for day_offset in range(0, 8):
            day_str = (now_dt + timedelta(days=day_offset)).strftime("%Y%m%d")
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{cfg['slug']}/scoreboard?dates={day_str}"
            try:
                async with session.get(url, headers=HTTP_HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for ev in (data.get("events") or []):
                            parsed = parse_event_object(ev, league_key, cfg, now_ts)
                            if parsed:
                                all_upcoming[parsed["event_id"]] = parsed
            except Exception:
                continue

    sorted_events = sorted(all_upcoming.values(), key=lambda x: x["start_ts"])
    seven_days_limit = now_ts + (7 * 86400)

    matches_7d = {m["event_id"]: m for m in sorted_events if m["start_ts"] <= seven_days_limit}
    if matches_7d:
        return league_key, {
            "title": cfg["title"],
            "slug": cfg["slug"],
            "matches": matches_7d,
            "extended": False
        }

    next_round_matches = {m["event_id"]: m for m in sorted_events[:14]}
    return league_key, {
        "title": cfg["title"],
        "slug": cfg["slug"],
        "matches": next_round_matches,
        "extended": True
    }

async def get_real_matches(force_refresh: bool = False) -> dict:
    now_dt = now_msk()
    now_ts = int(now_dt.timestamp())

    if not force_refresh and SCHEDULE_CACHE["data"] and (now_ts - SCHEDULE_CACHE["updated_at"] < CACHE_TTL):
        filtered = {}
        for l_k, l_v in SCHEDULE_CACHE["data"].items():
            active_m = {m_id: m for m_id, m in l_v["matches"].items() if m["start_ts"] > now_ts}
            filtered[l_k] = {
                "title": l_v["title"],
                "slug": l_v["slug"],
                "matches": active_m,
                "extended": l_v.get("extended", False)
            }
        if any(len(v["matches"]) > 0 for v in filtered.values()):
            return filtered

    result_db = {}
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_league_schedule(session, l_key, cfg, now_dt, now_ts)
            for l_key, cfg in LEAGUES_CONFIG.items()
        ]
        responses = await asyncio.gather(*tasks)
        for l_key, l_data in responses:
            result_db[l_key] = l_data

    if any(len(v["matches"]) > 0 for v in result_db.values()):
        SCHEDULE_CACHE["data"] = result_db
        SCHEDULE_CACHE["updated_at"] = now_ts

    return result_db

async def fetch_real_match_result(session: aiohttp.ClientSession, league_slug: str, event_id: str) -> dict:
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/summary?event={event_id}"
    try:
        async with session.get(url, headers=HTTP_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                header = data.get("header") or {}
                comps = header.get("competitions") or []
                if comps and isinstance(comps[0], dict):
                    comp = comps[0]
                    status_obj = comp.get("status") or {}
                    st_type = status_obj.get("type") or {}
                    state = str(st_type.get("state", "pre")).lower()
                    completed = bool(st_type.get("completed", False))
                    detail = str(st_type.get("shortDetail") or "")

                    competitors = comp.get("competitors") or []
                    home_c = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "home"), competitors[0] if competitors else {})
                    away_c = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

                    h_score = int(home_c.get("score") or 0)
                    a_score = int(away_c.get("score") or 0)
                    return {
                        "ok": True,
                        "state": state,
                        "completed": completed or (state == "post"),
                        "home_score": h_score,
                        "away_score": a_score,
                        "score_str": f"{h_score}:{a_score}",
                        "detail": detail
                    }
    except Exception as e:
        logging.warning(f"Ошибка проверки результата матча {event_id}: {e}")
    return {"ok": False, "state": "unknown", "completed": False}

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
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS legs_json TEXT DEFAULT '[]';
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
                        score_result TEXT DEFAULT '',
                        legs_json TEXT DEFAULT '[]'
                    )
                """)
                for col_def in [
                    "bet_type TEXT DEFAULT 'single'",
                    "win_prob REAL DEFAULT 50.0",
                    "settle_ts INTEGER DEFAULT 0",
                    "created_at TEXT DEFAULT ''",
                    "score_result TEXT DEFAULT ''",
                    "legs_json TEXT DEFAULT '[]'"
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

    async def create_pending_bet(
        self, user_id: int, username: str, match_title: str, pick: str,
        amount: int, odds: float, win_prob: float, settle_ts: int,
        bet_type: str = "single", legs_json: str = "[]"
    ) -> dict:
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
                    INSERT INTO bets (user_id, match_title, pick, amount, odds, status, bet_type, win_prob, settle_ts, created_at, legs_json)
                    VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8, $9, $10) RETURNING bet_id
                """, user_id, match_title, pick, amount, odds, bet_type, win_prob, settle_ts, created_str, legs_json)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
                cur = await db.execute("""
                    INSERT INTO bets (user_id, match_title, pick, amount, odds, status, bet_type, win_prob, settle_ts, created_at, legs_json)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """, (user_id, match_title, pick, amount, odds, bet_type, win_prob, settle_ts, created_str, legs_json))
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

    async def get_all_pending_bets(self) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM bets WHERE status = 'pending'")
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM bets WHERE status = 'pending'") as cur:
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

# ================= СКОРОСТНОЙ МУЛЬТИ-ШЛЮЗ ИИ С КЭШИРОВАНИЕМ =================
async def ask_ai_cached(cache_key: str, prompt: str, system_prompt: str = "Ты элитный футбольный аналитик.") -> str | None:
    now_ts = int(now_msk().timestamp())
    cached = AI_CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"] < 10800):
        return cached["text"]

    # 1. Сверхбыстрый кластер Groq (отвечает за 0.6 сек с сервера Render в США)
    for groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        try:
            resp = await asyncio.wait_for(
                groq_client.chat.completions.create(
                    model=groq_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.45,
                    max_tokens=360
                ),
                timeout=3.8
            )
            if resp.choices and resp.choices[0].message.content:
                ans = clean_ai_text(resp.choices[0].message.content)
                AI_CACHE[cache_key] = {"text": ans, "ts": now_ts}
                return ans
        except Exception as e:
            logging.warning(f"Groq ({groq_model}) пропущен: {e}")

    # 2. Google Gemini 2.5 Flash
    if GEMINI_API_KEY:
        try:
            resp = await asyncio.wait_for(
                gemini_client.chat.completions.create(
                    model="gemini-2.5-flash",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.45,
                    max_tokens=380
                ),
                timeout=4.2
            )
            if resp.choices and resp.choices[0].message.content:
                ans = clean_ai_text(resp.choices[0].message.content)
                AI_CACHE[cache_key] = {"text": ans, "ts": now_ts}
                return ans
        except Exception as e:
            logging.warning(f"Gemini пропущен: {e}")

    return None

# ================= ПРОВЕРКА РЕАЛЬНЫХ РЕЗУЛЬТАТОВ (ВКЛЮЧАЯ ТОТАЛЫ И ОЗ) =================
def evaluate_leg_pick(pick_code: str, home_score: int, away_score: int) -> bool:
    code = pick_code.lower()
    total_goals = home_score + away_score
    if code in ("p1", "п1"):
        return home_score > away_score
    elif code in ("x", "х"):
        return home_score == away_score
    elif code in ("p2", "п2"):
        return away_score > home_score
    elif code in ("1x", "1х"):
        return home_score >= away_score
    elif code in ("x2", "х2"):
        return away_score >= home_score
    elif code == "tb15":
        return total_goals >= 2
    elif code == "tb25":
        return total_goals >= 3
    elif code == "tm25":
        return total_goals <= 2
    elif code == "btts":
        return (home_score >= 1) and (away_score >= 1)
    return home_score > away_score

async def check_and_settle_real_bet(session: aiohttp.ClientSession, bet: dict) -> dict:
    try:
        legs = json.loads(bet.get("legs_json") or "[]")
    except Exception:
        legs = []

    if not legs:
        return {"settled": False, "live_summary": "Ожидание данных матча"}

    all_completed = True
    all_won = True
    score_parts = []
    live_parts = []

    for leg in legs:
        res = await fetch_real_match_result(session, leg["league_slug"], str(leg["event_id"]))
        if not res["ok"]:
            all_completed = False
            live_parts.append(f"⏳ {leg['teams']} — ожидание данных")
            continue

        if not res["completed"]:
            all_completed = False
            if res["state"] == "in":
                live_parts.append(f"🔴 LIVE: {leg['teams']} — {res['score_str']} ({res['detail']})")
            else:
                live_parts.append(f"📅 {leg['teams']} — еще не начался")
        else:
            leg_won = evaluate_leg_pick(leg["pick_code"], res["home_score"], res["away_score"])
            if not leg_won:
                all_won = False
            icon = "✅" if leg_won else "❌"
            if len(legs) == 1:
                score_parts.append(f"{res['score_str']}")
            else:
                score_parts.append(f"{leg['teams']} {res['score_str']} ({icon})")
            live_parts.append(f"🏁 {leg['teams']} — {res['score_str']} {icon}")

    if all_completed:
        final_score_str = " | ".join(score_parts)
        db_res = await db_manager.settle_bet_in_db(bet, all_won, final_score_str)
        await send_settlement_notification(bet, all_won, final_score_str, db_res)
        return {"settled": True, "is_win": all_won, "score_str": final_score_str}

    return {"settled": False, "live_summary": "\n".join(live_parts)}

async def send_settlement_notification(bet: dict, is_win: bool, score_str: str, res: dict):
    type_label = "⚡ ЭКСПРЕСС" if bet.get("bet_type") == "express" else "⚽ ОРДИНАР"
    if is_win:
        msg = (
            f"🎉 <b>СТАВКА СЫГРАЛА! ({type_label})</b>\n\n"
            f"<blockquote>🎫 <b>Купон:</b> <code>#{bet['bet_id']}</code>\n"
            f"🏟 <b>Событие:</b> {bet['match_title']}\n"
            f"🎯 <b>Прогноз:</b> <code>{bet['pick']}</code> (кэф <code>{bet['odds']}</code>)\n"
            f"🏁 <b>Реальный счет:</b> <code>{score_str}</code></blockquote>\n"
            f"💵 <b>Сумма ставки:</b> <code>{bet['amount']} FC</code>\n"
            f"💰 <b>Выплата:</b> <b><code>+{res['payout']} FC</code></b> <i>(чистыми: +{res['net_profit']} FC)</i>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )
    else:
        msg = (
            f"📢 <b>МАТЧ ЗАВЕРШЕН ({type_label})</b>\n\n"
            f"<blockquote>🎫 <b>Купон:</b> <code>#{bet['bet_id']}</code> — ❌ <i>Не сыграл</i>\n"
            f"🏟 <b>Событие:</b> {bet['match_title']}\n"
            f"🎯 <b>Прогноз:</b> <code>{bet['pick']}</code> (кэф <code>{bet['odds']}</code>)\n"
            f"🏁 <b>Реальный счет:</b> <code>{score_str}</code></blockquote>\n"
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
            pending_bets = await db_manager.get_all_pending_bets()
            if pending_bets:
                async with aiohttp.ClientSession() as session:
                    for b in pending_bets:
                        await check_and_settle_real_bet(session, b)
        except Exception as e:
            logging.error(f"Ошибка фонового расчета реальных матчей: {e}")
        await asyncio.sleep(180)

# ================= РАЗНООБРАЗНАЯ АНАЛИТИКА И ЭКСПРЕСС ДНЯ =================
def build_daily_express_data(db: dict) -> dict | None:
    all_upcoming = []
    for l_val in db.values():
        for m in l_val.get("matches", {}).values():
            all_upcoming.append(m)

    all_upcoming.sort(key=lambda x: x["start_ts"])
    selected = all_upcoming[:6]
    if not selected:
        return None

    picks_text = []
    short_titles = []
    legs = []
    total_odd = 1.0
    combined_prob = 100.0
    max_end_ts = 0

    for idx, m in enumerate(selected):
        t1, t2 = m["home_team"], m["away_team"]
        o = m["odds"]
        probs = calculate_ai_probabilities(o)
        if m["end_ts"] > max_end_ts:
            max_end_ts = m["end_ts"]

        # Умный выбор разнообразных рынков для экспресса (исходы, тоталы, ОЗ)
        if probs["p1"] >= 58:
            pick_code, bet_str, k, p = "p1", f"П1 ({t1})", o["p1"], probs["p1"]
        elif probs["p2"] >= 54:
            pick_code, bet_str, k, p = "p2", f"П2 ({t2})", o["p2"], probs["p2"]
        elif o["tb25"] <= 1.76 and idx % 2 == 0:
            pick_code, bet_str, k, p = "tb25", "ТБ 2.5 (Тотал Больше 2.5)", o["tb25"], probs["tb25"]
        elif abs(probs["p1"] - probs["p2"]) <= 11:
            pick_code, bet_str, k, p = "btts", "ОЗ: Да (Обе забьют)", o["btts"], probs["btts"]
        else:
            pick_code, bet_str, k, p = "tb15", "ТБ 1.5 (Минимум 2 гола)", o["tb15"], probs["tb15"]

        total_odd *= k
        combined_prob *= (p / 100.0)
        picks_text.append(
            f"<b>{len(picks_text)+1}. {m['teams']}</b> <i>({m['date']})</i>\n"
            f"   🎯 Прогноз: <code>{bet_str}</code> • Кэф: <b><code>{k}</code></b>"
        )
        short_titles.append(f"{m['teams']} ({PICK_LABELS.get(pick_code, bet_str)})")
        legs.append({
            "league_slug": m["league_slug"],
            "event_id": m["event_id"],
            "teams": m["teams"],
            "pick_code": pick_code,
            "pick_label": bet_str
        })

    final_odd = round(total_odd, 2)
    return {
        "text": "\n\n".join(picks_text) + f"\n\n<blockquote>📈 <b>Итоговый коэффициент:</b> <code>{final_odd}</code></blockquote>",
        "total_odd": final_odd,
        "prob": round(combined_prob * 100, 1),
        "end_ts": max_end_ts,
        "summary_title": f"Экспресс дня ({len(legs)} матчей)",
        "summary_pick": " + ".join(short_titles[:3]) + (f" и еще {len(legs)-3}" if len(legs) > 3 else ""),
        "legs": legs
    }

def smart_local_match_analysis(match: dict, probs: dict) -> str:
    t1, t2 = match["home_team"], match["away_team"]
    odds = match["odds"]
    p1, x, p2 = probs["p1"], probs["x"], probs["p2"]

    if p1 >= 60:
        style = f"⚔️ <b>Тактический расклад:</b> {t1} имеет весомое преимущество домашнего поля и класса ({p1}%). Ожидается интенсивный прессинг хозяев с первых минут."
        bet = f"🎯 <b>Лучший выбор:</b> П1 ({t1}) за <code>{odds['p1']}</code> или надежный ТБ 1.5 за <code>{odds['tb15']}</code>"
    elif p2 >= 53:
        style = f"⚔️ <b>Тактический расклад:</b> {t2} сильнее в быстрых переходных фазах и реализации моментов ({p2}% против {p1}%)."
        bet = f"🎯 <b>Лучший выбор:</b> П2 ({t2}) за <code>{odds['p2']}</code> (надежная альтернатива: ТБ 1.5 за <code>{odds['tb15']}</code>)"
    elif odds["tb25"] <= 1.78:
        style = f"⚔️ <b>Тактический расклад:</b> Встреча двух атакующих команд с высоким потенциалом xG. Оборона обеих сторон регулярно допускает моменты."
        bet = f"🎯 <b>Лучший выбор:</b> ТБ 2.5 за <code>{odds['tb25']}</code> или Обе забьют (Да) за <code>{odds['btts']}</code>"
    elif abs(p1 - p2) <= 12:
        style = f"⚔️ <b>Тактический расклад:</b> Абсолютно равное противостояние ({p1}% на {p2}%). В таких матчах исход часто решает обмен голами."
        bet = f"🎯 <b>Лучший выбор:</b> Обе забьют (Да) за <code>{odds['btts']}</code> или ТБ 1.5 за <code>{odds['tb15']}</code>"
    else:
        style = f"⚔️ <b>Тактический расклад:</b> Умеренное преимущество {t1} ({p1}%), но {t2} опасен на контратаках и стандартах."
        bet = f"🎯 <b>Лучший выбор:</b> Тотал Больше 1.5 за <code>{odds['tb15']}</code> или П1 за <code>{odds['p1']}</code>"
    return f"{style}\n\n{bet}"

# ================= КЛАВИАТУРЫ (ЧИСТЫЙ ИНТЕРФЕЙС) =================
def main_menu_kb(user_id: int = 0):
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Личный кабинет", callback_data="profile")
    builder.button(text="🏆 Лига Чемпионов", callback_data="league:ucl")
    builder.button(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)", callback_data="league:epl")
    builder.button(text="🇪🇸 Ла Лига (Испания)", callback_data="league:laliga")
    builder.button(text="🇮🇹 Серия А (Италия)", callback_data="league:seriea")
    builder.button(text="🇩🇪 Бундеслига", callback_data="league:bundesliga")
    builder.button(text="🇫🇷 Лига 1 (Франция)", callback_data="league:ligue1")
    builder.button(text="⚡ Экспресс дня (Топ-6)", callback_data="express_day")
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
    for match_id, data in list(matches_dict.items())[:15]:
        short_date = data['date'].replace(".2026", "").replace(" МСК", "")
        builder.button(text=f"{data['teams']} • {short_date}", callback_data=f"match:{league_key}:{match_id}")
    builder.button(text="🔄 Обновить расписание", callback_data=f"refresh_league:{league_key}")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def match_outcomes_kb(league_key: str, match_id: str, odds: dict, user_id: int):
    """Аккуратная сетка из 7 рынков (Исходы + Тоталы + ОЗ) без визуального перегруза"""
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()
    # Ряд 1: Основные исходы (3 кнопки)
    builder.button(text=f"П1 ({odds['p1']})", callback_data=f"pick:{league_key}:{match_id}:p1")
    builder.button(text=f"Х ({odds['x']})", callback_data=f"pick:{league_key}:{match_id}:x")
    builder.button(text=f"П2 ({odds['p2']})", callback_data=f"pick:{league_key}:{match_id}:p2")
    # Ряд 2: Тоталы Больше (2 кнопки)
    builder.button(text=f"ТБ 1.5 ({odds['tb15']})", callback_data=f"pick:{league_key}:{match_id}:tb15")
    builder.button(text=f"ТБ 2.5 ({odds['tb25']})", callback_data=f"pick:{league_key}:{match_id}:tb25")
    # Ряд 3: Тотал Меньше и Обе забьют (2 кнопки)
    builder.button(text=f"ТМ 2.5 ({odds['tm25']})", callback_data=f"pick:{league_key}:{match_id}:tm25")
    builder.button(text=f"ОЗ: Да ({odds['btts']})", callback_data=f"pick:{league_key}:{match_id}:btts")

    if slip_count > 0:
        builder.button(text=f"🧺 Мой купон экспресса ({slip_count})", callback_data="view_slip")

    builder.button(text="⬅️ К матчам лиги", callback_data=f"league:{league_key}")
    builder.button(text="🏠 Меню", callback_data="back_to_main")

    if slip_count > 0:
        builder.adjust(3, 2, 2, 1, 2)
    else:
        builder.adjust(3, 2, 2, 2)
    return builder.as_markup()

def amount_selection_kb(target_code: str, balance: float):
    builder = InlineKeyboardBuilder()
    for amt in [100, 250, 500, 1000]:
        builder.button(text=f"💵 {amt} FC", callback_data=f"place:{target_code}:{amt}")
    all_in = int(balance) if balance >= 10 else 0
    if all_in >= 10:
        builder.button(text=f"🔥 Ва-банк ({all_in} FC)", callback_data=f"place:{target_code}:{all_in}")
    builder.button(text="✍️ Ввести свою сумму", callback_data=f"custom_amt:{target_code}")

    if target_code == "express-day":
        builder.button(text="⬅️ Назад к Экспрессу", callback_data="express_day")
        builder.adjust(2, 2, 1, 1, 1)
    elif target_code == "custom-slip":
        builder.button(text="⬅️ Назад к купону", callback_data="view_slip")
        builder.adjust(2, 2, 1, 1, 1)
    else:
        l_key, m_id, p_code = target_code.split("-")
        builder.button(text="➕ Добавить этот исход в мой Экспресс", callback_data=f"slipadd:{l_key}:{m_id}:{p_code}")
        builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{l_key}:{m_id}")
        builder.adjust(2, 2, 1, 1, 1, 1)

    return builder.as_markup()

# ================= ОБРАБОТЧИКИ СОБЫТИЙ =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await db_manager.get_or_create_user(message.from_user.id, message.from_user.username)
    text = (
        f"⚽ <b>AI_BET_BOT — РЕАЛЬНАЯ ЛИНИЯ И СТАВКИ</b>\n\n"
        f"<blockquote>👤 Игрок: <b>{user['username']}</b>\n"
        f"💰 Доступный банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"🏆 Выиграно купонов: <b><code>{user['wins']}</code></b></blockquote>\n"
        f"📡 <b>Live-синхронизация:</b> Реальные матчи, расширенная линия (Исходы, Тоталы, ОЗ) и расчет по настоящему финальному счету.\n\n"
        f"👇 <b>Выбери раздел:</b>"
    )
    await message.answer(text, reply_markup=main_menu_kb(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_main")
async def process_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    text = (
        f"⚽ <b>ГЛАВНОЕ МЕНЮ • AI_BET_BOT</b>\n\n"
        f"<blockquote>💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>  |  🏆 Побед: <b><code>{user['wins']}</code></b></blockquote>\n"
        f"👇 <b>Выбери турнир или открой Личный кабинет:</b>"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb(callback.from_user.id), parse_mode="HTML")
    await callback.answer()

# ================= ЛИЧНЫЙ КАБИНЕТ И LIVE-РАДАР =================
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
        f"<i>📡 Бот отслеживает реальные результаты матчей и пришлет уведомление сразу после финального свистка.</i>"
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
            "Открой любую лигу или «⚡ Экспресс дня», чтобы сделать ставку на предстоящие матчи!"
        )
    else:
        lines = []
        for b in bets:
            end_dt = datetime.fromtimestamp(b["settle_ts"], tz=MSK_TZ).strftime("%d.%m в %H:%M МСК")
            btype = "⚡ Экспресс" if b.get("bet_type") == "express" else "⚽ Ординар"
            pot_win = round(b["amount"] * b["odds"], 1)
            lines.append(
                f"<blockquote>🎫 <b>Купон #{b['bet_id']}</b> ({btype})\n"
                f"🏟 <b>{b['match_title']}</b>\n"
                f"🎯 Исход: <code>{b['pick']}</code>  •  Кэф: <b><code>{b['odds']}</code></b>\n"
                f"💵 Ставка: <code>{b['amount']} FC</code> ➔ Выплата: <b><code>{pot_win} FC</code></b>\n"
                f"⏱ Ориентир окончания: <i>{end_dt}</i></blockquote>"
            )
        text = "⏳ <b>МОИ АКТИВНЫЕ КУПОНЫ В ИГРЕ:</b>\n\n" + "\n".join(lines)
        builder.button(text="📡 Проверить Live-счет и статус матчей", callback_data="check_live_status")

    builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
    builder.button(text="⬅️ В кабинет", callback_data="profile")
    if bets:
        builder.adjust(1, 2)
    else:
        builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "check_live_status")
async def process_check_live_status(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    if not bets:
        await callback.answer("У тебя нет активных купонов!", show_alert=True)
        return

    settled_count = 0
    live_info = []
    async with aiohttp.ClientSession() as session:
        for b in bets:
            res = await check_and_settle_real_bet(session, b)
            if res["settled"]:
                settled_count += 1
            else:
                live_info.append(f"#{b['bet_id']}: {res.get('live_summary', '')}")

    if settled_count > 0:
        await callback.answer(f"✅ Рассчитано завершенных купонов: {settled_count}! Проверь чат.", show_alert=True)
        await process_profile(callback)
    else:
        clean_alert = re.sub(r"<.*?>", "", "\n".join(live_info))[:195]
        await callback.answer(f"📡 Статус реальных матчей:\n{clean_alert}", show_alert=True)

@dp.callback_query(F.data == "archive_bets")
async def process_archive_bets(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=False)
    if not bets:
        text = (
            "🗄 <b>АРХИВ СТАВОК ПУСТ</b>\n\n"
            "<blockquote>Сюда попадают все купоны после официального завершения реальных матчей.</blockquote>"
        )
    else:
        lines = []
        for b in bets:
            is_win = b["status"] == "win"
            badge = f"✅ ВЫИГРЫШ (+{round(b['amount']*b['odds'], 1)} FC)" if is_win else f"❌ ПРОИГРЫШ (-{b['amount']} FC)"
            score_info = f"\n🏁 Реальный счет: <code>{b['score_result']}</code>" if b.get("score_result") else ""
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
    db = await get_real_matches()
    exp_data = build_daily_express_data(db)

    builder = InlineKeyboardBuilder()
    if not exp_data:
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        await callback.message.edit_text("На ближайшие дни матчей не найдено.", reply_markup=builder.as_markup())
        return

    builder.button(
        text=f"🔥 Поставить на Экспресс (Кэф {exp_data['total_odd']})",
        callback_data="pick:express_day:all:exp"
    )
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)

    text = (
        f"⚡ <b>ЭКСПРЕСС ДНЯ (КОМБИНИРОВАННАЯ ЛИНИЯ)</b>\n\n"
        f"{exp_data['text']}\n\n"
        f"👇 <i>Нажми кнопку ниже, чтобы поставить на весь экспресс одним купоном:</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("slipadd:"))
async def process_slip_add(callback: CallbackQuery):
    _, league_key, match_id, pick_code = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await callback.answer("⛔ Матч уже начался или линия обновилась!", show_alert=True)
        return

    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)
    pick_label = PICK_LABELS.get(pick_code, pick_code.upper())

    uid = callback.from_user.id
    slip = USER_SLIPS.get(uid, [])
    slip = [item for item in slip if item["event_id"] != match["event_id"]]
    if len(slip) >= 6:
        await callback.answer("⚠️ В один экспресс можно добавить максимум 6 матчей!", show_alert=True)
        return

    slip.append({
        "event_id": match["event_id"],
        "league_slug": match["league_slug"],
        "match_title": match["teams"],
        "pick_code": pick_code,
        "pick": pick_label,
        "odds": odds[pick_code],
        "prob": probs.get(pick_code, 50.0),
        "start_ts": match["start_ts"],
        "end_ts": match["end_ts"]
    })
    USER_SLIPS[uid] = slip
    await callback.answer(
        f"✅ Добавлено в экспресс: {match['teams']} — {pick_label} ({odds[pick_code]}). В купоне: {len(slip)}",
        show_alert=True
    )
    # Возвращаем игрока к карточке матча с обновленным счетчиком купона экспресса
    await process_match_select(callback)

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

# ================= ВЫБОР РЕАЛЬНОГО МАТЧА И ОФОРМЛЕНИЕ СТАВКИ =================
@dp.callback_query(F.data.startswith("refresh_league:"))
async def process_refresh_league(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    await callback.answer("📡 Синхронизация реального расписания...")
    db = await get_real_matches(force_refresh=True)
    league_data = db.get(league_key, {})
    matches = league_data.get("matches", {})
    if not matches:
        text = f"<b>{league_data.get('title', 'Лига')}</b>\n\n<blockquote>📅 На ближайшие дни официальных матчей не найдено.</blockquote>"
    elif league_data.get("extended"):
        text = f"<b>{league_data['title']}</b>\n📅 <i>В ближайшие 7 дней перерыв между турами — показаны матчи ближайшего тура (МСК):</i>"
    else:
        text = f"<b>{league_data['title']}</b>\n📅 Реальное расписание на ближайшие 7 дней (МСК):"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")

@dp.callback_query(F.data.startswith("league:"))
async def process_league_select(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    db = await get_real_matches()
    league_data = db.get(league_key, {})
    matches = league_data.get("matches", {})

    if not matches:
        text = (
            f"<b>{league_data.get('title', 'Турнир')}</b>\n\n"
            f"<blockquote>📅 На ближайшие дни матчей не найдено. Нажми «Обновить расписание».</blockquote>"
        )
    elif league_data.get("extended"):
        text = f"<b>{league_data['title']}</b>\n📅 <i>В ближайшие 7 дней перерыв между турами — показаны матчи ближайшего тура (время МСК):</i>"
    else:
        text = f"<b>{league_data['title']}</b>\n📅 Реальные матчи на ближайшие 7 дней (время МСК):"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("match:"))
async def process_match_select(callback: CallbackQuery):
    parts = callback.data.split(":")
    league_key, match_id = parts[1], parts[2]
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await callback.answer("⛔ Этот матч уже начался или завершен!", show_alert=True)
        return

    league_title = db[league_key]["title"]
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)

    # Если разбора еще нет в кэше — показываем статус загрузки
    if match["event_id"] not in AI_CACHE:
        await callback.message.edit_text(f"🧠 <i>ИИ анализирует статистику {match['teams']}...</i>", parse_mode="HTML")

    prompt = (
        f"Предстоящий матч. Турнир: {league_title}. Дата: {match['date']}.\n"
        f"Матч: {match['teams']}. Статистика сезона: {match['records_info']}.\n"
        f"Линия: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}, ТБ 1.5={odds['tb15']}, ТБ 2.5={odds['tb25']}, ТМ 2.5={odds['tm25']}, ОЗ(Да)={odds['btts']}.\n"
        f"Дай краткий экспертный разбор (до 60 слов) в 2 пункта:\n"
        f"1. ⚔️ Тактический рисунок игры и атакующий потенциал.\n"
        f"2. 🎯 Самая выгодная ставка из ВСЕЙ линии (можно выбрать Тотал ТБ 1.5 / ТБ 2.5 / ТМ 2.5, Обе забьют или исход П1/Х/П2 — выбери то, что реально надежнее для этого матча) с кэфом."
    )
    ai_verdict = await ask_ai_cached(match["event_id"], prompt) or smart_local_match_analysis(match, probs)

    text = (
        f"🏟 <b>{match['teams']}</b>\n"
        f"🕒 Начало: <code>{match['date']}</code>\n\n"
        f"<blockquote>📊 <b>Основные исходы (Вероятность):</b>\n"
        f"П1: <b><code>{odds['p1']}</code></b> ({probs['p1']}%)  |  Х: <b><code>{odds['x']}</code></b> ({probs['x']}%)  |  П2: <b><code>{odds['p2']}</code></b> ({probs['p2']}%)\n"
        f"⚽ <b>Рынок голов:</b>\n"
        f"ТБ 1.5: <b><code>{odds['tb15']}</code></b>  |  ТБ 2.5: <b><code>{odds['tb25']}</code></b>  |  ТМ 2.5: <b><code>{odds['tm25']}</code></b>  |  ОЗ: <b><code>{odds['btts']}</code></b></blockquote>\n"
        f"🤖 <b>Аналитика ИИ:</b>\n{ai_verdict}\n\n"
        f"👇 <b>Выбери исход для ставки (или добавления в экспресс):</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=match_outcomes_kb(league_key, match_id, odds, callback.from_user.id),
        parse_mode="HTML"
    )
    await callback.answer()

async def resolve_bet_target(target_code: str, user_id: int) -> dict | None:
    db = await get_real_matches()
    now_ts = int(now_msk().timestamp())

    if target_code == "express-day":
        exp = build_daily_express_data(db)
        if not exp:
            return None
        return {
            "match_title": exp["summary_title"],
            "pick": exp["summary_pick"],
            "odds": exp["total_odd"],
            "prob": exp["prob"],
            "end_ts": exp["end_ts"],
            "bet_type": "express",
            "legs_json": json.dumps(exp["legs"], ensure_ascii=False)
        }
    elif target_code == "custom-slip":
        slip = USER_SLIPS.get(user_id, [])
        if not slip:
            return None
        total_odd = 1.0
        comb_prob = 1.0
        max_ts = 0
        titles = []
        legs = []
        for s in slip:
            if s["start_ts"] <= now_ts:
                return None
            total_odd *= s["odds"]
            comb_prob *= (s["prob"] / 100.0)
            if s["end_ts"] > max_ts:
                max_ts = s["end_ts"]
            titles.append(f"{s['match_title']} ({s['pick']})")
            legs.append({
                "league_slug": s["league_slug"],
                "event_id": s["event_id"],
                "teams": s["match_title"],
                "pick_code": s["pick_code"],
                "pick_label": s["pick"]
            })
        return {
            "match_title": f"Персональный экспресс ({len(slip)} матчей)",
            "pick": " + ".join(titles),
            "odds": round(total_odd, 2),
            "prob": round(comb_prob * 100, 1),
            "end_ts": max_ts,
            "bet_type": "express",
            "legs_json": json.dumps(legs, ensure_ascii=False)
        }
    else:
        l_key, m_id, p_code = target_code.split("-")
        match = db.get(l_key, {}).get("matches", {}).get(m_id)
        if not match or match["start_ts"] <= now_ts:
            return None
        odds = match["odds"]
        probs = calculate_ai_probabilities(odds)
        pick_label = PICK_LABELS.get(p_code, p_code.upper())
        legs = [{
            "league_slug": match["league_slug"],
            "event_id": match["event_id"],
            "teams": match["teams"],
            "pick_code": p_code,
            "pick_label": pick_label
        }]
        return {
            "match_title": f"{match['teams']} ({match['date']})",
            "pick": pick_label,
            "odds": odds[p_code],
            "prob": probs.get(p_code, 50.0),
            "end_ts": match["end_ts"],
            "bet_type": "single",
            "legs_json": json.dumps(legs, ensure_ascii=False)
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

    info = await resolve_bet_target(target_code, callback.from_user.id)
    if not info:
        await callback.answer("⛔ Матч уже начался или купон устарел!", show_alert=True)
        return

    user = await db_manager.get_or_create_user(callback.from_user.id, callback.from_user.username)
    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m.%Y в %H:%M МСК")

    text = (
        f"🎫 <b>ОФОРМЛЕНИЕ КУПОНА</b>\n\n"
        f"<blockquote>🏟 <b>Событие:</b> {info['match_title']}\n"
        f"🎯 <b>Выбранный рынок:</b> <code>{info['pick']}</code>\n"
        f"📈 <b>Коэффициент:</b> <b><code>{info['odds']}</code></b>\n"
        f"⏱ <b>Расчет по финальному свистку:</b> <i>~{end_str}</i></blockquote>\n"
        f"💰 <b>Доступный баланс:</b> <code>{round(user['balance'], 1)} FC</code>\n\n"
        f"👇 <b>Выбери сумму для ординара или добавь исход в свой Экспресс:</b>"
    )
    await callback.message.edit_text(text, reply_markup=amount_selection_kb(target_code, user["balance"]), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("place:"))
async def process_place_fixed_amount(callback: CallbackQuery):
    _, target_code, amt_str = callback.data.split(":")
    amount = int(amt_str)
    info = await resolve_bet_target(target_code, callback.from_user.id)
    if not info:
        await callback.answer("⛔ Прием ставок закрыт: матч уже начался!", show_alert=True)
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
        bet_type=info["bet_type"],
        legs_json=info["legs_json"]
    )

    if not res["ok"]:
        await callback.answer(f"⚠️ {res['error']}", show_alert=True)
        return

    if target_code == "custom-slip":
        USER_SLIPS.pop(callback.from_user.id, None)

    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m в %H:%M МСК")
    text = (
        f"✅ <b>СТАВКА ПРИНЯТА! (КУПОН #{res['bet_id']})</b>\n\n"
        f"<blockquote>🏟 <b>Событие:</b> {info['match_title']}\n"
        f"🎯 <b>Прогноз:</b> <code>{info['pick']}</code>  •  Кэф: <b><code>{info['odds']}</code></b>\n"
        f"💵 <b>Сумма ставки:</b> <code>{amount} FC</code>\n"
        f"💰 <b>Возможная выплата:</b> <b><code>{res['potential_win']} FC</code></b></blockquote>\n"
        f"🏦 <b>Остаток на балансе:</b> <code>{res['new_balance']} FC</code>\n"
        f"📡 <b>Расчет после завершения реального матча:</b> <i>~{end_str}</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ Мои активные ставки", callback_data="active_bets")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer("🎫 Купон зарегистрирован в системе!")

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
    info = await resolve_bet_target(target_code, message.from_user.id)
    if not info:
        await state.clear()
        await message.answer("⛔ Матч уже начался или купон устарел.", reply_markup=main_menu_kb(message.from_user.id))
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
        bet_type=info["bet_type"],
        legs_json=info["legs_json"]
    )

    if not res["ok"]:
        await message.answer(f"⚠️ {res['error']}\nВведи другую сумму:")
        return

    await state.clear()
    if target_code == "custom-slip":
        USER_SLIPS.pop(message.from_user.id, None)

    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m в %H:%M МСК")
    text = (
        f"✅ <b>СТАВКА ПРИНЯТА! (КУПОН #{res['bet_id']})</b>\n\n"
        f"<blockquote>🏟 <b>Событие:</b> {info['match_title']}\n"
        f"🎯 <b>Прогноз:</b> <code>{info['pick']}</code>  •  Кэф: <b><code>{info['odds']}</code></b>\n"
        f"💵 <b>Сумма ставки:</b> <code>{amount} FC</code>\n"
        f"💰 <b>Возможная выплата:</b> <b><code>{res['potential_win']} FC</code></b></blockquote>\n"
        f"🏦 <b>Остаток на балансе:</b> <code>{res['new_balance']} FC</code>\n"
        f"📡 <b>Расчет после завершения реального матча:</b> <i>~{end_str}</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ Мои активные ставки", callback_data="active_bets")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ================= ВЕБ-СЕРВЕР И ЗАПУСК =================
async def handle_ping(request):
    return web.Response(text="AI_BET_BOT Live Sports Engine is running 24/7!")

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
    await get_real_matches(force_refresh=True)
    await start_web_server()
    asyncio.create_task(match_settlement_worker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
