import os
import re
import math
import json
import random
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import aiohttp
from aiohttp import web
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, CommandObject
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
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

USER_SLIPS = {}
SUPEREXPRESS_DRAFTS = {}
AI_CACHE = {}
BOT_USERNAME = ""

class BetStates(StatesGroup):
    waiting_for_custom_total = State()
    waiting_for_custom_amount = State()
    waiting_for_nickname = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_gift_data = State()

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

# ================= КОНФИГУРАЦИЯ ТУРНИРОВ (ТОП-5 + ДРУГИЕ ЛИГИ) =================
MSK_TZ = timezone(timedelta(hours=3))

MAIN_LEAGUES = {
    "ucl": {"title": "🏆 Лига Чемпионов", "slug": "uefa.champions"},
    "epl": {"title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)", "slug": "eng.1"},
    "laliga": {"title": "🇪🇸 Ла Лига (Испания)", "slug": "esp.1"},
    "seriea": {"title": "🇮🇹 Серия А (Италия)", "slug": "ita.1"},
    "bundesliga": {"title": "🇩🇪 Бундеслига", "slug": "ger.1"},
    "ligue1": {"title": "🇫🇷 Лига 1 (Франция)", "slug": "fra.1"}
}

OTHER_LEAGUES = {
    "uel": {"title": "🏆 Лига Европы", "slug": "uefa.europa"},
    "uecl": {"title": "🏆 Лига Конференций", "slug": "uefa.europa.conference"},
    "por": {"title": "🇵🇹 Португалия", "slug": "por.1"},
    "ned": {"title": "🇳🇱 Нидерланды", "slug": "ned.1"},
    "tur": {"title": "🇹🇷 Турция", "slug": "tur.1"},
    "eng2": {"title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Чемпионшип", "slug": "eng.2"},
    "bra": {"title": "🇧🇷 Бразилия", "slug": "bra.1"}
}

LEAGUES_CONFIG = {**MAIN_LEAGUES, **OTHER_LEAGUES}

POPULAR_CLUBS = [
    "Реал Мадрид", "Барселона", "Арсенал", "Ливерпуль",
    "Ман Сити", "Ман Юнайтед", "Челси", "Бавария",
    "Боруссия Д", "Байер", "Интер", "Милан",
    "Ювентус", "Наполи", "ПСЖ", "Атлетико",
    "Бенфика", "Спортинг", "Галатасарай", "Фенербахче"
]

FOOTBALL_NICK_BASES = [
    "El_Capitano", "VAR_Oracle", "xG_Master", "TikiTaka_Pro",
    "GoldenBoot", "Sniper_FC", "Phantom_Striker", "Bets_Maestro",
    "Ultra_Scout", "Derby_Boss", "Playmaker", "BoxToBox",
    "HatTrick_King", "TotalOver", "CleanSheet", "Grand_Capper"
]

FORBIDDEN_NICK_WORDS = {
    "admin", "админ", "administrator", "администратор",
    "ai_bet_bot", "support", "саппорт", "поддержка",
    "модератор", "moderator", "system", "система", "bot", "бот"
}

ACHIEVEMENTS_CONFIG = {
    "first_bet": {"title": "🟢 Первый шаг", "desc": "Сделать первую ставку в боте", "reward": 150},
    "first_win": {"title": "🟢 В яблочко", "desc": "Одержать первую победу по ординару", "reward": 250},
    "first_express": {"title": "🟢 Конструктор", "desc": "Собрать и поставить первый экспресс", "reward": 300},
    "first_bonus": {"title": "🟢 Свой среди своих", "desc": "Забрать первый ежедневный бонус", "reward": 100},
    "streak_3": {"title": "🟡 Хет-трик", "desc": "Выиграть 3 ставки подряд", "reward": 500},
    "streak_7": {"title": "🟡 Снайпер тура", "desc": "Выиграть 7 ставок подряд", "reward": 2000},
    "express_10": {"title": "🟡 Железный пресс", "desc": "Выиграть экспресс с кэфом от 10.0+", "reward": 2500},
    "high_odd_4": {"title": "🟡 Ловец сенсаций", "desc": "Выиграть ординар с кэфом от 4.0+", "reward": 1500},
    "totals_5": {"title": "🟡 Тотальный контроль", "desc": "Выиграть 5 ставок на тоталы (ТБ/ТМ/ИТБ)", "reward": 750},
    "cashout_profit": {"title": "🟣 Хладнокровие", "desc": "Использовать досрочный выкуп CashOut", "reward": 350},
    "all_in_win": {"title": "🟣 Ва-банк", "desc": "Рискнуть всем банком и победить", "reward": 1000},
    "bal_10k": {"title": "🟣 Капиталист", "desc": "Достичь баланса 10 000 FC", "reward": 1500},
    "bal_50k": {"title": "🟣 Магнат лиги", "desc": "Достичь баланса 50 000 FC", "reward": 5000},
    "ref_1": {"title": "🔵 Скаут", "desc": "Пригласить первого друга по ссылке", "reward": 500},
    "ref_5": {"title": "🔵 Футбольный синдикат", "desc": "Пригласить 5 друзей в проект", "reward": 2500}
}

BOOSTER_NAMES = {
    "insure50": "🛡 Страховка 50% (возврат половины при проигрыше)",
    "boost035": "⚡ Кэф-буст +0.35 к следующей ставке"
}

TEAM_TRANSLATIONS = {
    # Англия (АПЛ + Чемпионшип)
    "Arsenal": "Арсенал", "Aston Villa": "Астон Вилла", "Bournemouth": "Борнмут", "AFC Bournemouth": "Борнмут",
    "Brentford": "Брентфорд", "Brighton & Hove Albion": "Брайтон", "Brighton": "Брайтон", "Chelsea": "Челси",
    "Crystal Palace": "Кристал Пэлас", "Everton": "Эвертон", "Fulham": "Фулхэм", "Ipswich Town": "Ипсвич",
    "Leicester City": "Лестер", "Liverpool": "Ливерпуль", "Manchester City": "Ман Сити",
    "Manchester United": "Ман Юнайтед", "Newcastle United": "Ньюкасл", "Nottingham Forest": "Ноттингем",
    "Southampton": "Саутгемптон", "Tottenham Hotspur": "Тоттенхэм", "West Ham United": "Вест Хэм",
    "Wolverhampton Wanderers": "Вулверхэмптон", "Leeds United": "Лидс", "Burnley": "Бернли",
    "Sunderland": "Сандерленд", "Sheffield United": "Шеффилд Ютд", "West Bromwich Albion": "Вест Бромвич",
    "Middlesbrough": "Мидлсбро", "Norwich City": "Норвич", "Coventry City": "Ковентри",
    "Watford": "Уотфорд", "Blackburn Rovers": "Блэкберн", "Bristol City": "Бристоль Сити",
    "Hull City": "Халл Сити", "Stoke City": "Сток Сити", "Swansea City": "Суонси", "Millwall": "Миллуолл",
    "Queens Park Rangers": "КПР", "Preston North End": "Престон", "Cardiff City": "Кардифф",
    # Испания
    "Real Madrid": "Реал Мадрид", "Barcelona": "Барселона", "Atlético Madrid": "Атлетико",
    "Atletico Madrid": "Атлетико", "Athletic Club": "Атлетик Б", "Real Sociedad": "Реал Сосьедад",
    "Real Betis": "Бетис", "Villarreal": "Вильярреал", "Valencia": "Валенсия", "Sevilla": "Севилья",
    "Girona": "Жирона", "Celta Vigo": "Сельта", "Osasuna": "Осасуна", "Getafe": "Хетафе",
    "Rayo Vallecano": "Райо Вальекано", "Mallorca": "Мальорка", "Las Palmas": "Лас-Пальмас",
    "Alavés": "Алавес", "Deportivo Alavés": "Алавес", "Espanyol": "Эспаньол", "Leganés": "Леганес",
    "Real Valladolid": "Вальядолид",
    # Италия
    "Internazionale": "Интер", "Inter Milan": "Интер", "AC Milan": "Милан", "Juventus": "Ювентус",
    "Napoli": "Наполи", "AS Roma": "Рома", "Roma": "Рома", "Lazio": "Лацио", "Atalanta": "Аталанта",
    "Fiorentina": "Фиорентина", "Bologna": "Болонья", "Torino": "Торино", "Udinese": "Удинезе",
    "Genoa": "Дженоа", "Como": "Комо", "Parma": "Парма", "Hellas Verona": "Верона",
    "Empoli": "Эмполи", "Cagliari": "Кальяри", "Lecce": "Лечче", "Monza": "Монца", "Venezia": "Венеция",
    # Германия
    "Bayern Munich": "Бавария", "Borussia Dortmund": "Боруссия Д", "Bayer Leverkusen": "Байер",
    "RB Leipzig": "РБ Лейпциг", "VfB Stuttgart": "Штутгарт", "Eintracht Frankfurt": "Айнтрахт Ф",
    "SC Freiburg": "Фрайбург", "TSG Hoffenheim": "Хоффенхайм", "Werder Bremen": "Вердер",
    "Heidenheim": "Хайденхайм", "1. FC Heidenheim 1846": "Хайденхайм", "FC Augsburg": "Аугсбург",
    "VfL Wolfsburg": "Вольфсбург", "Borussia Mönchengladbach": "Боруссия М", "Mainz": "Майнц",
    "1. FSV Mainz 05": "Майнц", "1. FC Union Berlin": "Унион Берлин", "VfL Bochum": "Бохум",
    "FC St. Pauli": "Санкт-Паули", "Holstein Kiel": "Хольштайн", "Hamburger SV": "Гамбург", "FC Cologne": "Кельн",
    # Франция
    "Paris Saint-Germain": "ПСЖ", "AS Monaco": "Монако", "Monaco": "Монако", "Marseille": "Марсель",
    "Olympique de Marseille": "Марсель", "Lille": "Лилль", "LOSC Lille": "Лилль", "Lyon": "Лион",
    "Olympique Lyonnais": "Лион", "Nice": "Ницца", "OGC Nice": "Ницца", "Lens": "Ланс", "RC Lens": "Ланс",
    "Rennes": "Ренн", "Stade Rennais": "Ренн", "Stade Brestois 29": "Брест", "Brest": "Брест",
    "Reims": "Реймс", "Stade de Reims": "Реймс", "Strasbourg": "Страсбур", "RC Strasbourg Alsace": "Страсбур",
    "Toulouse": "Тулуза", "Montpellier": "Монпелье", "Nantes": "Нант", "FC Nantes": "Нант",
    "Auxerre": "Осер", "AJ Auxerre": "Осер", "Angers": "Анже", "Saint-Étienne": "Сент-Этьен", "Le Havre": "Гавр",
    # Португалия, Нидерланды, Турция, Бразилия, Еврокубки
    "Sporting CP": "Спортинг", "Benfica": "Бенфика", "FC Porto": "Порту", "SC Braga": "Брага",
    "Vitória de Guimarães": "Витория Гим", "Famalicão": "Фамаликан", "Rio Ave": "Риу Аве", "Boavista": "Боавишта",
    "PSV Eindhoven": "ПСВ", "Feyenoord": "Фейеноорд", "Ajax": "Аякс", "AZ Alkmaar": "АЗ Алкмар",
    "FC Twente": "Твенте", "FC Utrecht": "Утрехт", "Sparta Rotterdam": "Спарта Р", "Heerenveen": "Херенвен",
    "Galatasaray": "Галатасарай", "Fenerbahce": "Фенербахче", "Fenerbahçe": "Фенербахче",
    "Besiktas": "Бешикташ", "Beşiktaş": "Бешикташ", "Trabzonspor": "Трабзонспор",
    "Istanbul Basaksehir": "Башакшехир", "Samsunspor": "Самсунспор", "Antalyaspor": "Антальяспор",
    "Flamengo": "Фламенго", "Palmeiras": "Палмейрас", "Botafogo": "Ботафого", "São Paulo": "Сан-Паулу",
    "Corinthians": "Коринтианс", "Fluminense": "Флуминенсе", "Grêmio": "Гремио", "Internacional": "Интернасьонал",
    "Atlético Mineiro": "Атлетико Минейро", "Cruzeiro": "Крузейро", "Vasco da Gama": "Васко да Гама", "Santos": "Сантос",
    "Celtic": "Селтик", "Rangers": "Рейнджерс", "Club Brugge": "Брюгге", "Anderlecht": "Андерлехт",
    "Shakhtar Donetsk": "Шахтер", "Red Bull Salzburg": "Зальцбург", "Sturm Graz": "Штурм Грац",
    "Sparta Prague": "Спарта Прага", "Slavia Prague": "Славия Прага", "Olympiacos": "Олимпиакос", "PAOK": "ПАОК"
}

ELITE_KEYWORDS = {
    "Реал Мадрид": 0.45, "Ман Сити": 0.45, "Бавария": 0.42, "Барселона": 0.40,
    "Ливерпуль": 0.40, "Арсенал": 0.38, "Интер": 0.36, "ПСЖ": 0.35, "Байер": 0.30,
    "Атлетико": 0.28, "Ювентус": 0.26, "Наполи": 0.26, "Челси": 0.24, "Милан": 0.22,
    "Боруссия Д": 0.22, "Спортинг": 0.28, "Бенфика": 0.26, "Порту": 0.25,
    "ПСВ": 0.28, "Аякс": 0.24, "Галатасарай": 0.26, "Фенербахче": 0.25, "Палмейрас": 0.24, "Фламенго": 0.24
}

def translate_team(name: str) -> str:
    return TEAM_TRANSLATIONS.get(name, name)

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

def get_user_rank_info(balance: float, is_vip: int) -> tuple[str, int]:
    if is_vip or balance >= 15000:
        return "👑 Легенда Уолл-Стрит", 1000
    elif balance >= 5000:
        return "🔥 Профи-аналитик", 500
    elif balance >= 1500:
        return "⚡ Скаут", 350
    else:
        return "🌱 Новичок лиги", 250

def generate_football_nickname() -> str:
    base = random.choice(FOOTBALL_NICK_BASES)
    num = random.randint(7, 99)
    return f"{base}_{num}"

def validate_custom_nickname(raw_nick: str) -> tuple[bool, str]:
    nick = raw_nick.strip()
    if len(nick) < 3 or len(nick) > 16:
        return False, "Длина никнейма должна быть от 3 до 16 символов."
    if not re.match(r"^[a-zA-Zа-яА-ЯёЁ0-9_\-\s]+$", nick):
        return False, "Разрешены только буквы, цифры, пробел, дефис и нижнее подчеркивание."
    low = nick.lower()
    for bad in FORBIDDEN_NICK_WORDS:
        if bad in low:
            return False, "Этот никнейм зарезервирован системой. Выбери другой."
    return True, nick

# ================= ПОШАГОВОЕ ФОРМАТИРОВАНИЕ СОБЫТИЙ ЭКСПРЕССА =================
def format_bet_legs_multiline(bet: dict, with_result: bool = False) -> str:
    try:
        legs = json.loads(bet.get("legs_json") or "[]")
    except Exception:
        legs = []

    if len(legs) > 1:
        lines = []
        for idx, leg in enumerate(legs, 1):
            t_name = leg.get("teams", "Матч")
            p_lbl = leg.get("pick_label") or leg.get("pick_code", "")
            l_odd = leg.get("odds", "")
            odd_str = f" (<code>{l_odd}</code>)" if l_odd else ""

            st = leg.get("final_status", "")
            f_score = leg.get("final_score", "")
            live_sc = leg.get("live_score", "")

            if st == "win":
                status_tag = f"✅ <b>{f_score}</b> (Сыграло)"
            elif st == "loss":
                status_tag = f"❌ <b>{f_score}</b> (Не прошло)"
            elif st == "push":
                status_tag = f"🔄 <b>{f_score}</b> (Возврат)"
            elif live_sc:
                status_tag = f"🔴 LIVE: <b>{live_sc}</b>"
            else:
                status_tag = "📅 Ожидает"

            lines.append(
                f"<b>{idx}. {t_name}</b>\n"
                f"   🎯 <code>{p_lbl}</code>{odd_str} • {status_tag}"
            )
        return "\n".join(lines)

    if legs:
        lg = legs[0]
        st = lg.get("final_status", "")
        f_score = lg.get("final_score") or bet.get("score_result", "")
        live_sc = lg.get("live_score", "")
        if with_result and f_score and bet.get("status") != "cashout":
            icon = "✅" if st == "win" else ("🔄 Возврат" if st == "push" else "❌")
            score_part = f"\n🏁 Реальный счет: <b><code>{f_score}</code></b> {icon}"
        elif live_sc:
            score_part = f"\n🔴 Идет матч: <b><code>{live_sc}</code></b>"
        else:
            score_part = ""
    else:
        score_part = f"\n🏁 Реальный счет: <b><code>{bet['score_result']}</code></b>" if (with_result and bet.get("score_result")) else ""

    return (
        f"🏟 <b>Матч:</b> {bet['match_title']}\n"
        f"🎯 <b>Прогноз:</b> <code>{bet['pick']}</code> (кэф <b><code>{bet['odds']}</code></b>){score_part}"
    )

# ================= МАТЕМАТИЧЕСКАЯ МОДЕЛЬ ПУАССОНА =================
def poisson_pmf(k: int, lam: float) -> float:
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)

def evaluate_custom_market(match: dict, pick_code: str) -> dict | None:
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)
    lam_total = match.get("exp_goals", 2.65)
    lam_h = match.get("lam_h", 1.45)
    lam_a = match.get("lam_a", 1.20)
    t1, t2 = match["home_team"], match["away_team"]

    code = pick_code.lower()
    if code in ("p1", "x", "p2", "1x", "x2", "f10", "f20", "btts", "btts_no"):
        labels = {
            "p1": f"П1 ({t1})",
            "x": "Х (Ничья)",
            "p2": f"П2 ({t2})",
            "1x": f"1Х ({t1} не проиграет)",
            "x2": f"Х2 ({t2} не проиграет)",
            "f10": f"Фора 1 (0) — {t1}",
            "f20": f"Фора 2 (0) — {t2}",
            "btts": "Обе забьют: Да",
            "btts_no": "Обе забьют: Нет"
        }
        return {
            "pick_code": code,
            "label": labels[code],
            "odds": odds[code],
            "prob": probs.get(code, 50.0)
        }

    if code.startswith("itb1_") or code.startswith("itb2_"):
        is_home = code.startswith("itb1_")
        try:
            line = float(code.split("_")[1])
        except Exception:
            return None
        lam_team = lam_h if is_home else lam_a
        team_name = t1 if is_home else t2
        prefix_lbl = f"ИТБ1 ({team_name})" if is_home else f"ИТБ2 ({team_name})"

        goal_probs = [poisson_pmf(k, lam_team) for k in range(12)]
        min_goals = int(math.floor(line)) + 1
        p_win = max(0.06, min(0.90, sum(goal_probs[k] for k in range(min_goals, 12))))
        calc_odd = round(max(1.10, min(15.0, 1.0 / (p_win * 1.045))), 2)
        return {
            "pick_code": f"{'itb1' if is_home else 'itb2'}_{line:.1f}",
            "label": f"{prefix_lbl} > {line:.1f}",
            "odds": calc_odd,
            "prob": round(p_win * 100, 1)
        }

    if code.startswith("tb_") or code.startswith("tm_"):
        direction = "tb" if code.startswith("tb_") else "tm"
        try:
            line = float(code.split("_")[1])
        except Exception:
            return None

        if line < 0.5 or line > 7.5:
            return None

        goal_probs = [poisson_pmf(k, lam_total) for k in range(15)]
        is_integer_line = abs(line - round(line)) < 1e-5
        int_line = int(round(line))

        if direction == "tb":
            if is_integer_line:
                p_win = sum(goal_probs[k] for k in range(int_line + 1, 15))
                p_push = goal_probs[int_line]
            else:
                min_goals = int(math.floor(line)) + 1
                p_win = sum(goal_probs[k] for k in range(min_goals, 15))
                p_push = 0.0
            label_prefix = "ТБ"
        else:
            if is_integer_line:
                p_win = sum(goal_probs[k] for k in range(0, int_line))
                p_push = goal_probs[int_line]
            else:
                max_goals = int(math.floor(line))
                p_win = sum(goal_probs[k] for k in range(0, max_goals + 1))
                p_push = 0.0
            label_prefix = "ТМ"

        denom = max(0.04, 1.0 - p_push)
        effective_win_prob = max(0.05, min(0.92, p_win / denom))
        margin = 1.045
        calc_odd = round(max(1.08, min(19.0, 1.0 / (effective_win_prob * margin))), 2)

        line_str = f"{int_line}.0" if is_integer_line else f"{line:.1f}"
        refund_note = " (возврат)" if is_integer_line else ""
        return {
            "pick_code": f"{direction}_{line_str}",
            "label": f"{label_prefix} {line_str}{refund_note}",
            "odds": calc_odd,
            "prob": round(effective_win_prob * 100, 1)
        }

    return None

# ================= ПОЛУЧЕНИЕ РЕАЛЬНЫХ МАТЧЕЙ (ESPN API) =================
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

def parse_team_stats_detail(comp_dict: dict, ru_name: str) -> dict:
    base_ppg = 1.45 + get_elite_bonus(ru_name)
    record_str = "н/д"
    games_played = 0
    w, d, l = 0, 0, 0

    if isinstance(comp_dict, dict):
        records = comp_dict.get("records") or []
        for r in records:
            if not isinstance(r, dict):
                continue
            summary = str(r.get("summary") or "")
            parts = summary.split("-")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                w, d, l = int(parts[0]), int(parts[1]), int(parts[2])
                games_played = w + d + l
                record_str = f"{w}В - {d}Н - {l}П"
                if games_played >= 3:
                    ppg = (w * 3 + d) / games_played
                    base_ppg = (ppg * 0.7) + (base_ppg * 0.3)
                break
        form_raw = str(comp_dict.get("form") or "").upper()
    else:
        form_raw = ""

    if form_raw and len(form_raw) >= 3:
        icons = []
        for ch in form_raw[-5:]:
            if ch == "W":
                icons.append("✅В")
            elif ch == "D":
                icons.append("➖Н")
            elif ch == "L":
                icons.append("❌П")
        form_visual = " ".join(icons) if icons else "н/д"
    elif games_played > 0:
        seq = (["✅В"] * min(5, round((w / games_played) * 5)) +
               ["➖Н"] * min(5, round((d / games_played) * 5)) +
               ["❌П"] * 5)[:5]
        form_visual = " ".join(seq)
    else:
        form_visual = "📊 Старт сезона"

    points = w * 3 + d
    return {
        "ppg": base_ppg,
        "record_str": record_str,
        "points": points,
        "games": games_played,
        "form_visual": form_visual
    }

def compute_match_metrics_and_odds(comp_obj: dict, home_comp: dict, away_comp: dict, h_name: str, a_name: str):
    h_stats = parse_team_stats_detail(home_comp, h_name)
    a_stats = parse_team_stats_detail(away_comp, a_name)
    h_strength = h_stats["ppg"] + 0.22
    a_strength = a_stats["ppg"]
    diff = h_strength - a_strength

    lam_h = round(max(0.65, min(2.65, 1.38 + (h_strength - 1.50) * 0.62 - (a_strength - 1.45) * 0.22)), 2)
    lam_a = round(max(0.50, min(2.35, 1.12 + (a_strength - 1.45) * 0.58 - (h_strength - 1.50) * 0.22)), 2)
    exp_goals = round(lam_h + lam_a, 2)

    best_score = "1:1"
    best_p = 0.0
    for gh in range(5):
        for ga in range(5):
            p = poisson_pmf(gh, lam_h) * poisson_pmf(ga, lam_a)
            if p > best_p:
                best_p = p
                best_score = f"{gh}:{ga}"

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

    raw_1, raw_x, raw_2 = 1.0 / p1_odd, 1.0 / x_odd, 1.0 / p2_odd
    m_sum = raw_1 + raw_x + raw_2
    p1_clean, px_clean, p2_clean = raw_1 / m_sum, raw_x / m_sum, raw_2 / m_sum

    margin = 1.045
    odd_1x = round(max(1.08, 1.0 / ((p1_clean + px_clean) * margin)), 2)
    odd_x2 = round(max(1.08, 1.0 / ((p2_clean + px_clean) * margin)), 2)
    odd_f10 = round(max(1.08, 1.0 / ((p1_clean / (p1_clean + p2_clean)) * margin)), 2)
    odd_f20 = round(max(1.08, 1.0 / ((p2_clean / (p1_clean + p2_clean)) * margin)), 2)

    p_btts = max(0.35, min(0.68, (1.0 - math.exp(-lam_h)) * (1.0 - math.exp(-lam_a))))
    odd_btts = round(max(1.40, 1.0 / (p_btts * margin)), 2)
    odd_btts_no = round(max(1.40, 1.0 / ((1.0 - p_btts) * margin)), 2)

    p_tb25 = 1.0 - sum(poisson_pmf(k, exp_goals) for k in range(3))
    p_tb15 = 1.0 - sum(poisson_pmf(k, exp_goals) for k in range(2))
    odd_tb15 = round(max(1.12, 1.0 / (max(0.55, min(0.88, p_tb15)) * margin)), 2)
    odd_tb25 = round(max(1.38, 1.0 / (max(0.35, min(0.72, p_tb25)) * margin)), 2)
    odd_tm25 = round(max(1.38, 1.0 / (max(0.28, min(0.65, 1.0 - p_tb25)) * margin)), 2)

    odds_dict = {
        "p1": p1_odd, "x": x_odd, "p2": p2_odd,
        "1x": odd_1x, "x2": odd_x2,
        "f10": odd_f10, "f20": odd_f20,
        "tb15": odd_tb15, "tb25": odd_tb25, "tm25": odd_tm25,
        "btts": odd_btts, "btts_no": odd_btts_no
    }
    return odds_dict, exp_goals, lam_h, lam_a, best_score, h_stats, a_stats

def calculate_ai_probabilities(odds: dict) -> dict:
    raw_p1, raw_x, raw_p2 = 1 / odds["p1"], 1 / odds["x"], 1 / odds["p2"]
    margin_sum = raw_p1 + raw_x + raw_p2
    p1 = round((raw_p1 / margin_sum) * 100, 1)
    x = round((raw_x / margin_sum) * 100, 1)
    p2 = round((raw_p2 / margin_sum) * 100, 1)
    return {
        "p1": p1, "x": x, "p2": p2,
        "1x": round(p1 + x, 1),
        "x2": round(p2 + x, 1),
        "f10": round((p1 / max(1.0, p1 + p2)) * 100, 1),
        "f20": round((p2 / max(1.0, p1 + p2)) * 100, 1),
        "tb15": round(min(89.0, (1.0 / odds.get("tb15", 1.30)) * 95.5), 1),
        "tb25": round(min(76.0, (1.0 / odds.get("tb25", 1.85)) * 95.5), 1),
        "tm25": round(min(76.0, (1.0 / odds.get("tm25", 1.95)) * 95.5), 1),
        "btts": round(min(75.0, (1.0 / odds.get("btts", 1.75)) * 95.5), 1),
        "btts_no": round(min(75.0, (1.0 / odds.get("btts_no", 1.95)) * 95.5), 1),
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

        venue_obj = comp.get("venue") or {}
        venue_name = venue_obj.get("fullName") or "Центральная арена"
        venue_city = (venue_obj.get("address") or {}).get("city") or ""
        venue_str = f"{venue_name} ({venue_city})" if venue_city else venue_name

        odds, exp_goals, lam_h, lam_a, best_score, h_stats, a_stats = compute_match_metrics_and_odds(
            comp, home_c, away_c, h_name, a_name
        )

        return {
            "event_id": ev_id,
            "league_key": league_key,
            "league_slug": cfg["slug"],
            "teams": f"{h_name} — {a_name}",
            "home_team": h_name,
            "away_team": a_name,
            "venue": venue_str,
            "h_stats": h_stats,
            "a_stats": a_stats,
            "records_info": f"{h_name} ({h_stats['record_str']}), {a_name} ({a_stats['record_str']})",
            "date": dt_msk.strftime("%d.%m.%Y, %H:%M МСК"),
            "short_date": dt_msk.strftime("%d.%m %H:%M"),
            "start_ts": start_ts,
            "end_ts": start_ts + (115 * 60),
            "exp_goals": exp_goals,
            "lam_h": lam_h,
            "lam_a": lam_a,
            "best_score": best_score,
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
                        last_bonus TEXT DEFAULT '',
                        referred_by BIGINT DEFAULT 0,
                        referrals_count INT DEFAULT 0,
                        favorite_club TEXT DEFAULT '',
                        achievements TEXT DEFAULT '[]',
                        streak INT DEFAULT 0,
                        totals_wins INT DEFAULT 0,
                        last_spin TEXT DEFAULT '',
                        active_booster TEXT DEFAULT '',
                        is_incognito INT DEFAULT 0
                    );
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT DEFAULT 0;
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS referrals_count INT DEFAULT 0;
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_club TEXT DEFAULT '';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS achievements TEXT DEFAULT '[]';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS streak INT DEFAULT 0;
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS totals_wins INT DEFAULT 0;
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS last_spin TEXT DEFAULT '';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS active_booster TEXT DEFAULT '';
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS is_incognito INT DEFAULT 0;

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
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS booster_used TEXT DEFAULT '';
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_all_in INT DEFAULT 0;
                    ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_fav_club INT DEFAULT 0;

                    CREATE TABLE IF NOT EXISTS superexpress_entries (
                        entry_id SERIAL PRIMARY KEY,
                        round_key TEXT,
                        user_id BIGINT,
                        picks_json TEXT,
                        status TEXT DEFAULT 'pending',
                        guessed INT DEFAULT 0,
                        payout INT DEFAULT 0,
                        created_at TEXT DEFAULT ''
                    );
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
                        last_bonus TEXT DEFAULT '',
                        referred_by INTEGER DEFAULT 0,
                        referrals_count INTEGER DEFAULT 0,
                        favorite_club TEXT DEFAULT '',
                        achievements TEXT DEFAULT '[]',
                        streak INTEGER DEFAULT 0,
                        totals_wins INTEGER DEFAULT 0,
                        last_spin TEXT DEFAULT '',
                        active_booster TEXT DEFAULT '',
                        is_incognito INTEGER DEFAULT 0
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
                        legs_json TEXT DEFAULT '[]',
                        booster_used TEXT DEFAULT '',
                        is_all_in INTEGER DEFAULT 0,
                        is_fav_club INTEGER DEFAULT 0
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS superexpress_entries (
                        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        round_key TEXT,
                        user_id INTEGER,
                        picks_json TEXT,
                        status TEXT DEFAULT 'pending',
                        guessed INTEGER DEFAULT 0,
                        payout INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT ''
                    )
                """)
                for col_def in [
                    "referred_by INTEGER DEFAULT 0", "referrals_count INTEGER DEFAULT 0",
                    "favorite_club TEXT DEFAULT ''", "achievements TEXT DEFAULT '[]'",
                    "streak INTEGER DEFAULT 0", "totals_wins INTEGER DEFAULT 0",
                    "last_spin TEXT DEFAULT ''", "active_booster TEXT DEFAULT ''",
                    "is_incognito INTEGER DEFAULT 0"
                ]:
                    try:
                        await db.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
                    except Exception:
                        pass
                for col_def in [
                    "bet_type TEXT DEFAULT 'single'", "win_prob REAL DEFAULT 50.0",
                    "settle_ts INTEGER DEFAULT 0", "created_at TEXT DEFAULT ''",
                    "score_result TEXT DEFAULT ''", "legs_json TEXT DEFAULT '[]'",
                    "booster_used TEXT DEFAULT ''", "is_all_in INTEGER DEFAULT 0",
                    "is_fav_club INTEGER DEFAULT 0"
                ]:
                    try:
                        await db.execute(f"ALTER TABLE bets ADD COLUMN {col_def}")
                    except Exception:
                        pass
                await db.commit()
            logging.info("Локальная БД SQLite подключена!")

    async def get_or_create_user(self, user_id: int, username: str = "", referrer_id: int = 0) -> tuple[dict, bool]:
        uname = username or f"Capper_{str(user_id)[-4:]}"
        rewarded = False

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
                if not row:
                    valid_ref = 0
                    if referrer_id and referrer_id != user_id:
                        ref_exists = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", referrer_id)
                        if ref_exists:
                            valid_ref = referrer_id

                    start_bal = 1500.0 if valid_ref else 1000.0
                    await conn.execute(
                        "INSERT INTO users (user_id, username, balance, referred_by) VALUES ($1, $2, $3, $4)",
                        user_id, uname, start_bal, valid_ref
                    )
                    if valid_ref:
                        await conn.execute(
                            "UPDATE users SET balance = balance + 500.0, referrals_count = referrals_count + 1 WHERE user_id = $1",
                            valid_ref
                        )
                        rewarded = True
                    row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
                return dict(row), rewarded
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    valid_ref = 0
                    if referrer_id and referrer_id != user_id:
                        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,)) as c2:
                            if await c2.fetchone():
                                valid_ref = referrer_id

                    start_bal = 1500.0 if valid_ref else 1000.0
                    await db.execute(
                        "INSERT INTO users (user_id, username, balance, referred_by) VALUES (?, ?, ?, ?)",
                        (user_id, uname, start_bal, valid_ref)
                    )
                    if valid_ref:
                        await db.execute(
                            "UPDATE users SET balance = balance + 500.0, referrals_count = referrals_count + 1 WHERE user_id = ?",
                            (valid_ref,)
                        )
                        rewarded = True
                    await db.commit()
                    async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                        row = await cur.fetchone()
                return dict(row), rewarded

    async def get_user(self, user_id: int, username: str = "") -> dict:
        u, _ = await self.get_or_create_user(user_id, username)
        return u

    async def update_nickname(self, user_id: int, new_nick: str):
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE users SET username = $1 WHERE user_id = $2", new_nick, user_id)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (new_nick, user_id))
                await db.commit()

    async def toggle_user_incognito(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        new_val = 0 if int(user.get("is_incognito") or 0) == 1 else 1
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE users SET is_incognito = $1 WHERE user_id = $2", new_val, user_id)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE users SET is_incognito = ? WHERE user_id = ?", (new_val, user_id))
                await db.commit()
        return new_val

    async def unlock_achievement(self, user_id: int, ach_key: str) -> bool:
        if ach_key not in ACHIEVEMENTS_CONFIG:
            return False
        user = await self.get_user(user_id)
        try:
            unlocked = json.loads(user.get("achievements") or "[]")
        except Exception:
            unlocked = []

        if ach_key in unlocked:
            return False

        unlocked.append(ach_key)
        ach_json = json.dumps(unlocked, ensure_ascii=False)
        reward = ACHIEVEMENTS_CONFIG[ach_key]["reward"]
        title = ACHIEVEMENTS_CONFIG[ach_key]["title"]
        desc = ACHIEVEMENTS_CONFIG[ach_key]["desc"]

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET achievements = $1, balance = balance + $2, profit = profit + $2 WHERE user_id = $3",
                    ach_json, float(reward), user_id
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE users SET achievements = ?, balance = balance + ?, profit = profit + ? WHERE user_id = ?",
                    (ach_json, float(reward), float(reward), user_id)
                )
                await db.commit()

        try:
            msg = (
                f"🎖 <b>НОВОЕ ДОСТИЖЕНИЕ РАЗБЛОКИРОВАНО!</b>\n\n"
                f"<blockquote>🏆 <b>{title}</b>\n"
                f"📋 <i>{desc}</i>\n"
                f"💰 Награда: <b><code>+{reward} FC</code></b> зачислена на баланс!</blockquote>"
            )
            await bot.send_message(user_id, msg, parse_mode="HTML")
        except Exception:
            pass
        return True

    async def set_favorite_club(self, user_id: int, club_name: str):
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE users SET favorite_club = $1 WHERE user_id = $2", club_name, user_id)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE users SET favorite_club = ? WHERE user_id = ?", (club_name, user_id))
                await db.commit()

    async def spin_roulette_db(self, user_id: int, coin_win: int, booster_code: str, is_respin: bool) -> dict:
        today_str = "" if is_respin else now_msk().strftime("%Y-%m-%d")
        user = await self.get_user(user_id)
        new_bal = round(user["balance"] + coin_win, 1)
        new_booster = booster_code if booster_code else user.get("active_booster", "")

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET balance = $1, last_spin = $2, active_booster = $3 WHERE user_id = $4",
                    new_bal, today_str, new_booster, user_id
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE users SET balance = ?, last_spin = ?, active_booster = ? WHERE user_id = ?",
                    (new_bal, today_str, new_booster, user_id)
                )
                await db.commit()

        if new_bal >= 10000:
            await self.unlock_achievement(user_id, "bal_10k")
        if new_bal >= 50000:
            await self.unlock_achievement(user_id, "bal_50k")

        return {"new_balance": new_bal, "active_booster": new_booster}

    async def claim_daily_bonus(self, user_id: int) -> tuple[bool, int, str]:
        today_str = now_msk().strftime("%Y-%m-%d")
        user = await self.get_user(user_id)
        rank_name, bonus = get_user_rank_info(user["balance"], user["is_vip"])
        if user["last_bonus"] == today_str:
            return False, 0, rank_name

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

        await self.unlock_achievement(user_id, "first_bonus")
        return True, bonus, rank_name

    async def create_pending_bet(
        self, user_id: int, username: str, match_title: str, pick: str,
        amount: int, odds: float, win_prob: float, settle_ts: int,
        bet_type: str = "single", legs_json: str = "[]"
    ) -> dict:
        user = await self.get_user(user_id, username)
        if amount < 10:
            return {"ok": False, "error": "Минимальная сумма ставки — 10 FC!"}
        if user["balance"] < amount:
            return {"ok": False, "error": f"Недостаточно средств! Твой баланс: {round(user['balance'], 1)} FC."}

        is_all_in = 1 if (user["balance"] - amount < 10.0) else 0
        fav_club = user.get("favorite_club") or ""
        is_fav_club = 1 if (fav_club and (fav_club in match_title or fav_club in pick)) else 0

        active_booster = user.get("active_booster") or ""
        booster_used = ""
        final_odds = odds
        if active_booster == "boost035":
            final_odds = round(odds + 0.35, 2)
            booster_used = "boost035"
        elif active_booster == "insure50":
            booster_used = "insure50"

        new_balance = round(user["balance"] - amount, 1)
        created_str = now_msk().strftime("%d.%m %H:%M")

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET balance = $1, active_booster = '' WHERE user_id = $2",
                    new_balance, user_id
                )
                bet_id = await conn.fetchval("""
                    INSERT INTO bets (
                        user_id, match_title, pick, amount, odds, status, bet_type,
                        win_prob, settle_ts, created_at, legs_json, booster_used, is_all_in, is_fav_club
                    )
                    VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8, $9, $10, $11, $12, $13) RETURNING bet_id
                """, user_id, match_title, pick, amount, final_odds, bet_type, win_prob, settle_ts, created_str, legs_json, booster_used, is_all_in, is_fav_club)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE users SET balance = ?, active_booster = '' WHERE user_id = ?",
                    (new_balance, user_id)
                )
                cur = await db.execute("""
                    INSERT INTO bets (
                        user_id, match_title, pick, amount, odds, status, bet_type,
                        win_prob, settle_ts, created_at, legs_json, booster_used, is_all_in, is_fav_club
                    )
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, match_title, pick, amount, final_odds, bet_type, win_prob, settle_ts, created_str, legs_json, booster_used, is_all_in, is_fav_club))
                bet_id = cur.lastrowid
                await db.commit()

        await self.unlock_achievement(user_id, "first_bet")
        if bet_type == "express":
            await self.unlock_achievement(user_id, "first_express")

        return {
            "ok": True,
            "bet_id": bet_id,
            "final_odds": final_odds,
            "booster_used": booster_used,
            "is_fav_club": is_fav_club,
            "new_balance": new_balance,
            "potential_win": round(amount * final_odds, 1)
        }

    async def update_bet_legs_progress(self, bet_id: int, updated_legs_json: str):
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute("UPDATE bets SET legs_json = $1 WHERE bet_id = $2", updated_legs_json, bet_id)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("UPDATE bets SET legs_json = ? WHERE bet_id = ?", (updated_legs_json, bet_id))
                await db.commit()

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

    async def get_bet_by_id(self, bet_id: int, user_id: int) -> dict | None:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM bets WHERE bet_id = $1 AND user_id = $2", bet_id, user_id)
                return dict(row) if row else None
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM bets WHERE bet_id = ? AND user_id = ?", (bet_id, user_id)) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None

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

    async def settle_bet_in_db(self, bet: dict, outcome_status: str, effective_odds: float, score_str: str, updated_legs_json: str | None = None) -> dict:
        user = await self.get_user(bet["user_id"])
        amount = bet["amount"]
        legs_str = updated_legs_json if updated_legs_json is not None else bet.get("legs_json", "[]")
        booster_used = bet.get("booster_used") or ""
        is_fav_club = int(bet.get("is_fav_club") or 0)
        is_all_in = int(bet.get("is_all_in") or 0)

        cur_streak = int(user.get("streak") or 0)
        cur_totals_wins = int(user.get("totals_wins") or 0)
        fav_bonus = 0.0
        insured_refund = 0.0

        if outcome_status == "win":
            base_payout = round(amount * effective_odds, 1)
            net_profit = round(base_payout - amount, 1)
            if is_fav_club and net_profit > 0:
                fav_bonus = round(net_profit * 0.10, 1)
                net_profit = round(net_profit + fav_bonus, 1)
            payout = round(amount + net_profit, 1)
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc = 1, 0
            new_streak = cur_streak + 1

            try:
                legs_list = json.loads(legs_str)
            except Exception:
                legs_list = []
            has_total_leg = any(
                str(lg.get("pick_code", "")).startswith(("tb", "tm", "itb"))
                for lg in legs_list
            )
            new_totals_wins = cur_totals_wins + (1 if has_total_leg else 0)

        elif outcome_status == "push":
            payout = float(amount)
            net_profit = 0.0
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc = 0, 0
            new_streak = cur_streak
            new_totals_wins = cur_totals_wins

        elif outcome_status == "cashout":
            payout = round(effective_odds, 1)
            net_profit = round(payout - amount, 1)
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc = (1, 0) if net_profit > 0 else (0, 0)
            new_streak = cur_streak
            new_totals_wins = cur_totals_wins

        else:
            if booster_used == "insure50":
                insured_refund = round(amount * 0.5, 1)
                payout = insured_refund
                net_profit = -round(amount - insured_refund, 1)
                new_balance = round(user["balance"] + insured_refund, 1)
            else:
                payout = 0.0
                net_profit = -float(amount)
                new_balance = round(user["balance"], 1)
            w_inc, l_inc = 0, 1
            new_streak = 0
            new_totals_wins = cur_totals_wins

        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE bets SET status = $1, score_result = $2, odds = $3, legs_json = $4 WHERE bet_id = $5",
                    outcome_status, score_str, round(effective_odds, 2) if outcome_status != "cashout" else bet["odds"], legs_str, bet["bet_id"]
                )
                await conn.execute(
                    "UPDATE users SET balance = $1, wins = wins + $2, losses = losses + $3, profit = profit + $4, streak = $5, totals_wins = $6 WHERE user_id = $7",
                    new_balance, w_inc, l_inc, net_profit, new_streak, new_totals_wins, bet["user_id"]
                )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE bets SET status = ?, score_result = ?, odds = ?, legs_json = ? WHERE bet_id = ?",
                    (outcome_status, score_str, round(effective_odds, 2) if outcome_status != "cashout" else bet["odds"], legs_str, bet["bet_id"])
                )
                await db.execute(
                    "UPDATE users SET balance = ?, wins = wins + ?, losses = losses + ?, profit = profit + ?, streak = ?, totals_wins = ? WHERE user_id = ?",
                    (new_balance, w_inc, l_inc, net_profit, new_streak, new_totals_wins, bet["user_id"])
                )
                await db.commit()

        uid = bet["user_id"]
        if outcome_status == "cashout":
            await self.unlock_achievement(uid, "cashout_profit")
        elif outcome_status == "win":
            if bet.get("bet_type") == "single":
                await self.unlock_achievement(uid, "first_win")
                if effective_odds >= 4.0:
                    await self.unlock_achievement(uid, "high_odd_4")
            elif bet.get("bet_type") == "express" and effective_odds >= 10.0:
                await self.unlock_achievement(uid, "express_10")

            if new_streak >= 3:
                await self.unlock_achievement(uid, "streak_3")
            if new_streak >= 7:
                await self.unlock_achievement(uid, "streak_7")
            if new_totals_wins >= 5:
                await self.unlock_achievement(uid, "totals_5")
            if is_all_in:
                await self.unlock_achievement(uid, "all_in_win")

        if new_balance >= 10000:
            await self.unlock_achievement(uid, "bal_10k")
        if new_balance >= 50000:
            await self.unlock_achievement(uid, "bal_50k")

        return {
            "payout": payout,
            "net_profit": net_profit,
            "new_balance": new_balance,
            "fav_bonus": fav_bonus,
            "insured_refund": insured_refund
        }

    # Методы Суперэкспресса тура
    async def get_superexpress_entry(self, user_id: int, round_key: str) -> dict | None:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM superexpress_entries WHERE user_id = $1 AND round_key = $2",
                    user_id, round_key
                )
                return dict(row) if row else None
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM superexpress_entries WHERE user_id = ? AND round_key = ?",
                    (user_id, round_key)
                ) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None

    async def create_superexpress_entry(self, user_id: int, round_key: str, picks_list: list) -> int:
        picks_str = json.dumps(picks_list, ensure_ascii=False)
        created_str = now_msk().strftime("%d.%m %H:%M")
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                entry_id = await conn.fetchval("""
                    INSERT INTO superexpress_entries (round_key, user_id, picks_json, status, created_at)
                    VALUES ($1, $2, $3, 'pending', $4) RETURNING entry_id
                """, round_key, user_id, picks_str, created_str)
                return entry_id
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cur = await db.execute("""
                    INSERT INTO superexpress_entries (round_key, user_id, picks_json, status, created_at)
                    VALUES (?, ?, ?, 'pending', ?)
                """, (round_key, user_id, picks_str, created_str))
                await db.commit()
                return cur.lastrowid

    async def get_pending_superexpress_entries(self) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM superexpress_entries WHERE status = 'pending'")
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM superexpress_entries WHERE status = 'pending'") as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def settle_superexpress_entry(self, entry_id: int, user_id: int, guessed: int, payout: int, updated_picks_json: str):
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE superexpress_entries SET status = 'settled', guessed = $1, payout = $2, picks_json = $3 WHERE entry_id = $4",
                    guessed, payout, updated_picks_json, entry_id
                )
                if payout > 0:
                    await conn.execute(
                        "UPDATE users SET balance = balance + $1, profit = profit + $1 WHERE user_id = $2",
                        float(payout), user_id
                    )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(
                    "UPDATE superexpress_entries SET status = 'settled', guessed = ?, payout = ?, picks_json = ? WHERE entry_id = ?",
                    (guessed, payout, updated_picks_json, entry_id)
                )
                if payout > 0:
                    await db.execute(
                        "UPDATE users SET balance = balance + ?, profit = profit + ? WHERE user_id = ?",
                        (float(payout), float(payout), user_id)
                    )
                await db.commit()

    async def get_leaderboard(self) -> list:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_id, username, balance, wins, losses, is_vip, favorite_club, is_incognito FROM users ORDER BY balance DESC LIMIT 10"
                )
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT user_id, username, balance, wins, losses, is_vip, favorite_club, is_incognito FROM users ORDER BY balance DESC LIMIT 10"
                ) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def get_project_stats(self) -> dict:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                total_u = await conn.fetchval("SELECT COUNT(*) FROM users")
                total_b = await conn.fetchval("SELECT COUNT(*) FROM bets")
                active_b = await conn.fetchval("SELECT COUNT(*) FROM bets WHERE status = 'pending'")
                total_fc = await conn.fetchval("SELECT COALESCE(SUM(balance), 0) FROM users")
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                async with db.execute("SELECT COUNT(*) FROM users") as c:
                    total_u = (await c.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM bets") as c:
                    total_b = (await c.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM bets WHERE status = 'pending'") as c:
                    active_b = (await c.fetchone())[0]
                async with db.execute("SELECT COALESCE(SUM(balance), 0) FROM users") as c:
                    total_fc = (await c.fetchone())[0]
        return {
            "users": total_u,
            "bets": total_b,
            "active_bets": active_b,
            "total_fc": round(float(total_fc), 1)
        }

    async def get_all_user_ids(self) -> list[int]:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id FROM users")
                return [r["user_id"] for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                async with db.execute("SELECT user_id FROM users") as cur:
                    rows = await cur.fetchall()
                    return [r[0] for r in rows]

    async def add_balance_to_user(self, target_uid: int, add_amt: float) -> bool:
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", target_uid)
                if not row:
                    return False
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", add_amt, target_uid)
                return True
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (target_uid,)) as c:
                    if not await c.fetchone():
                        return False
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (add_amt, target_uid))
                await db.commit()
                return True

db_manager = Database()

# ================= СКОРОСТНОЙ МУЛЬТИ-ШЛЮЗ ИИ С КЭШИРОВАНИЕМ =================
async def ask_ai_cached(cache_key: str, prompt: str, system_prompt: str = "Ты элитный футбольный аналитик.") -> str | None:
    now_ts = int(now_msk().timestamp())
    cached = AI_CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"] < 10800):
        return cached["text"]

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

# ================= ПРОВЕРКА РЕЗУЛЬТАТОВ И ПРОМЕЖУТОЧНЫХ НОГ ЭКСПРЕССА =================
def evaluate_leg_result(pick_code: str, home_score: int, away_score: int) -> str:
    code = pick_code.lower()
    total_goals = home_score + away_score

    if code in ("p1", "п1"):
        return "win" if home_score > away_score else "loss"
    elif code in ("x", "х"):
        return "win" if home_score == away_score else "loss"
    elif code in ("p2", "п2"):
        return "win" if away_score > home_score else "loss"
    elif code in ("1x", "1х"):
        return "win" if home_score >= away_score else "loss"
    elif code in ("x2", "х2"):
        return "win" if away_score >= home_score else "loss"
    elif code == "f10":
        if home_score > away_score:
            return "win"
        return "push" if home_score == away_score else "loss"
    elif code == "f20":
        if away_score > home_score:
            return "win"
        return "push" if home_score == away_score else "loss"
    elif code == "btts":
        return "win" if (home_score >= 1 and away_score >= 1) else "loss"
    elif code == "btts_no":
        return "win" if (home_score == 0 or away_score == 0) else "loss"
    elif code == "tb15":
        return "win" if total_goals >= 2 else "loss"
    elif code == "tb25":
        return "win" if total_goals >= 3 else "loss"
    elif code == "tm25":
        return "win" if total_goals <= 2 else "loss"
    elif code.startswith("itb1_") or code.startswith("itb2_"):
        is_home = code.startswith("itb1_")
        try:
            line = float(code.split("_")[1])
        except Exception:
            return "loss"
        team_goals = home_score if is_home else away_score
        return "win" if team_goals > line else "loss"
    elif code.startswith("tb_") or code.startswith("tm_"):
        direction = "tb" if code.startswith("tb_") else "tm"
        try:
            line = float(code.split("_")[1])
        except Exception:
            return "loss"
        if abs(total_goals - line) < 1e-5:
            return "push"
        if direction == "tb":
            return "win" if total_goals > line else "loss"
        else:
            return "win" if total_goals < line else "loss"

    return "win" if home_score > away_score else "loss"

async def calculate_cashout_offer(session: aiohttp.ClientSession, bet: dict) -> float:
    amount = bet["amount"]
    try:
        legs = json.loads(bet.get("legs_json") or "[]")
    except Exception:
        legs = []

    if not legs:
        return round(amount * 0.90, 1)

    multiplier = 1.0
    any_started = False

    for leg in legs:
        res = await fetch_real_match_result(session, leg["league_slug"], str(leg["event_id"]))
        leg_odd = float(leg.get("odds") or bet["odds"])
        if not res["ok"] or res["state"] == "pre":
            multiplier *= 0.94
            continue

        any_started = True
        cur_state = evaluate_leg_result(leg["pick_code"], res["home_score"], res["away_score"])
        if res["completed"]:
            if cur_state == "win":
                multiplier *= leg_odd
            elif cur_state == "push":
                multiplier *= 1.0
            else:
                return 0.0
        else:
            if cur_state == "win":
                multiplier *= (1.0 + (leg_odd - 1.0) * 0.68)
            elif cur_state == "push":
                multiplier *= 0.92
            else:
                multiplier *= 0.35

    if not any_started:
        return round(amount * 0.92, 1)

    offer = round(amount * multiplier, 1)
    max_win = round(amount * bet["odds"] * 0.95, 1)
    return min(offer, max_win)

async def check_and_settle_real_bet(session: aiohttp.ClientSession, bet: dict) -> dict:
    try:
        legs = json.loads(bet.get("legs_json") or "[]")
    except Exception:
        legs = []

    if not legs:
        return {"settled": False, "live_summary": "Ожидание данных матча"}

    all_completed = True
    any_lost = False
    effective_odds = 1.0
    all_pushed = True
    score_parts = []
    live_parts = []
    legs_changed = False

    for leg in legs:
        res = await fetch_real_match_result(session, leg["league_slug"], str(leg["event_id"]))
        if not res["ok"]:
            all_completed = False
            live_parts.append(f"⏳ {leg['teams']} — ожидание")
            continue

        if not res["completed"]:
            all_completed = False
            if res["state"] == "in":
                live_tag = f"{res['score_str']} ({res['detail']})"
                if leg.get("live_score") != live_tag:
                    leg["live_score"] = live_tag
                    legs_changed = True
                live_parts.append(f"🔴 LIVE: {leg['teams']} — {live_tag}")
            else:
                live_parts.append(f"📅 {leg['teams']} — ожидает начала")
        else:
            st = evaluate_leg_result(leg["pick_code"], res["home_score"], res["away_score"])
            if leg.get("final_status") != st or leg.get("final_score") != res["score_str"]:
                leg["final_score"] = res["score_str"]
                leg["final_status"] = st
                leg.pop("live_score", None)
                legs_changed = True

            leg_odd = float(leg.get("odds") or bet["odds"])
            if st == "win":
                effective_odds *= leg_odd
                all_pushed = False
                icon = "✅"
            elif st == "push":
                effective_odds *= 1.0
                icon = "🔄 Возврат"
            else:
                any_lost = True
                all_pushed = False
                icon = "❌"

            if len(legs) == 1:
                score_parts.append(f"{res['score_str']}")
            else:
                score_parts.append(f"{leg['teams']} {res['score_str']} ({icon})")
            live_parts.append(f"🏁 {leg['teams']} — {res['score_str']} {icon}")

    updated_legs_str = json.dumps(legs, ensure_ascii=False)

    if all_completed:
        final_score_str = " | ".join(score_parts)
        if any_lost:
            outcome_status = "loss"
        elif all_pushed:
            outcome_status = "push"
        else:
            outcome_status = "win"

        if len(legs) == 1 and outcome_status == "win":
            effective_odds = float(bet["odds"])

        bet["legs_json"] = updated_legs_str
        bet["score_result"] = final_score_str
        db_res = await db_manager.settle_bet_in_db(bet, outcome_status, effective_odds, final_score_str, updated_legs_str)
        await send_settlement_notification(bet, outcome_status, effective_odds, db_res)
        return {"settled": True, "status": outcome_status, "score_str": final_score_str}

    if legs_changed:
        bet["legs_json"] = updated_legs_str
        await db_manager.update_bet_legs_progress(bet["bet_id"], updated_legs_str)

    return {"settled": False, "live_summary": "\n".join(live_parts)}

async def send_settlement_notification(bet: dict, outcome_status: str, effective_odds: float, res: dict):
    type_label = "⚡ ЭКСПРЕСС" if bet.get("bet_type") == "express" else "⚽ ОРДИНАР"
    events_block = format_bet_legs_multiline(bet, with_result=True)
    fav_note = f"\n⭐ <b>Фан-бонус любимого клуба (+10%):</b> <code>+{res['fav_bonus']} FC</code>" if res.get("fav_bonus", 0) > 0 else ""
    ins_note = f"\n🛡 <b>Сработала Страховка 50%:</b> возвращено <b><code>+{res['insured_refund']} FC</code></b>!" if res.get("insured_refund", 0) > 0 else ""

    if outcome_status == "win":
        msg = (
            f"🎉 <b>СТАВКА СЫГРАЛА! ({type_label})</b>\n"
            f"🎫 <b>Купон #{bet['bet_id']}</b>  •  Итоговый кэф: <b><code>{round(effective_odds, 2)}</code></b>\n\n"
            f"<blockquote>{events_block}</blockquote>\n"
            f"💵 <b>Сумма ставки:</b> <code>{bet['amount']} FC</code>{fav_note}\n"
            f"💰 <b>Выплата:</b> <b><code>+{res['payout']} FC</code></b> <i>(чистыми: +{res['net_profit']} FC)</i>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )
    elif outcome_status == "push":
        msg = (
            f"🔄 <b>ВОЗВРАТ СТАВКИ (РАСХОД • КЭФ 1.00)</b>\n"
            f"🎫 <b>Купон #{bet['bet_id']}</b>\n\n"
            f"<blockquote>{events_block}</blockquote>\n"
            f"💵 <b>Возвращено на счет:</b> <b><code>+{res['payout']} FC</code></b>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )
    else:
        msg = (
            f"📢 <b>КУПОН РАССЧИТАН ({type_label}) — ❌ НЕ СЫГРАЛ</b>\n"
            f"🎫 <b>Купон #{bet['bet_id']}</b>  •  Кэф: <code>{bet['odds']}</code>\n\n"
            f"<blockquote>{events_block}</blockquote>\n"
            f"💸 <b>Потеряно:</b> <code>{res['net_profit']} FC</code>{ins_note}\n"
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

async def check_and_settle_superexpress_entry(session: aiohttp.ClientSession, entry: dict):
    try:
        picks = json.loads(entry.get("picks_json") or "[]")
    except Exception:
        return

    if not picks:
        return

    all_completed = True
    guessed = 0
    lines = []

    for idx, item in enumerate(picks, 1):
        res = await fetch_real_match_result(session, item["league_slug"], str(item["event_id"]))
        if not res["ok"] or not res["completed"]:
            all_completed = False
            break
        st = evaluate_leg_result(item["pick_code"], res["home_score"], res["away_score"])
        item["final_score"] = res["score_str"]
        item["won"] = (st == "win")
        if st == "win":
            guessed += 1
        icon = "✅" if st == "win" else "❌"
        lines.append(f"<b>{idx}. {item['teams']}</b> — <code>{item['pick_label']}</code> (Счет: <b>{res['score_str']}</b>) {icon}")

    if not all_completed:
        return

    if guessed == 6:
        payout = 10000
        prize_title = "🏆 СУПЕРДЖЕКПОТ (6 из 6 угадано)!"
    elif guessed == 5:
        payout = 2500
        prize_title = "🥈 СЕРЕБРЯНЫЙ ФОНД (5 из 6 угадано)!"
    elif guessed == 4:
        payout = 500
        prize_title = "🥉 ПРИЗОВОЙ ФОНД (4 из 6 угадано)!"
    else:
        payout = 0
        prize_title = f"📊 Угадано {guessed} из 6 исходов"

    updated_json = json.dumps(picks, ensure_ascii=False)
    await db_manager.settle_superexpress_entry(entry["entry_id"], entry["user_id"], guessed, payout, updated_json)

    try:
        msg = (
            f"🏆 <b>ИТОГИ СУПЕРЭКСПРЕССА ТУРА</b>\n"
            f"<b>{prize_title}</b>\n\n"
            f"<blockquote>" + "\n".join(lines) + "</blockquote>\n"
            f"💰 <b>Твой выигрыш:</b> <b><code>+{payout} FC</code></b>"
        )
        await bot.send_message(entry["user_id"], msg, parse_mode="HTML")
    except Exception:
        pass

async def match_settlement_worker():
    while True:
        try:
            pending_bets = await db_manager.get_all_pending_bets()
            pending_se = await db_manager.get_pending_superexpress_entries()
            if pending_bets or pending_se:
                async with aiohttp.ClientSession() as session:
                    for b in pending_bets:
                        await check_and_settle_real_bet(session, b)
                    for se in pending_se:
                        await check_and_settle_superexpress_entry(session, se)
        except Exception as e:
            logging.error(f"Ошибка фонового расчета реальных матчей: {e}")
        await asyncio.sleep(180)

# ================= АНАЛИТИКА, ЭКСПРЕСС ДНЯ И СУПЕРЭКСПРЕСС =================
def get_top_6_upcoming_matches(db: dict) -> list:
    all_upcoming = []
    for l_val in db.values():
        for m in l_val.get("matches", {}).values():
            all_upcoming.append(m)
    all_upcoming.sort(key=lambda x: x["start_ts"])
    return all_upcoming[:6]

def build_daily_express_data(db: dict) -> dict | None:
    selected = get_top_6_upcoming_matches(db)
    if not selected:
        return None

    picks_text = []
    multiline_pick = []
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

        if probs["p1"] >= 58:
            pick_code, bet_str, k, p = "p1", f"П1 ({t1})", o["p1"], probs["p1"]
        elif probs["p2"] >= 54:
            pick_code, bet_str, k, p = "p2", f"П2 ({t2})", o["p2"], probs["p2"]
        elif o["tb25"] <= 1.76 and idx % 2 == 0:
            pick_code, bet_str, k, p = "tb_2.5", "ТБ 2.5", o["tb25"], probs["tb25"]
        elif abs(probs["p1"] - probs["p2"]) <= 11:
            pick_code, bet_str, k, p = "btts", "Обе забьют: Да", o["btts"], probs["btts"]
        else:
            pick_code, bet_str, k, p = "tb_1.5", "ТБ 1.5", o["tb15"], probs["tb15"]

        total_odd *= k
        combined_prob *= (p / 100.0)
        picks_text.append(
            f"<b>{len(picks_text)+1}. {m['teams']}</b> <i>({m['short_date']})</i>\n"
            f"   🎯 Прогноз: <code>{bet_str}</code> • Кэф: <b><code>{k}</code></b>"
        )
        multiline_pick.append(f"{idx+1}. {m['teams']} — {bet_str} ({k})")
        legs.append({
            "league_slug": m["league_slug"],
            "event_id": m["event_id"],
            "teams": m["teams"],
            "pick_code": pick_code,
            "pick_label": bet_str,
            "odds": k
        })

    final_odd = round(total_odd, 2)
    return {
        "text": "\n\n".join(picks_text) + f"\n\n<blockquote>📈 <b>Итоговый коэффициент:</b> <code>{final_odd}</code></blockquote>",
        "total_odd": final_odd,
        "prob": round(combined_prob * 100, 1),
        "end_ts": max_end_ts,
        "summary_title": f"Экспресс дня ({len(legs)} матчей)",
        "summary_pick": "\n".join(multiline_pick),
        "legs": legs
    }

def smart_local_match_analysis(match: dict, probs: dict) -> str:
    t1, t2 = match["home_team"], match["away_team"]
    odds = match["odds"]
    p1, x, p2 = probs["p1"], probs["x"], probs["p2"]

    if p1 >= 60:
        style = f"⚔️ <b>Расклад:</b> {t1} имеет весомый перевес домашнего поля и класса ({p1}%)."
        bet = f"🎯 <b>Выбор ИИ:</b> П1 ({t1}) за <code>{odds['p1']}</code> или ТБ 1.5 за <code>{odds['tb15']}</code>"
    elif p2 >= 53:
        style = f"⚔️ <b>Расклад:</b> {t2} сильнее в переходных фазах и реализации моментов ({p2}% против {p1}%)."
        bet = f"🎯 <b>Выбор ИИ:</b> П2 ({t2}) за <code>{odds['p2']}</code> или Фора 2 (0) за <code>{odds['f20']}</code>"
    elif odds["tb25"] <= 1.78:
        style = f"⚔️ <b>Расклад:</b> Встреча двух атакующих команд с высоким потенциалом xG ({match['exp_goals']})."
        bet = f"🎯 <b>Выбор ИИ:</b> ТБ 2.5 за <code>{odds['tb25']}</code> или Обе забьют за <code>{odds['btts']}</code>"
    elif abs(p1 - p2) <= 12:
        style = f"⚔️ <b>Расклад:</b> Плотное противостояние ({p1}% на {p2}%). Высока вероятность обмена голами."
        bet = f"🎯 <b>Выбор ИИ:</b> Обе забьют за <code>{odds['btts']}</code> или ТБ 2.0 (с возвратом)"
    else:
        style = f"⚔️ <b>Расклад:</b> Инициатива у {t1} ({p1}%), но {t2} опасен на стандартах и контратаках."
        bet = f"🎯 <b>Выбор ИИ:</b> Фора 1 (0) за <code>{odds['f10']}</code> или ТБ 1.5 за <code>{odds['tb15']}</code>"
    return f"{style}\n\n{bet}"

# ================= МОБИЛЬНЫЕ КЛАВИАТУРЫ (ОПТИМИЗИРОВАННЫЕ ПОД СМАРТФОН) =================
def main_menu_kb(user_id: int = 0):
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Личный кабинет", callback_data="profile")
    builder.button(text="🏆 Лига Чемпионов", callback_data="league:ucl")
    builder.button(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ", callback_data="league:epl")
    builder.button(text="🇪🇸 Ла Лига", callback_data="league:laliga")
    builder.button(text="🇮🇹 Серия А", callback_data="league:seriea")
    builder.button(text="🇩🇪 Бундеслига", callback_data="league:bundesliga")
    builder.button(text="🇫🇷 Лига 1", callback_data="league:ligue1")
    builder.button(text="🌐 Другие чемпионаты (7 лиг)", callback_data="other_leagues")
    builder.button(text="⚡ Экспресс дня", callback_data="express_day")
    builder.button(text="🎯 Суперэкспресс", callback_data="superexpress_menu")
    builder.button(text="🏆 Топ-10 капперов", callback_data="leaderboard")

    if slip_count > 0:
        builder.button(text=f"🧺 Мой купон экспресса ({slip_count})", callback_data="view_slip")
        builder.adjust(1, 2, 2, 2, 1, 2, 1, 1)
    else:
        builder.adjust(1, 2, 2, 2, 1, 2, 1)
    return builder.as_markup()

def other_leagues_kb(db: dict):
    builder = InlineKeyboardBuilder()
    for l_key, cfg in OTHER_LEAGUES.items():
        cnt = len(db.get(l_key, {}).get("matches", {}))
        badge = f" ({cnt})" if cnt > 0 else ""
        builder.button(text=f"{cfg['title']}{badge}", callback_data=f"league:{l_key}")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()

def profile_kb(active_count: int = 0, bonus_amt: int = 250, ach_count: int = 0, fav_club: str = ""):
    club_btn = f"⭐ {fav_club}" if fav_club else "⭐ Мой клуб"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⏳ Активные ({active_count})", callback_data="active_bets")
    builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
    builder.button(text="🎰 Рулетка удачи", callback_data="roulette_menu")
    builder.button(text=f"🎁 Бонус (+{bonus_amt})", callback_data="claim_bonus")
    builder.button(text=f"🎖 Трофеи ({ach_count}/15)", callback_data="achievements_menu")
    builder.button(text=club_btn, callback_data="fav_club_menu")
    builder.button(text="✏️ Никнейм", callback_data="nick_menu")
    builder.button(text="🤝 Друзья (+500)", callback_data="referral_menu")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

def matches_kb(league_key: str, matches_dict: dict):
    builder = InlineKeyboardBuilder()
    for match_id, data in list(matches_dict.items())[:15]:
        builder.button(
            text=f"{data['teams']} • {data['short_date']}",
            callback_data=f"match:{league_key}:{match_id}"
        )
    builder.button(text="🔄 Обновить", callback_data=f"refresh_league:{league_key}")
    if league_key in OTHER_LEAGUES:
        builder.button(text="⬅️ Другие лиги", callback_data="other_leagues")
    else:
        builder.button(text="🏠 В меню", callback_data="back_to_main")
    builder.adjust(*([1] * min(15, len(matches_dict))), 2)
    return builder.as_markup()

def match_outcomes_kb(league_key: str, match_id: str, odds: dict, user_id: int):
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()
    builder.button(text=f"П1 ({odds['p1']})", callback_data=f"pick:{league_key}:{match_id}:p1")
    builder.button(text=f"Х ({odds['x']})", callback_data=f"pick:{league_key}:{match_id}:x")
    builder.button(text=f"П2 ({odds['p2']})", callback_data=f"pick:{league_key}:{match_id}:p2")
    builder.button(text="📈 Тотал Б (ТБ)", callback_data=f"totals_menu:{league_key}:{match_id}:tb")
    builder.button(text="📉 Тотал М (ТМ)", callback_data=f"totals_menu:{league_key}:{match_id}:tm")
    builder.button(text="📊 Сводка и ИТБ", callback_data=f"stats_menu:{league_key}:{match_id}")
    builder.button(text="🛡️ Форы / 1Х2 / ОЗ", callback_data=f"extras_menu:{league_key}:{match_id}")

    if slip_count > 0:
        builder.button(text=f"🧺 Купон экспресса ({slip_count})", callback_data="view_slip")

    builder.button(text="⬅️ К матчам", callback_data=f"league:{league_key}")
    builder.button(text="🏠 Меню", callback_data="back_to_main")

    if slip_count > 0:
        builder.adjust(3, 2, 2, 1, 2)
    else:
        builder.adjust(3, 2, 2, 2)
    return builder.as_markup()

def stats_and_itb_kb(match: dict):
    league_key = match["league_key"]
    match_id = match["event_id"]
    builder = InlineKeyboardBuilder()

    for line_val in ["0.5", "1.5", "2.5"]:
        m1 = evaluate_custom_market(match, f"itb1_{line_val}")
        m2 = evaluate_custom_market(match, f"itb2_{line_val}")
        if m1 and m2:
            builder.button(text=f"🏠 ИТБ1>{line_val} ({m1['odds']})", callback_data=f"pick:{league_key}:{match_id}:itb1_{line_val}")
            builder.button(text=f"✈️ ИТБ2>{line_val} ({m2['odds']})", callback_data=f"pick:{league_key}:{match_id}:itb2_{line_val}")

    builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{league_key}:{match_id}")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()

def totals_constructor_kb(match: dict, direction: str):
    league_key = match["league_key"]
    match_id = match["event_id"]
    prefix = "ТБ" if direction == "tb" else "ТМ"
    builder = InlineKeyboardBuilder()

    for line_val in ["1.0", "1.5", "2.0", "2.5", "3.0", "3.5", "4.0", "4.5"]:
        code = f"{direction}_{line_val}"
        mkt = evaluate_custom_market(match, code)
        if mkt:
            builder.button(
                text=f"{prefix} {line_val} ({mkt['odds']})",
                callback_data=f"pick:{league_key}:{match_id}:{code}"
            )

    builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{league_key}:{match_id}")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

def extras_menu_kb(match: dict):
    league_key = match["league_key"]
    match_id = match["event_id"]
    o = match["odds"]
    builder = InlineKeyboardBuilder()

    builder.button(text=f"1Х ({o['1x']})", callback_data=f"pick:{league_key}:{match_id}:1x")
    builder.button(text=f"Х2 ({o['x2']})", callback_data=f"pick:{league_key}:{match_id}:x2")
    builder.button(text=f"Фора 1(0) • {o['f10']}", callback_data=f"pick:{league_key}:{match_id}:f10")
    builder.button(text=f"Фора 2(0) • {o['f20']}", callback_data=f"pick:{league_key}:{match_id}:f20")
    builder.button(text=f"ОЗ: Да ({o['btts']})", callback_data=f"pick:{league_key}:{match_id}:btts")
    builder.button(text=f"ОЗ: Нет ({o['btts_no']})", callback_data=f"pick:{league_key}:{match_id}:btts_no")
    builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{league_key}:{match_id}")
    builder.adjust(2, 2, 2, 1)
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
        l_key, m_id, p_code = target_code.split("-", 2)
        builder.button(text="➕ В мой Экспресс", callback_data=f"slipadd:{l_key}:{m_id}:{p_code}")
        builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{l_key}:{m_id}")
        builder.adjust(2, 2, 1, 1, 2)

    return builder.as_markup()

# ================= СТАРТ И НАВИГАЦИЯ =================
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    ref_id = 0
    if command.args and command.args.startswith("ref_"):
        raw_ref = command.args.replace("ref_", "").strip()
        if raw_ref.isdigit():
            ref_id = int(raw_ref)

    user, rewarded = await db_manager.get_or_create_user(message.from_user.id, message.from_user.username, ref_id)
    if rewarded and ref_id:
        ref_user = await db_manager.get_user(ref_id)
        ref_cnt = int(ref_user.get("referrals_count") or 0)
        if ref_cnt >= 1:
            await db_manager.unlock_achievement(ref_id, "ref_1")
        if ref_cnt >= 5:
            await db_manager.unlock_achievement(ref_id, "ref_5")
        try:
            await bot.send_message(
                ref_id,
                f"🎉 <b>НОВЫЙ РЕФЕРАЛ!</b>\n\n"
                f"Игрок <b>{user['username']}</b> присоединился по твоей ссылке!\n"
                f"💰 На твой баланс начислено <b><code>+500 FC</code></b>!",
                parse_mode="HTML"
            )
        except Exception:
            pass

    rank_name, _ = get_user_rank_info(user["balance"], user["is_vip"])
    bonus_note = "\n🎁 <i>Начислено +500 FC по приглашению друга!</i>\n" if rewarded else ""
    text = (
        f"⚽ <b>AI_BET_BOT • ФУТБОЛЬНАЯ ЛИНИЯ</b>\n\n"
        f"<blockquote>👤 Каппер: <b>{user['username']}</b>\n"
        f"🏅 Ранг: <b>{rank_name}</b>\n"
        f"💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>  •  🏆 Побед: <b><code>{user['wins']}</code></b></blockquote>"
        f"{bonus_note}"
        f"👇 <b>Выбери турнир или открой Личный кабинет:</b>"
    )
    await message.answer(text, reply_markup=main_menu_kb(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_main")
async def process_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    rank_name, _ = get_user_rank_info(user["balance"], user["is_vip"])
    text = (
        f"⚽ <b>ГЛАВНОЕ МЕНЮ • AI_BET_BOT</b>\n\n"
        f"<blockquote>🏅 <b>{rank_name}</b>\n"
        f"💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>  •  🏆 Побед: <b><code>{user['wins']}</code></b></blockquote>\n"
        f"👇 <b>Выбери турнир или игровой режим:</b>"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb(callback.from_user.id), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "other_leagues")
async def process_other_leagues(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    db = await get_real_matches()
    text = (
        "🌐 <b>ДРУГИЕ ЧЕМПИОНАТЫ И ЕВРОКУБКИ</b>\n\n"
        "<blockquote>В скобках указано количество доступных матчей в расписании.</blockquote>\n"
        "👇 <b>Выбери турнир:</b>"
    )
    await callback.message.edit_text(text, reply_markup=other_leagues_kb(db), parse_mode="HTML")
    await callback.answer()

# ================= ЛИЧНЫЙ КАБИНЕТ, СМЕНА НИКА И АНИМИРОВАННАЯ РУЛЕТКА =================
@dp.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    active_bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    total_settled = user["wins"] + user["losses"]
    winrate = round((user["wins"] / total_settled) * 100, 1) if total_settled > 0 else 0.0
    rank_name, bonus_amt = get_user_rank_info(user["balance"], user["is_vip"])
    profit_sign = "+" if user["profit"] >= 0 else ""

    try:
        unlocked = json.loads(user.get("achievements") or "[]")
    except Exception:
        unlocked = []

    streak = int(user.get("streak") or 0)
    if streak < 3:
        streak_target = f" <i>(до «Хет-трика»: {3 - streak})</i>"
    elif streak < 7:
        streak_target = f" <i>(до «Снайпера»: {7 - streak})</i>"
    else:
        streak_target = " 🔥 <i>Мастер серии!</i>"

    fav_club = user.get("favorite_club") or ""
    club_line = f"⭐ Клуб: <b>{fav_club}</b> <i>(+10% к выплатам)</i>\n" if fav_club else ""
    booster_code = user.get("active_booster") or ""
    booster_line = f"\n🚀 <b>Активный бустер:</b> {BOOSTER_NAMES.get(booster_code, booster_code)}\n" if booster_code else ""

    text = (
        f"👤 <b>КАБИНЕТ КАППЕРА</b>\n\n"
        f"<blockquote>🆔 <b>{user['username']}</b> (<code>{user['user_id']}</code>)\n"
        f"🏅 Ранг: <b>{rank_name}</b>\n"
        f"{club_line}"
        f"💰 Свободный банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"🔥 Серия побед: <b><code>{streak} подряд</code></b>{streak_target}\n"
        f"⏳ Купонов в игре: <b><code>{len(active_bets)}</code></b></blockquote>"
        f"{booster_line}"
        f"📊 <b>Эффективность:</b>\n"
        f"• Ставок: <code>{total_settled}</code> (✅ <code>{user['wins']}</code> | ❌ <code>{user['losses']}</code>)\n"
        f"• Винрейт: <b><code>{winrate}%</code></b>  |  ROI: <b><code>{profit_sign}{round(user['profit'], 1)} FC</code></b>\n"
        f"• Трофеи: <b><code>{len(unlocked)}/15</code></b>  |  Друзья: <b><code>{user.get('referrals_count', 0)}</code></b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=profile_kb(len(active_bets), bonus_amt, len(unlocked), fav_club),
        parse_mode="HTML"
    )
    await callback.answer()

def nick_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Случайный ник", callback_data="nick_random")
    builder.button(text="🔄 Сбросить к Telegram", callback_data="nick_reset")
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    builder.adjust(2, 1)
    return builder.as_markup()

@dp.callback_query(F.data == "nick_menu")
async def process_nick_menu(callback: CallbackQuery, state: FSMContext):
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    await state.set_state(BetStates.waiting_for_nickname)
    text = (
        f"✏️ <b>НАСТРОЙКА ПСЕВДОНИМА</b>\n\n"
        f"<blockquote>👤 Текущий никнейм: <b>{user['username']}</b></blockquote>\n"
        f"• Напиши в чат любой свой псевдоним (от 3 до 16 символов: буквы, цифры, пробел или <code>_</code>).\n"
        f"• Или используй генератор футбольных ников кнопкой ниже:"
    )
    await callback.message.edit_text(text, reply_markup=nick_menu_kb(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "nick_random")
async def process_nick_random(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BetStates.waiting_for_nickname)
    new_nick = generate_football_nickname()
    await db_manager.update_nickname(callback.from_user.id, new_nick)
    text = (
        f"✏️ <b>НАСТРОЙКА ПСЕВДОНИМА</b>\n\n"
        f"<blockquote>🎲 Новый псевдоним: <b>{new_nick}</b></blockquote>\n"
        f"• Нажми «🎲 Случайный ник» еще раз для другого варианта, напиши свой в чат или вернись в кабинет:"
    )
    await callback.message.edit_text(text, reply_markup=nick_menu_kb(), parse_mode="HTML")
    await callback.answer(f"🎲 Установлен ник: {new_nick}")

@dp.callback_query(F.data == "nick_reset")
async def process_nick_reset(callback: CallbackQuery, state: FSMContext):
    default_nick = callback.from_user.username or callback.from_user.first_name or f"Capper_{str(callback.from_user.id)[-4:]}"
    default_nick = re.sub(r"[<>&]", "", default_nick)[:16]
    await db_manager.update_nickname(callback.from_user.id, default_nick)
    await callback.answer(f"🔄 Возвращено имя: {default_nick}", show_alert=True)
    await process_profile(callback, state)

@dp.message(BetStates.waiting_for_nickname)
async def process_custom_nickname_input(message: Message, state: FSMContext):
    raw_text = message.text or ""
    ok, result_or_err = validate_custom_nickname(raw_text)
    if not ok:
        await message.answer(f"⚠️ {result_or_err}\nПопробуй ввести другое имя:", reply_markup=nick_menu_kb(), parse_mode="HTML")
        return

    await db_manager.update_nickname(message.from_user.id, result_or_err)
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Вернуться в кабинет", callback_data="profile")
    await message.answer(
        f"✅ Твой псевдоним успешно изменен на <b>{result_or_err}</b>!",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "roulette_menu")
async def process_roulette_menu(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    today_str = now_msk().strftime("%Y-%m-%d")
    can_spin = user.get("last_spin") != today_str
    booster_code = user.get("active_booster") or ""
    booster_info = f"\n🚀 <b>Активен бустер:</b> {BOOSTER_NAMES.get(booster_code, '')}\n" if booster_code else ""

    text = (
        f"🎰 <b>ФУТБОЛЬНАЯ РУЛЕТКА УДАЧИ</b>\n\n"
        f"<blockquote>Бесплатное вращение доступно <b>1 раз в сутки</b>!\n"
        f"Выбивай монеты FC, страховку ставки или буст коэффициента.</blockquote>"
        f"{booster_info}\n"
        f"🎁 <b>Сектора на барабане:</b>\n"
        f"• 💰 Монеты: <code>+150</code>, <code>+300</code>, <code>+750</code>, <code>+2 000 FC</code>\n"
        f"• 🛡 <b>Страховка 50%</b> — возврат половины ставки при проигрыше\n"
        f"• ⚡ <b>Кэф-буст +0.35</b> — прибавка к кэфу следующего купона\n"
        f"• 🎟 <b>Золотой билет</b> — +100 FC и повторное вращение!"
    )
    builder = InlineKeyboardBuilder()
    if can_spin:
        builder.button(text="🎲 Крутить барабан (Бесплатно)", callback_data="spin_roulette")
    else:
        builder.button(text="⏳ Доступно завтра (Уже прокручено)", callback_data="spin_cooldown")
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "spin_cooldown")
async def process_spin_cooldown(callback: CallbackQuery):
    await callback.answer("⏳ Ты уже крутил рулетку сегодня! Новое вращение откроется завтра.", show_alert=True)

@dp.callback_query(F.data == "spin_roulette")
async def process_spin_roulette(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    today_str = now_msk().strftime("%Y-%m-%d")
    if user.get("last_spin") == today_str:
        await callback.answer("⏳ Ты уже крутил рулетку сегодня!", show_alert=True)
        return

    await callback.answer("🎰 Барабан запущен!")

    sectors = [
        {"name": "💰 +150 FC", "coins": 150, "booster": "", "respin": False, "weight": 28},
        {"name": "💰 +300 FC", "coins": 300, "booster": "", "respin": False, "weight": 22},
        {"name": "🛡 Бустер: Страховка 50%", "coins": 0, "booster": "insure50", "respin": False, "weight": 15},
        {"name": "⚡ Бустер: Кэф-буст +0.35", "coins": 0, "booster": "boost035", "respin": False, "weight": 15},
        {"name": "🎟 Золотой билет (+100 FC + Спин!)", "coins": 100, "booster": "", "respin": True, "weight": 10},
        {"name": "💎 Крупный куш: +750 FC!", "coins": 750, "booster": "", "respin": False, "weight": 7},
        {"name": "🔥 ДЖЕКПОТ: +2 000 FC!", "coins": 2000, "booster": "", "respin": False, "weight": 3},
    ]
    chosen = random.choices(sectors, weights=[s["weight"] for s in sectors], k=1)[0]

    anim_frames = [
        "🎰 <b>БАРАБАН НАБИРАЕТ СКОРОСТЬ...</b>\n\n<blockquote><code>[ 💰 +150 FC ] ➔ [ ⚡ Кэф-буст ] ➔ [ 💎 +750 FC ]</code></blockquote>\n<i>Крутим колесо фортуны...</i>",
        "🎰 <b>БАРАБАН ЗАМЕДЛЯЕТСЯ...</b>\n\n<blockquote><code>[ 🛡 Страховка ] ➔ [ 🔥 ДЖЕКПОТ ] ➔ [ 🎟 Билет ]</code></blockquote>\n<i>Стрелка почти остановилась...</i>"
    ]
    for frame_txt in anim_frames:
        try:
            await callback.message.edit_text(frame_txt, parse_mode="HTML")
            await asyncio.sleep(0.65)
        except Exception:
            pass

    res = await db_manager.spin_roulette_db(
        callback.from_user.id, chosen["coins"], chosen["booster"], chosen["respin"]
    )

    text = (
        f"🎉 <b>РУЛЕТКА ОСТАНОВИЛАСЬ!</b>\n\n"
        f"<blockquote>▶️ <b>[ {chosen['name']} ]</b> ◀️</blockquote>\n"
        f"🏦 <b>Твой текущий банк:</b> <b><code>{res['new_balance']} FC</code></b>"
    )
    builder = InlineKeyboardBuilder()
    if chosen["respin"]:
        builder.button(text="🎟 Крутить еще раз (Золотой билет!)", callback_data="spin_roulette")
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "achievements_menu")
async def process_achievements_menu(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    try:
        unlocked = json.loads(user.get("achievements") or "[]")
    except Exception:
        unlocked = []

    lines = []
    total_bonus_earned = 0
    for key, cfg in ACHIEVEMENTS_CONFIG.items():
        if key in unlocked:
            status_icon = "✅"
            total_bonus_earned += cfg["reward"]
        else:
            status_icon = "🔒"
        lines.append(
            f"{status_icon} <b>{cfg['title']}</b> (<code>+{cfg['reward']} FC</code>)\n"
            f"   <i>{cfg['desc']}</i>"
        )

    text = (
        f"🎖 <b>ЗАЛ СЛАВЫ ({len(unlocked)}/{len(ACHIEVEMENTS_CONFIG)})</b>\n"
        f"💰 Заработано на трофеях: <b><code>+{total_bonus_earned} FC</code></b>\n\n"
        f"<blockquote>" + "\n\n".join(lines) + "</blockquote>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "fav_club_menu")
async def process_fav_club_menu(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    cur_club = user.get("favorite_club") or "Не выбран"

    text = (
        f"⭐ <b>ВЫБОР ЛЮБИМОГО КЛУБА</b>\n\n"
        f"<blockquote>Текущий клуб: <b>{cur_club}</b>\n"
        f"Любая победная ставка на матч любимого клуба приносит <b>+10% к чистой прибыли</b>!</blockquote>\n"
        f"👇 Выбери свой клуб:"
    )
    builder = InlineKeyboardBuilder()
    for idx, club in enumerate(POPULAR_CLUBS):
        mark = "⭐ " if club == cur_club else ""
        builder.button(text=f"{mark}{club}", callback_data=f"set_club:{idx}")
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("set_club:"))
async def process_set_club(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    if 0 <= idx < len(POPULAR_CLUBS):
        club = POPULAR_CLUBS[idx]
        await db_manager.set_favorite_club(callback.from_user.id, club)
        await callback.answer(f"⭐ Любимый клуб: {club}! (+10% к выплатам)", show_alert=True)
    await process_profile(callback, state)

# ================= ТОТАЛИЗАТОР «СУПЕРЭКСПРЕСС ТУРА» =================
@dp.callback_query(F.data == "superexpress_menu")
async def process_superexpress_menu(callback: CallbackQuery):
    db = await get_real_matches()
    top6 = get_top_6_upcoming_matches(db)
    builder = InlineKeyboardBuilder()

    if len(top6) < 6:
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        await callback.message.edit_text(
            "🎯 <b>СУПЕРЭКСПРЕСС ТУРА</b>\n\nВ линии сейчас недостаточно матчей для формирования тиража из 6 игр.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        return

    round_key = "_".join(m["event_id"] for m in top6)
    existing = await db_manager.get_superexpress_entry(callback.from_user.id, round_key)

    if existing:
        picks = json.loads(existing["picks_json"])
        lines = []
        for i, p in enumerate(picks, 1):
            lines.append(f"<b>{i}. {p['teams']}</b>\n   🎯 Выбор: <code>{p['pick_label']}</code>")
        status_txt = "⏳ В игре (ожидает завершения 6 матчей)" if existing["status"] == "pending" else f"🏁 Завершен (Угадано: {existing['guessed']}/6, Выплата: +{existing['payout']} FC)"
        text = (
            f"🎯 <b>СУПЕРЭКСПРЕСС — КУПОН В ИГРЕ</b>\n\n"
            f"<blockquote>" + "\n".join(lines) + "</blockquote>\n"
            f"📡 <b>Статус:</b> {status_txt}\n\n"
            f"🏆 <b>Призовой фонд:</b>\n"
            f"• 4 из 6 — <code>+500 FC</code> | 5 из 6 — <code>+2 500 FC</code> | 6 из 6 — <b><code>+10 000 FC</code></b>"
        )
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await callback.answer()
        return

    uid = callback.from_user.id
    draft = SUPEREXPRESS_DRAFTS.get(uid, {})
    lines = []
    for idx, m in enumerate(top6):
        cur_pick = draft.get(idx, "")
        lbl = {"p1": "П1", "x": "Х", "p2": "П2"}.get(cur_pick, "—")
        lines.append(f"<b>{idx+1}. {m['teams']}</b> <i>({m['short_date']})</i> • Выбор: <b><code>{lbl}</code></b>")
        for code, btn_txt in [("p1", "П1"), ("x", "Х"), ("p2", "П2")]:
            mark = "✅ " if cur_pick == code else ""
            builder.button(text=f"{mark}#{idx+1} {btn_txt}", callback_data=f"se_pick:{idx}:{code}")

    if len(draft) == 6:
        builder.button(text="🔥 Подтвердить Суперэкспресс (Бесплатно)", callback_data="se_submit")

    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    if len(draft) == 6:
        builder.adjust(3, 3, 3, 3, 3, 3, 1, 1)
    else:
        builder.adjust(3, 3, 3, 3, 3, 3, 1)

    text = (
        f"🎯 <b>СУПЕРЭКСПРЕСС ТУРА (БЕСПЛАТНО)</b>\n\n"
        f"<blockquote>Угадай исходы 6 матчей!\n"
        f"4/6: <b>+500 FC</b> • 5/6: <b>+2 500 FC</b> • 6/6: <b>+10 000 FC</b></blockquote>\n" +
        "\n".join(lines) +
        f"\n\n👇 <i>Выбери исходы кнопками ниже ({len(draft)}/6):</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("se_pick:"))
async def process_se_pick(callback: CallbackQuery):
    _, idx_str, code = callback.data.split(":")
    idx = int(idx_str)
    uid = callback.from_user.id
    draft = SUPEREXPRESS_DRAFTS.get(uid, {})
    draft[idx] = code
    SUPEREXPRESS_DRAFTS[uid] = draft
    await process_superexpress_menu(callback)

@dp.callback_query(F.data == "se_submit")
async def process_se_submit(callback: CallbackQuery):
    uid = callback.from_user.id
    draft = SUPEREXPRESS_DRAFTS.get(uid, {})
    if len(draft) < 6:
        await callback.answer("Выбери исходы для всех 6 матчей!", show_alert=True)
        return

    db = await get_real_matches()
    top6 = get_top_6_upcoming_matches(db)
    if len(top6) < 6:
        return

    round_key = "_".join(m["event_id"] for m in top6)
    existing = await db_manager.get_superexpress_entry(uid, round_key)
    if existing:
        await callback.answer("Ты уже участвуешь в этом тираже!", show_alert=True)
        return

    picks_list = []
    lbl_map = {"p1": "П1", "x": "Х", "p2": "П2"}
    for idx, m in enumerate(top6):
        c = draft[idx]
        picks_list.append({
            "event_id": m["event_id"],
            "league_slug": m["league_slug"],
            "teams": m["teams"],
            "pick_code": c,
            "pick_label": lbl_map[c]
        })

    await db_manager.create_superexpress_entry(uid, round_key, picks_list)
    SUPEREXPRESS_DRAFTS.pop(uid, None)
    await callback.answer("🎉 Купон Суперэкспресса принят!", show_alert=True)
    await process_superexpress_menu(callback)

# ================= РЕФЕРАЛЫ, АКТИВНЫЕ СТАВКИ, АРХИВ И ТОП-10 С ИНКОГНИТО =================
@dp.callback_query(F.data == "referral_menu")
async def process_referral_menu(callback: CallbackQuery):
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await bot.get_me()
        BOT_USERNAME = me.username

    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['user_id']}"
    share_text = quote(
        "⚽ Залетайте в AI_BET_BOT! Реальная футбольная линия, ИИ-аналитика и турнир капперов.\n"
        "🎁 По моей ссылке стартовый банк 1 500 FC вместо 1 000 FC:"
    )
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_text}"

    text = (
        f"🤝 <b>ПАРТНЕРСКАЯ ПРОГРАММА (+500 FC)</b>\n\n"
        f"<blockquote>👥 Приглашено друзей: <b><code>{user.get('referrals_count', 0)}</code></b>\n"
        f"💰 Заработано: <b><code>{user.get('referrals_count', 0) * 500} FC</code></b></blockquote>\n"
        f"• Тебе мгновенно начисляется <b><code>+500 FC</code></b> за каждого друга\n"
        f"• Друг получает повышенный стартовый банк <b><code>1 500 FC</code></b>\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{ref_link}</code>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Отправить приглашение другу", url=share_url)
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
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
            end_dt = datetime.fromtimestamp(b["settle_ts"], tz=MSK_TZ).strftime("%d.%m в %H:%M МСК")
            btype = "⚡ Экспресс" if b.get("bet_type") == "express" else "⚽ Ординар"
            pot_win = round(b["amount"] * b["odds"], 1)
            events_multiline = format_bet_legs_multiline(b, with_result=False)
            b_tag = f"\n🚀 Бустер: <code>{BOOSTER_NAMES.get(b['booster_used'], '')}</code>" if b.get("booster_used") else ""
            lines.append(
                f"<blockquote>🎫 <b>Купон #{b['bet_id']}</b> ({btype}) • Кэф: <b><code>{b['odds']}</code></b>\n"
                f"{events_multiline}{b_tag}\n"
                f"💵 Ставка: <code>{b['amount']} FC</code> ➔ Выплата: <b><code>{pot_win} FC</code></b>\n"
                f"⏱ Расчет: <i>~{end_dt}</i></blockquote>"
            )
            builder.button(text=f"💸 CashOut купона #{b['bet_id']}", callback_data=f"cashout_ask:{b['bet_id']}")

        text = "⏳ <b>МОИ АКТИВНЫЕ КУПОНЫ В ИГРЕ:</b>\n\n" + "\n".join(lines)
        builder.button(text="📡 Обновить Live-статусы матчей", callback_data="check_live_status")

    builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
    builder.button(text="⬅️ В кабинет", callback_data="profile")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("cashout_ask:"))
async def process_cashout_ask(callback: CallbackQuery):
    bet_id = int(callback.data.split(":")[1])
    bet = await db_manager.get_bet_by_id(bet_id, callback.from_user.id)
    if not bet or bet["status"] != "pending":
        await callback.answer("Купон уже рассчитан!", show_alert=True)
        return

    async with aiohttp.ClientSession() as session:
        offer = await calculate_cashout_offer(session, bet)

    if offer <= 0:
        await callback.answer("⛔ CashOut недоступен: событие в купоне уже проиграло.", show_alert=True)
        return

    events_multiline = format_bet_legs_multiline(bet, with_result=False)
    text = (
        f"💸 <b>ДОСРОЧНЫЙ ВЫКУП (CASHOUT)</b>\n\n"
        f"<blockquote>🎫 <b>Купон #{bet['bet_id']}</b> (Кэф <code>{bet['odds']}</code>)\n"
        f"{events_multiline}\n"
        f"💵 <b>Сумма ставки:</b> <code>{bet['amount']} FC</code></blockquote>\n"
        f"💰 <b>Сумма выкупа сейчас:</b> <b><code>{offer} FC</code></b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Забрать {offer} FC сейчас", callback_data=f"cashout_confirm:{bet_id}:{offer}")
    builder.button(text="🔙 Оставить ставку в игре", callback_data="active_bets")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("cashout_confirm:"))
async def process_cashout_confirm(callback: CallbackQuery):
    _, bet_id_str, offer_str = callback.data.split(":")
    bet_id = int(bet_id_str)
    offer = float(offer_str)
    bet = await db_manager.get_bet_by_id(bet_id, callback.from_user.id)
    if not bet or bet["status"] != "pending":
        await callback.answer("Купон уже закрыт!", show_alert=True)
        return

    res = await db_manager.settle_bet_in_db(bet, "cashout", offer, f"CashOut ({offer} FC)")
    await callback.answer(f"💸 Купон #{bet_id} выкуплен! На баланс зачислено +{res['payout']} FC.", show_alert=True)
    await process_active_bets(callback)

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
                live_info.append(f"#{b['bet_id']}:\n{res.get('live_summary', '')}")

    if settled_count > 0:
        await callback.answer(f"✅ Рассчитано завершенных купонов: {settled_count}! Проверь чат.", show_alert=True)
    else:
        clean_alert = re.sub(r"<.*?>", "", "\n".join(live_info))[:195]
        await callback.answer(f"📡 Статусы обновлены:\n{clean_alert}", show_alert=True)
    await process_active_bets(callback)

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
            st = b["status"]
            if st == "win":
                badge = f"✅ ВЫИГРЫШ (+{round(b['amount']*b['odds'], 1)} FC)"
            elif st == "push":
                badge = f"🔄 ВОЗВРАТ (+{b['amount']} FC)"
            elif st == "cashout":
                badge = f"💸 CASHOUT ({b.get('score_result', '')})"
            else:
                badge = f"❌ ПРОИГРЫШ (-{b['amount']} FC)"

            events_multiline = format_bet_legs_multiline(b, with_result=True)
            lines.append(
                f"<blockquote>🎫 <b>Купон #{b['bet_id']}</b> — <b>{badge}</b>\n"
                f"{events_multiline}\n"
                f"💵 Сумма: <code>{b['amount']} FC</code> • Итоговый кэф: <code>{b['odds']}</code></blockquote>"
            )
        text = "🗄 <b>АРХИВ РАССЧИТАННЫХ СТАВОК:</b>\n\n" + "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.button(text="⏳ Активные ставки", callback_data="active_bets")
    builder.button(text="⬅️ В кабинет", callback_data="profile")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "claim_bonus")
async def process_claim_bonus(callback: CallbackQuery, state: FSMContext):
    ok, amount, rank_name = await db_manager.claim_daily_bonus(callback.from_user.id)
    if ok:
        await callback.answer(f"🎉 Бонус ранга «{rank_name}»: +{amount} FC зачислено на баланс!", show_alert=True)
        await process_profile(callback, state)
    else:
        await callback.answer("⏳ Ты уже забирал бонус сегодня! Возвращайся завтра.", show_alert=True)

async def render_leaderboard_view(callback: CallbackQuery):
    viewer = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    is_incog = int(viewer.get("is_incognito") or 0) == 1

    top = await db_manager.get_leaderboard()
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, u in enumerate(top):
        place_str = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        u_incog = int(u.get("is_incognito") or 0) == 1
        is_me = (u["user_id"] == callback.from_user.id)

        if u_incog:
            disp_name = f"🕶 Скрытый #{str(u['user_id'])[-4:]}" + (" <i>(Ты)</i>" if is_me else "")
            club_tag = ""
        else:
            disp_name = f"<b>{u['username']}</b>" + (" <i>(Ты)</i>" if is_me else "")
            club_tag = f" • <i>{u['favorite_club']}</i>" if u.get("favorite_club") else ""

        lines.append(
            f"{place_str} {disp_name}{club_tag} — <b><code>{round(u['balance'], 1)} FC</code></b> <i>(Побед: {u['wins']})</i>"
        )

    body = "\n".join(lines) if lines else "Рейтинг пока формируется."
    incog_btn_txt = "🟢 Инкогнито: ВКЛ" if is_incog else "🕶 Инкогнито: ВЫКЛ"

    builder = InlineKeyboardBuilder()
    builder.button(text=incog_btn_txt, callback_data="toggle_incognito")
    builder.button(text="👤 Кабинет", callback_data="profile")
    builder.button(text="🏠 В меню", callback_data="back_to_main")
    builder.adjust(2, 1)

    await callback.message.edit_text(
        f"🏆 <b>ТОП-10 КАППЕРОВ ПРОЕКТА</b>\n\n<blockquote>{body}</blockquote>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "leaderboard")
async def process_leaderboard(callback: CallbackQuery):
    await render_leaderboard_view(callback)
    await callback.answer()

@dp.callback_query(F.data == "toggle_incognito")
async def process_toggle_incognito(callback: CallbackQuery):
    new_state = await db_manager.toggle_user_incognito(callback.from_user.id)
    msg = "🕶 Режим Инкогнито ВКЛЮЧЕН: твой ник скрыт в Топ-10!" if new_state == 1 else "👀 Режим Инкогнито ВЫКЛЮЧЕН: твой ник снова виден в Топ-10!"
    await callback.answer(msg, show_alert=True)
    await render_leaderboard_view(callback)

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
        f"⚡ <b>ЭКСПРЕСС ДНЯ (ТОП-6 СОБЫТИЙ)</b>\n\n"
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

    mkt = evaluate_custom_market(match, pick_code)
    if not mkt:
        await callback.answer("⚠️ Некорректный рынок!", show_alert=True)
        return

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
        "pick_code": mkt["pick_code"],
        "pick": mkt["label"],
        "odds": mkt["odds"],
        "prob": mkt["prob"],
        "start_ts": match["start_ts"],
        "end_ts": match["end_ts"]
    })
    USER_SLIPS[uid] = slip
    await callback.answer(
        f"✅ Добавлено в экспресс: {match['teams']} — {mkt['label']} ({mkt['odds']}). Событий: {len(slip)}",
        show_alert=True
    )
    await render_match_card(callback.message, league_key, match_id, callback.from_user.id)

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

# ================= КАРТОЧКА МАТЧА, СВОДКА И КОНСТРУКТОР ТОТАЛОВ =================
@dp.callback_query(F.data.startswith("refresh_league:"))
async def process_refresh_league(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    await callback.answer("📡 Обновляю расписание...")
    db = await get_real_matches(force_refresh=True)
    league_data = db.get(league_key, {})
    matches = league_data.get("matches", {})
    if not matches:
        text = f"<b>{league_data.get('title', 'Лига')}</b>\n\n<blockquote>📅 На ближайшие дни официальных матчей не найдено.</blockquote>"
    elif league_data.get("extended"):
        text = f"<b>{league_data['title']}</b>\n📅 <i>Матчи ближайшего тура (время МСК):</i>"
    else:
        text = f"<b>{league_data['title']}</b>\n📅 <i>Расписание на ближайшие 7 дней (МСК):</i>"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")

@dp.callback_query(F.data.startswith("league:"))
async def process_league_select(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    league_key = callback.data.split(":")[1]
    db = await get_real_matches()
    league_data = db.get(league_key, {})
    matches = league_data.get("matches", {})

    if not matches:
        text = (
            f"<b>{league_data.get('title', 'Турнир')}</b>\n\n"
            f"<blockquote>📅 На ближайшие дни матчей не найдено. Нажми «🔄 Обновить».</blockquote>"
        )
    elif league_data.get("extended"):
        text = f"<b>{league_data['title']}</b>\n📅 <i>Матчи ближайшего тура (время МСК):</i>"
    else:
        text = f"<b>{league_data['title']}</b>\n📅 <i>Реальные матчи на 7 дней (время МСК):</i>"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")
    await callback.answer()

async def render_match_card(message_obj: Message, league_key: str, match_id: str, user_id: int):
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        return False

    user = await db_manager.get_user(user_id)
    fav_club = user.get("favorite_club") or ""
    is_fav_match = fav_club and (fav_club in match["teams"])
    fav_banner = f"\n⭐ <b>Матч любимого клуба ({fav_club}) • +10% к выплате!</b>" if is_fav_match else ""

    league_title = db[league_key]["title"]
    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)

    if match["event_id"] not in AI_CACHE:
        await message_obj.edit_text(f"🧠 <i>ИИ анализирует матч {match['teams']}...</i>", parse_mode="HTML")

    prompt = (
        f"Предстоящий матч. Турнир: {league_title}. Дата: {match['date']}.\n"
        f"Хозяева: {match['home_team']}. Гости: {match['away_team']}. Статистика: {match['records_info']}.\n"
        f"Ожидаемые голы xG: {match['exp_goals']}. Линия: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}, ТБ 1.5={odds['tb15']}, ТБ 2.5={odds['tb25']}, ОЗ(Да)={odds['btts']}.\n"
        f"Дай краткий разбор (до 50 слов) в 2 пункта:\n"
        f"1. ⚔️ Тактика и потенциал атаки.\n"
        f"2. 🎯 Лучшая ставка из линии (Тотал, ОЗ, Фора(0) или исход) с кэфом."
    )
    ai_verdict = await ask_ai_cached(match["event_id"], prompt) or smart_local_match_analysis(match, probs)

    text = (
        f"🏟 <b>{league_title}</b>\n"
        f"🏠 <b>{match['home_team']}</b>  vs  ✈️ <b>{match['away_team']}</b>\n"
        f"🕒 <code>{match['date']}</code>{fav_banner}\n\n"
        f"<blockquote>📊 <b>1Х2:</b> П1: <b><code>{odds['p1']}</code></b> ({probs['p1']}%) | Х: <b><code>{odds['x']}</code></b> ({probs['x']}%) | П2: <b><code>{odds['p2']}</code></b> ({probs['p2']}%)\n"
        f"⚽ <b>xG матча:</b> <b><code>{match['exp_goals']}</code></b>  •  Точный счет ИИ: <b><code>{match['best_score']}</code></b></blockquote>\n"
        f"🤖 <b>Вердикт ИИ:</b>\n{ai_verdict}"
    )
    await message_obj.edit_text(
        text,
        reply_markup=match_outcomes_kb(league_key, match_id, odds, user_id),
        parse_mode="HTML"
    )
    return True

@dp.callback_query(F.data.startswith("match:"))
async def process_match_select(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    parts = callback.data.split(":")
    league_key, match_id = parts[1], parts[2]
    ok = await render_match_card(callback.message, league_key, match_id, callback.from_user.id)
    if not ok:
        await callback.answer("⛔ Этот матч уже начался или завершен!", show_alert=True)
        return
    await callback.answer()

@dp.callback_query(F.data.startswith("stats_menu:"))
async def process_stats_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, league_key, match_id = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await callback.answer("⛔ Матч уже начался!", show_alert=True)
        return

    hs = match["h_stats"]
    as_ = match["a_stats"]
    text = (
        f"📊 <b>ДЕТАЛЬНАЯ СВОДКА И ИТБ</b>\n\n"
        f"🏟 <b>Арена:</b> {match['venue']}\n\n"
        f"<blockquote>🏠 <b>{match['home_team']}</b>\n"
        f"• Сезон: <code>{hs['record_str']}</code> ({hs['points']} очк.)\n"
        f"• Форма: {hs['form_visual']} | xG: <b><code>{match['lam_h']}</code></b></blockquote>\n"
        f"<blockquote>✈️ <b>{match['away_team']}</b>\n"
        f"• Сезон: <code>{as_['record_str']}</code> ({as_['points']} очк.)\n"
        f"• Форма: {as_['form_visual']} | xG: <b><code>{match['lam_a']}</code></b></blockquote>\n"
        f"👇 <b>Индивидуальный Тотал Больше (ИТБ1 — Хозяева, ИТБ2 — Гости):</b>"
    )
    await callback.message.edit_text(text, reply_markup=stats_and_itb_kb(match), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("totals_menu:"))
async def process_totals_menu(callback: CallbackQuery, state: FSMContext):
    _, league_key, match_id, direction = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await callback.answer("⛔ Матч уже начался!", show_alert=True)
        return

    await state.set_state(BetStates.waiting_for_custom_total)
    await state.update_data(league_key=league_key, match_id=match_id, direction=direction)

    dir_title = "📈 ТОТАЛ БОЛЬШЕ (ТБ)" if direction == "tb" else "📉 ТОТАЛ МЕНЬШЕ (ТМ)"
    text = (
        f"⚽ <b>{dir_title}</b>\n\n"
        f"<blockquote>🏟 <b>{match['teams']}</b>\n"
        f"📊 <b>Ожидаемые голы (xG):</b> <b><code>{match['exp_goals']}</code></b>\n"
        f"🔄 <i>Целые тоталы (1.0, 2.0, 3.0) идут с возвратом при точном попадании!</i></blockquote>\n"
        f"👇 <b>Выбери кнопкой ИЛИ напиши любое число в чат</b> (например: <code>2.5</code> или <code>3</code>):"
    )
    await callback.message.edit_text(text, reply_markup=totals_constructor_kb(match, direction), parse_mode="HTML")
    await callback.answer()

@dp.message(BetStates.waiting_for_custom_total)
async def process_custom_total_input(message: Message, state: FSMContext):
    data = await state.get_data()
    league_key = data.get("league_key")
    match_id = data.get("match_id")
    direction = data.get("direction", "tb")

    raw = (message.text or "").strip().replace(",", ".")
    try:
        val = float(raw)
    except Exception:
        await message.answer("⚠️ Введи значение тотала числом (например: <code>1.5</code>, <code>2</code> или <code>3.5</code>):", parse_mode="HTML")
        return

    rounded_val = round(val * 2) / 2
    if rounded_val < 0.5 or rounded_val > 6.5:
        await message.answer("⚠️ Допустимый диапазон — от <code>0.5</code> до <code>6.5</code> голов:", parse_mode="HTML")
        return

    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await state.clear()
        await message.answer("⛔ Матч уже начался.", reply_markup=main_menu_kb(message.from_user.id))
        return

    is_int = abs(rounded_val - round(rounded_val)) < 1e-5
    line_str = f"{int(round(rounded_val))}.0" if is_int else f"{rounded_val:.1f}"
    pick_code = f"{direction}_{line_str}"

    await state.clear()
    target_code = f"{league_key}-{match_id}-{pick_code}"
    info = await resolve_bet_target(target_code, message.from_user.id)
    if not info:
        await message.answer("⚠️ Ошибка расчета котировки.")
        return

    user = await db_manager.get_user(message.from_user.id, message.from_user.username)
    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m.%Y в %H:%M МСК")

    text = (
        f"🎫 <b>ОФОРМЛЕНИЕ КУПОНА</b>\n\n"
        f"<blockquote>{info['events_preview']}\n"
        f"📈 <b>Коэффициент:</b> <b><code>{info['odds']}</code></b>\n"
        f"⏱ <b>Расчет:</b> <i>~{end_str}</i></blockquote>\n"
        f"💰 <b>Доступный баланс:</b> <code>{round(user['balance'], 1)} FC</code>\n\n"
        f"👇 <b>Выбери сумму ставки или добавь исход в Экспресс:</b>"
    )
    await message.answer(text, reply_markup=amount_selection_kb(target_code, user["balance"]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("extras_menu:"))
async def process_extras_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, league_key, match_id = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await callback.answer("⛔ Матч уже начался!", show_alert=True)
        return

    text = (
        f"🛡️ <b>ФОРЫ, ДВОЙНОЙ ШАНС И ОЗ</b>\n\n"
        f"<blockquote>🏟 <b>{match['teams']}</b>\n"
        f"• <b>1Х / Х2</b> — команда не проиграет\n"
        f"• <b>Фора (0)</b> — победа с возвратом при ничьей\n"
        f"• <b>ОЗ</b> — обе команды забьют</blockquote>\n"
        f"👇 <b>Выбери исход:</b>"
    )
    await callback.message.edit_text(text, reply_markup=extras_menu_kb(match), parse_mode="HTML")
    await callback.answer()

async def resolve_bet_target(target_code: str, user_id: int) -> dict | None:
    db = await get_real_matches()
    now_ts = int(now_msk().timestamp())

    if target_code == "express-day":
        exp = build_daily_express_data(db)
        if not exp:
            return None
        preview_lines = [
            f"<b>{i+1}. {leg['teams']}</b>\n   🎯 <code>{leg['pick_label']}</code> (кэф <code>{leg['odds']}</code>)"
            for i, leg in enumerate(exp["legs"])
        ]
        return {
            "match_title": exp["summary_title"],
            "pick": exp["summary_pick"],
            "events_preview": "\n".join(preview_lines),
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
        multiline_titles = []
        preview_lines = []
        legs = []
        for idx, s in enumerate(slip, 1):
            if s["start_ts"] <= now_ts:
                return None
            total_odd *= s["odds"]
            comb_prob *= (s["prob"] / 100.0)
            if s["end_ts"] > max_ts:
                max_ts = s["end_ts"]
            multiline_titles.append(f"{idx}. {s['match_title']} — {s['pick']} ({s['odds']})")
            preview_lines.append(f"<b>{idx}. {s['match_title']}</b>\n   🎯 <code>{s['pick']}</code> (кэф <code>{s['odds']}</code>)")
            legs.append({
                "league_slug": s["league_slug"],
                "event_id": s["event_id"],
                "teams": s["match_title"],
                "pick_code": s["pick_code"],
                "pick_label": s["pick"],
                "odds": s["odds"]
            })
        return {
            "match_title": f"Персональный экспресс ({len(slip)} матчей)",
            "pick": "\n".join(multiline_titles),
            "events_preview": "\n".join(preview_lines),
            "odds": round(total_odd, 2),
            "prob": round(comb_prob * 100, 1),
            "end_ts": max_ts,
            "bet_type": "express",
            "legs_json": json.dumps(legs, ensure_ascii=False)
        }
    else:
        l_key, m_id, p_code = target_code.split("-", 2)
        match = db.get(l_key, {}).get("matches", {}).get(m_id)
        if not match or match["start_ts"] <= now_ts:
            return None
        mkt = evaluate_custom_market(match, p_code)
        if not mkt:
            return None
        legs = [{
            "league_slug": match["league_slug"],
            "event_id": match["event_id"],
            "teams": match["teams"],
            "pick_code": mkt["pick_code"],
            "pick_label": mkt["label"],
            "odds": mkt["odds"]
        }]
        return {
            "match_title": f"{match['teams']} ({match['short_date']})",
            "pick": mkt["label"],
            "events_preview": f"🏟 <b>Матч:</b> {match['teams']} ({match['short_date']})\n🎯 <b>Исход:</b> <code>{mkt['label']}</code>",
            "odds": mkt["odds"],
            "prob": mkt["prob"],
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

    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m.%Y в %H:%M МСК")
    booster_code = user.get("active_booster") or ""
    booster_note = f"\n🚀 <b>Будет применен бустер:</b> {BOOSTER_NAMES.get(booster_code, '')}" if booster_code else ""

    text = (
        f"🎫 <b>ОФОРМЛЕНИЕ КУПОНА</b>\n\n"
        f"<blockquote>{info['events_preview']}\n"
        f"📈 <b>Коэффициент:</b> <b><code>{info['odds']}</code></b>\n"
        f"⏱ <b>Расчет:</b> <i>~{end_str}</i></blockquote>"
        f"{booster_note}\n"
        f"💰 <b>Доступный баланс:</b> <code>{round(user['balance'], 1)} FC</code>\n\n"
        f"👇 <b>Выбери сумму ставки или введи свою:</b>"
    )
    await callback.message.edit_text(text, reply_markup=amount_selection_kb(target_code, user["balance"]), parse_mode="HTML")
    await callback.answer()

async def build_bet_accepted_response(user_id: int, bet_id: int, info: dict, amount: int, res: dict) -> tuple[str, InlineKeyboardBuilder]:
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await bot.get_me()
        BOT_USERNAME = me.username

    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m в %H:%M МСК")
    b_note = f"\n🚀 <b>Бустер:</b> <code>{BOOSTER_NAMES.get(res['booster_used'], '')}</code>" if res.get("booster_used") else ""
    fav_note = "\n⭐ <b>Матч любимого клуба:</b> <i>+10% к чистой прибыли!</i>" if res.get("is_fav_club") else ""

    text = (
        f"✅ <b>СТАВКА ПРИНЯТА! (КУПОН #{bet_id})</b>\n\n"
        f"<blockquote>{info['events_preview']}\n\n"
        f"📈 <b>Итоговый кэф:</b> <b><code>{res['final_odds']}</code></b>\n"
        f"💵 <b>Сумма ставки:</b> <code>{amount} FC</code>\n"
        f"💰 <b>Возможная выплата:</b> <b><code>{res['potential_win']} FC</code></b></blockquote>"
        f"{b_note}{fav_note}\n"
        f"🏦 <b>Остаток на балансе:</b> <code>{res['new_balance']} FC</code>\n"
        f"📡 <b>Расчет:</b> <i>~{end_str}</i>"
    )

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    share_txt = quote(
        f"🎫 Мой купон #{bet_id} в AI_BET_BOT (Кэф {res['final_odds']})!\n"
        f"💰 Потенциальная выплата: {res['potential_win']} FC.\n"
        f"Заходи и получай 1 500 FC на старт:"
    )
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_txt}"

    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Поделиться купоном с другом", url=share_url)
    builder.button(text="⏳ Мои активные ставки", callback_data="active_bets")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return text, builder

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

    text, builder = await build_bet_accepted_response(callback.from_user.id, res["bet_id"], info, amount, res)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer("🎫 Купон зарегистрирован!")

@dp.callback_query(F.data.startswith("custom_amt:"))
async def process_custom_amount_prompt(callback: CallbackQuery, state: FSMContext):
    target_code = callback.data.split(":")[1]
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
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

    text, builder = await build_bet_accepted_response(message.from_user.id, res["bet_id"], info, amount, res)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ================= ЗАКРЫТАЯ АДМИН-ПАНЕЛЬ (/admin) =================
def is_admin(user_id: int) -> bool:
    global ADMIN_ID
    if ADMIN_ID == 0:
        ADMIN_ID = user_id
    return user_id == ADMIN_ID

def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Сделать рассылку всем", callback_data="admin_broadcast")
    builder.button(text="🎁 Выдать FC игроку по ID", callback_data="admin_gift")
    builder.button(text="🔄 Обновить статистику", callback_data="admin_panel")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    st = await db_manager.get_project_stats()
    text = (
        f"⚙️ <b>ПАНЕЛЬ УПРАВЛЕНИЯ ПРОЕКТОМ (ADMIN)</b>\n\n"
        f"<blockquote>👥 Игроков в базе: <b><code>{st['users']}</code></b>\n"
        f"🎫 Всего купонов: <b><code>{st['bets']}</code></b>\n"
        f"⏳ Активных купонов: <b><code>{st['active_bets']}</code></b>\n"
        f"🏦 Суммарный банк: <b><code>{st['total_fc']} FC</code></b></blockquote>\n"
        f"👇 Выбери действие:"
    )
    await message.answer(text, reply_markup=admin_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "admin_panel")
async def process_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    st = await db_manager.get_project_stats()
    text = (
        f"⚙️ <b>ПАНЕЛЬ УПРАВЛЕНИЯ ПРОЕКТОМ (ADMIN)</b>\n\n"
        f"<blockquote>👥 Игроков в базе: <b><code>{st['users']}</code></b>\n"
        f"🎫 Всего купонов: <b><code>{st['bets']}</code></b>\n"
        f"⏳ Активных купонов: <b><code>{st['active_bets']}</code></b>\n"
        f"🏦 Суммарный банк: <b><code>{st['total_fc']} FC</code></b></blockquote>\n"
        f"👇 Выбери действие:"
    )
    await callback.message.edit_text(text, reply_markup=admin_kb(), parse_mode="HTML")
    await callback.answer("Статистика обновлена")

@dp.callback_query(F.data == "admin_broadcast")
async def process_admin_broadcast_ask(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_broadcast)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text(
        "📢 <b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n\n"
        "Отправь в чат текст сообщения, которое получат все игроки бота (поддерживается HTML):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast)
async def process_admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    uids = await db_manager.get_all_user_ids()
    sent = 0
    for uid in uids:
        try:
            await bot.send_message(uid, message.text, parse_mode="HTML", reply_markup=main_menu_kb(uid))
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
    await message.answer(f"✅ Рассылка завершена! Доставлено: <b>{sent}</b> из {len(uids)}.", reply_markup=admin_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "admin_gift")
async def process_admin_gift_ask(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_gift_data)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text(
        "🎁 <b>НАЧИСЛЕНИЕ ВАЛЮТЫ ИГРОКУ</b>\n\n"
        "Отправь через пробел <code>ID_игрока Сумму</code> (например: <code>123456789 2000</code>):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_gift_data)
async def process_admin_gift_exec(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").strip().split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
        await message.answer("⚠️ Введи корректно два числа через пробел: <code>ID Сумма</code>", parse_mode="HTML")
        return

    target_uid, add_amt = int(parts[0]), float(parts[1])
    ok = await db_manager.add_balance_to_user(target_uid, add_amt)
    await state.clear()
    if ok:
        try:
            await bot.send_message(target_uid, f"🎁 Администратор начислил тебе <b><code>+{add_amt} FC</code></b> на баланс!", parse_mode="HTML")
        except Exception:
            pass
        await message.answer(f"✅ Игроку <code>{target_uid}</code> начислено <b>{add_amt} FC</b>!", reply_markup=admin_kb(), parse_mode="HTML")
    else:
        await message.answer("⚠️ Игрок с таким ID не найден.", reply_markup=admin_kb(), parse_mode="HTML")

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
