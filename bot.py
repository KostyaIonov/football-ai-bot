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
from aiogram.types import Message, CallbackQuery, BotCommand, BotCommandScopeDefault
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from aiogram.types import WebAppInfo

WEBAPP_BASE_URL = (os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

# ================= НАСТРОЙКИ СЕРВЕРА И КЛЮЧИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "gsk_" + "4Tsu0D9a7WpeKXgsfCEBWGdyb3FYh36zWsKthL2t6jJ1ROtV1dqH")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_BASE_URL = (os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

USER_SLIPS = {}
SUPEREXPRESS_DRAFTS = {}
PVP_DRAFTS = {}
AI_CACHE = {}
BOT_USERNAME = ""

class BetStates(StatesGroup):
    waiting_for_custom_total = State()
    waiting_for_custom_amount = State()
    waiting_for_nickname = State()
    waiting_for_pvp_stake = State()
    waiting_for_pvp_target = State()
    waiting_for_auction_bid = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_gift_data = State()
    waiting_for_user_lookup = State()

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

# ================= КОНФИГУРАЦИЯ ЛИГ (С РПЛ И ЛИГОЙ НАЦИЙ) =================
MSK_TZ = timezone(timedelta(hours=3))

MAIN_LEAGUES = {
    "ucl": {"title": "🏆 Лига Чемпионов", "slug": "uefa.champions"},
    "epl": {"title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ", "slug": "eng.1"},
    "laliga": {"title": "🇪🇸 Ла Лига", "slug": "esp.1"},
    "seriea": {"title": "🇮🇹 Серия А", "slug": "ita.1"},
    "bundesliga": {"title": "🇩🇪 Бундеслига", "slug": "ger.1"},
    "ligue1": {"title": "🇫🇷 Лига 1", "slug": "fra.1"}
}

OTHER_LEAGUES = {
    "rpl": {"title": "🇷🇺 РПЛ (Россия)", "slug": "rus.1"},
    "unl": {"title": "🏆 Лига Наций УЕФА", "slug": "uefa.nations"},
    "uel": {"title": "🏆 Лига Европы", "slug": "uefa.europa"},
    "uecl": {"title": "🏆 Лига Конференций", "slug": "uefa.europa.conference"},
    "por": {"title": "🇵🇹 Португалия", "slug": "por.1"},
    "ned": {"title": "🇳🇱 Нидерланды", "slug": "ned.1"},
    "tur": {"title": "🇹🇷 Турция", "slug": "tur.1"},
    "eng2": {"title": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Чемпионшип", "slug": "eng.2"},
    "bra": {"title": "🇧🇷 Бразилия", "slug": "bra.1"}
}

LEAGUES_CONFIG = {**MAIN_LEAGUES, **OTHER_LEAGUES}

# 10 уровней Стадионов
STADIUM_LEVELS = {
    1: {"name": "Дворовая коробка", "cap": "500 мест", "income": 150, "price": 0},
    2: {"name": "Тренировочное поле", "cap": "2 500 мест", "income": 300, "price": 1500},
    3: {"name": "Городской стадион", "cap": "8 000 мест", "income": 500, "price": 4000},
    4: {"name": "Арена Первой Лиги", "cap": "18 000 мест", "income": 800, "price": 10000},
    5: {"name": "Футбольный Колизей", "cap": "32 000 мест", "income": 1200, "price": 25000},
    6: {"name": "Национальный Парк", "cap": "45 000 мест", "income": 1800, "price": 60000},
    7: {"name": "Элитная Арена", "cap": "55 000 мест", "income": 2500, "price": 130000},
    8: {"name": "Гранд-Стэдиум УЕФА", "cap": "68 000 мест", "income": 3500, "price": 250000},
    9: {"name": "Кибер-Дом Чемпионов", "cap": "80 000 мест", "income": 4800, "price": 450000},
    10: {"name": "Мега-Арена Легенд", "cap": "95 000 мест", "income": 6500, "price": 800000}
}

# 5 уровней ИИ-Лаборатории
LAB_LEVELS = {
    1: {"name": "Базовый скаут", "odd_bonus": 0.0, "price": 0, "desc": "Базовый анализ матчей"},
    2: {"name": "Отдел xG-метрик", "odd_bonus": 0.02, "price": 3000, "desc": "Открывает «🔥 Валуй дня» (+0.02 к кэфам)"},
    3: {"name": "Нейросеть v2.0", "odd_bonus": 0.04, "price": 9000, "desc": "Валуй дня + прибавка +0.04 к кэфам"},
    4: {"name": "Суперкомпьютер Лиги", "odd_bonus": 0.06, "price": 22000, "desc": "Валуй дня + прибавка +0.06 к кэфам"},
    5: {"name": "Квантовый Оракул", "odd_bonus": 0.10, "price": 50000, "desc": "Максимальный буст +0.10 ко всем кэфам"}
}

# Карточки FUT-Каппера
FUT_CARDS = {
    "fw_1": {"id": "fw_1", "role": "FW", "tier": 1, "name": "🥉 Джейми Варди", "val": 5, "desc": "+5% к прибыли на Тоталах"},
    "gk_1": {"id": "gk_1", "role": "GK", "tier": 1, "name": "🥉 Джордан Пикфорд", "val": 8, "desc": "8% кэшбэк при проигрыше"},
    "co_1": {"id": "co_1", "role": "COACH", "tier": 1, "name": "🥉 Микель Артета", "val": 0.10, "desc": "+0.10 к кэфу Экспресса"},
    "fw_2": {"id": "fw_2", "role": "FW", "tier": 2, "name": "🥇 Мохамед Салах", "val": 10, "desc": "+10% к прибыли на Тоталах"},
    "fw_3": {"id": "fw_3", "role": "FW", "tier": 2, "name": "🥇 Харри Кейн", "val": 11, "desc": "+11% к прибыли на Тоталах"},
    "gk_2": {"id": "gk_2", "role": "GK", "tier": 2, "name": "🥇 Алиссон Бекер", "val": 14, "desc": "14% кэшбэк при проигрыше"},
    "co_2": {"id": "co_2", "role": "COACH", "tier": 2, "name": "🥇 Юрген Клопп", "val": 0.20, "desc": "+0.20 к кэфу Экспресса"},
    "fw_4": {"id": "fw_4", "role": "FW", "tier": 3, "name": "💎 Килиан Мбаппе (TOTY)", "val": 16, "desc": "+16% к прибыли на Тоталах"},
    "fw_5": {"id": "fw_5", "role": "FW", "tier": 3, "name": "💎 Эрлинг Холанд (ICON)", "val": 17, "desc": "+17% к прибыли на Тоталах"},
    "gk_3": {"id": "gk_3", "role": "GK", "tier": 3, "name": "💎 Тибо Куртуа (TOTY)", "val": 20, "desc": "20% кэшбэк при проигрыше"},
    "co_3": {"id": "co_3", "role": "COACH", "tier": 3, "name": "💎 Карло Анчелотти (ICON)", "val": 0.30, "desc": "+0.30 к кэфу Экспресса"},
    "goat_messi": {"id": "goat_messi", "role": "FW", "tier": 4, "name": "🐐 Лионель Месси (GOAT)", "val": 22, "desc": "+22% к прибыли на Тоталах"},
    "goat_ronaldo": {"id": "goat_ronaldo", "role": "FW", "tier": 4, "name": "🐐 Криштиану Роналду (GOAT)", "val": 22, "desc": "+22% к прибыли на Тоталах"},
    "goat_yashin": {"id": "goat_yashin", "role": "GK", "tier": 4, "name": "🐐 Лев Яшин (GOAT)", "val": 25, "desc": "25% кэшбэк при проигрыше"},
    "goat_pep": {"id": "goat_pep", "role": "COACH", "tier": 4, "name": "🐐 Пеп Гвардиола (GOAT)", "val": 0.45, "desc": "+0.45 к кэфу Экспресса"}
}

BLACK_MARKET_ROTATION = ["goat_messi", "goat_yashin", "goat_ronaldo", "goat_pep"]

POPULAR_CLUBS = [
    "Реал Мадрид", "Барселона", "Арсенал", "Ливерпуль",
    "Ман Сити", "Ман Юнайтед", "Челси", "Бавария",
    "Боруссия Д", "Байер", "Интер", "Милан",
    "Ювентус", "Наполи", "ПСЖ", "Атлетико",
    "ЦСКА", "Спартак", "Зенит", "Краснодар"
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
    # РПЛ (Россия)
    "CSKA Moscow": "ЦСКА", "PFC CSKA Moscow": "ЦСКА", "Spartak Moscow": "Спартак", "FC Spartak Moscow": "Спартак",
    "Zenit St Petersburg": "Зенит", "FC Zenit Saint Petersburg": "Зенит", "Krasnodar": "Краснодар", "FC Krasnodar": "Краснодар",
    "Dynamo Moscow": "Динамо М", "FC Dynamo Moscow": "Динамо М", "Lokomotiv Moscow": "Локомотив", "FC Lokomotiv Moscow": "Локомотив",
    "Rostov": "Ростов", "FC Rostov": "Ростов", "Rubin Kazan": "Рубин", "FC Rubin Kazan": "Рубин",
    "Krylia Sovetov": "Крылья Советов", "PFC Krylia Sovetov Samara": "Крылья Советов", "Akhmat Grozny": "Ахмат",
    "Pari Nizhny Novgorod": "Пари НН", "FC Pari Nizhny Novgorod": "Пари НН", "Fakel Voronezh": "Факел",
    "Orenburg": "Оренбург", "FC Orenburg": "Оренбург", "Khimki": "Химки", "FC Khimki": "Химки",
    "Akron Togliatti": "Акрон", "Dynamo Makhachkala": "Динамо Мх", "Baltika Kaliningrad": "Балтика", "Torpedo Moscow": "Торпедо М",
    # Сборные (Лига Наций УЕФА)
    "France": "Франция", "Spain": "Испания", "England": "Англия", "Germany": "Германия", "Italy": "Италия",
    "Portugal": "Португалия", "Netherlands": "Нидерланды", "Belgium": "Бельгия", "Croatia": "Хорватия",
    "Switzerland": "Швейцария", "Denmark": "Дания", "Austria": "Австрия", "Serbia": "Сербия", "Hungary": "Венгрия",
    "Poland": "Польша", "Scotland": "Шотландия", "Ukraine": "Украина", "Turkey": "Турция", "Türkiye": "Турция",
    "Czechia": "Чехия", "Czech Republic": "Чехия", "Wales": "Уэльс", "Norway": "Норвегия", "Sweden": "Швеция",
    "Greece": "Греция", "Romania": "Румыния", "Slovakia": "Словакия", "Slovenia": "Словения", "Georgia": "Грузия",
    "Finland": "Финляндия", "Republic of Ireland": "Ирландия", "Ireland": "Ирландия", "Kazakhstan": "Казахстан",
    "Armenia": "Армения", "Belarus": "Беларусь", "Azerbaijan": "Азербайджан", "Iceland": "Исландия",
    # Топ-5 и другие лиги
    "Arsenal": "Арсенал", "Aston Villa": "Астон Вилла", "Bournemouth": "Борнмут", "AFC Bournemouth": "Борнмут",
    "Brentford": "Брентфорд", "Brighton & Hove Albion": "Брайтон", "Brighton": "Брайтон", "Chelsea": "Челси",
    "Crystal Palace": "Кристал Пэлас", "Everton": "Эвертон", "Fulham": "Фулхэм", "Ipswich Town": "Ипсвич",
    "Leicester City": "Лестер", "Liverpool": "Ливерпуль", "Manchester City": "Ман Сити",
    "Manchester United": "Ман Юнайтед", "Newcastle United": "Ньюкасл", "Nottingham Forest": "Ноттингем",
    "Southampton": "Саутгемптон", "Tottenham Hotspur": "Тоттенхэм", "West Ham United": "Вест Хэм",
    "Wolverhampton Wanderers": "Вулверхэмптон", "Leeds United": "Лидс", "Burnley": "Бернли",
    "Sunderland": "Сандерленд", "Sheffield United": "Шеффилд Ютд", "West Bromwich Albion": "Вест Бром",
    "Middlesbrough": "Мидлсбро", "Norwich City": "Норвич", "Coventry City": "Ковентри",
    "Watford": "Уотфорд", "Blackburn Rovers": "Блэкберн", "Bristol City": "Бристоль",
    "Hull City": "Халл Сити", "Stoke City": "Сток Сити", "Swansea City": "Суонси", "Millwall": "Миллуолл",
    "Queens Park Rangers": "КПР", "Preston North End": "Престон", "Cardiff City": "Кардифф",
    "Real Madrid": "Реал Мадрид", "Barcelona": "Барселона", "Atlético Madrid": "Атлетико",
    "Atletico Madrid": "Атлетико", "Athletic Club": "Атлетик Б", "Real Sociedad": "Реал Сосьедад",
    "Real Betis": "Бетис", "Villarreal": "Вильярреал", "Valencia": "Валенсия", "Sevilla": "Севилья",
    "Girona": "Жирона", "Celta Vigo": "Сельта", "Osasuna": "Осасуна", "Getafe": "Хетафе",
    "Rayo Vallecano": "Райо Вальекано", "Mallorca": "Мальорка", "Las Palmas": "Лас-Пальмас",
    "Alavés": "Алавес", "Deportivo Alavés": "Алавес", "Espanyol": "Эспаньол", "Leganés": "Леганес",
    "Real Valladolid": "Вальядолид", "Internazionale": "Интер", "Inter Milan": "Интер", "AC Milan": "Милан",
    "Juventus": "Ювентус", "Napoli": "Наполи", "AS Roma": "Рома", "Roma": "Рома", "Lazio": "Лацио",
    "Atalanta": "Аталанта", "Fiorentina": "Фиорентина", "Bologna": "Болонья", "Torino": "Торино",
    "Udinese": "Удинезе", "Genoa": "Дженоа", "Como": "Комо", "Parma": "Парма", "Hellas Verona": "Верона",
    "Empoli": "Эмполи", "Cagliari": "Кальяри", "Lecce": "Лечче", "Monza": "Монца", "Venezia": "Венеция",
    "Bayern Munich": "Бавария", "Borussia Dortmund": "Боруссия Д", "Bayer Leverkusen": "Байер",
    "RB Leipzig": "РБ Лейпциг", "VfB Stuttgart": "Штутгарт", "Eintracht Frankfurt": "Айнтрахт Ф",
    "SC Freiburg": "Фрайбург", "TSG Hoffenheim": "Хоффенхайм", "Werder Bremen": "Вердер",
    "Heidenheim": "Хайденхайм", "1. FC Heidenheim 1846": "Хайденхайм", "FC Augsburg": "Аугсбург",
    "VfL Wolfsburg": "Вольфсбург", "Borussia Mönchengladbach": "Боруссия М", "Mainz": "Майнц",
    "1. FSV Mainz 05": "Майнц", "1. FC Union Berlin": "Унион", "VfL Bochum": "Бохум",
    "FC St. Pauli": "Санкт-Паули", "Holstein Kiel": "Хольштайн", "Hamburger SV": "Гамбург", "FC Cologne": "Кельн",
    "Paris Saint-Germain": "ПСЖ", "AS Monaco": "Монако", "Monaco": "Монако", "Marseille": "Марсель",
    "Olympique de Marseille": "Марсель", "Lille": "Лилль", "LOSC Lille": "Лилль", "Lyon": "Лион",
    "Olympique Lyonnais": "Лион", "Nice": "Ницца", "OGC Nice": "Ницца", "Lens": "Ланс", "RC Lens": "Ланс",
    "Rennes": "Ренн", "Stade Rennais": "Ренн", "Stade Brestois 29": "Брест", "Brest": "Брест",
    "Reims": "Реймс", "Stade de Reims": "Реймс", "Strasbourg": "Страсбур", "RC Strasbourg Alsace": "Страсбур",
    "Toulouse": "Тулуза", "Montpellier": "Монпелье", "Nantes": "Нант", "FC Nantes": "Нант",
    "Auxerre": "Осер", "AJ Auxerre": "Осер", "Angers": "Анже", "Saint-Étienne": "Сент-Этьен", "Le Havre": "Гавр",
    "Sporting CP": "Спортинг", "Benfica": "Бенфика", "FC Porto": "Порту", "SC Braga": "Брага",
    "Vitória de Guimarães": "Витория Гим", "Famalicão": "Фамаликан", "Rio Ave": "Риу Аве", "Boavista": "Боавишта",
    "PSV Eindhoven": "ПСВ", "Feyenoord": "Фейеноорд", "Ajax": "Аякс", "AZ Alkmaar": "АЗ Алкмар",
    "FC Twente": "Твенте", "FC Utrecht": "Утрехт", "Sparta Rotterdam": "Спарта Р", "Heerenveen": "Херенвен",
    "Galatasaray": "Галатасарай", "Fenerbahce": "Фенербахче", "Fenerbahçe": "Фенербахче",
    "Besiktas": "Бешикташ", "Beşiktaş": "Бешикташ", "Trabzonspor": "Трабзонспор",
    "Istanbul Basaksehir": "Башакшехир", "Samsunspor": "Самсунспор", "Antalyaspor": "Антальяспор",
    "Flamengo": "Фламенго", "Palmeiras": "Палмейрас", "Botafogo": "Ботафого", "São Paulo": "Сан-Паулу",
    "Corinthians": "Коринтианс", "Fluminense": "Флуминенсе", "Grêmio": "Гремио", "Internacional": "Интернасьонал",
    "Atlético Mineiro": "Атлетико М", "Cruzeiro": "Крузейро", "Vasco da Gama": "Васко", "Santos": "Сантос",
    "Celtic": "Селтик", "Rangers": "Рейнджерс", "Club Brugge": "Брюгге", "Anderlecht": "Андерлехт",
    "Shakhtar Donetsk": "Шахтер", "Red Bull Salzburg": "Зальцбург", "Sturm Graz": "Штурм",
    "Sparta Prague": "Спарта Пр", "Slavia Prague": "Славия Пр", "Olympiacos": "Олимпиакос", "PAOK": "ПАОК"
}

# Короткие названия специально для мобильных кнопок, чтобы текст никогда не уходил в троеточие (...)
SHORT_BTN_NAMES = {
    "Кристал Пэлас": "Кр. Пэлас", "Вулверхэмптон": "Вулвз", "Реал Сосьедад": "Р. Сосьедад",
    "Райо Вальекано": "Райо", "Крылья Советов": "Крылья", "Интернасьонал": "Интер Бр",
    "Атлетико Минейро": "Атлетико М", "Башакшехир": "Истанбул", "Трабзонспор": "Трабзон",
    "Астон Вилла": "А. Вилла", "Ноттингем": "Ноттингем", "Вест Бром": "В. Бромвич"
}

ELITE_KEYWORDS = {
    "Реал Мадрид": 0.45, "Ман Сити": 0.45, "Бавария": 0.42, "Барселона": 0.40,
    "Ливерпуль": 0.40, "Арсенал": 0.38, "Интер": 0.36, "ПСЖ": 0.35, "Байер": 0.30,
    "Атлетико": 0.28, "Ювентус": 0.26, "Наполи": 0.26, "Челси": 0.24, "Милан": 0.22,
    "Боруссия Д": 0.22, "Спортинг": 0.28, "Бенфика": 0.26, "Порту": 0.25,
    "ПСВ": 0.28, "Аякс": 0.24, "Галатасарай": 0.26, "Фенербахче": 0.25,
    "Зенит": 0.30, "Краснодар": 0.28, "ЦСКА": 0.26, "Спартак": 0.26, "Локомотив": 0.24,
    "Франция": 0.40, "Испания": 0.42, "Англия": 0.38, "Германия": 0.38, "Португалия": 0.36
}

def translate_team(name: str) -> str:
    return TEAM_TRANSLATIONS.get(name, name)

def short_team_btn(ru_name: str) -> str:
    """Сокращает длинные названия команд на кнопках для идеального отображения со смартфона"""
    s = SHORT_BTN_NAMES.get(ru_name, ru_name)
    return s[:12] if len(s) > 13 else s

def get_elite_bonus(ru_name: str) -> float:
    for kw, val in ELITE_KEYWORDS.items():
        if kw in ru_name:
            return val
    return 0.0

def now_msk() -> datetime:
    return datetime.now(MSK_TZ)

def get_current_week_key() -> str:
    dt = now_msk()
    shifted = dt - timedelta(days=4, hours=10)
    iso_year, iso_week, _ = shifted.isocalendar()
    return f"se_{iso_year}_w{iso_week}"

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
    return f"{random.choice(FOOTBALL_NICK_BASES)}_{random.randint(7, 99)}"

def validate_custom_nickname(raw_nick: str) -> tuple[bool, str]:
    nick = raw_nick.strip()
    if len(nick) < 3 or len(nick) > 16:
        return False, "Длина никнейма должна быть от 3 до 16 символов."
    if not re.match(r"^[a-zA-Zа-яА-ЯёЁ0-9_\-\s]+$", nick):
        return False, "Разрешены только буквы, цифры, пробел, дефис и _."
    low = nick.lower()
    for bad in FORBIDDEN_NICK_WORDS:
        if bad in low:
            return False, "Этот никнейм зарезервирован системой."
    return True, nick

def get_user_fut_buffs(user: dict) -> dict:
    try:
        cards = json.loads(user.get("fut_cards") or "{}")
    except Exception:
        cards = {}
    fw_id = cards.get("FW", "")
    gk_id = cards.get("GK", "")
    co_id = cards.get("COACH", "")

    fw_val = FUT_CARDS[fw_id]["val"] if fw_id in FUT_CARDS else 0
    gk_val = FUT_CARDS[gk_id]["val"] if gk_id in FUT_CARDS else 0
    co_val = FUT_CARDS[co_id]["val"] if co_id in FUT_CARDS else 0.0

    lab_lvl = int(user.get("lab_level") or 1)
    lab_bonus = LAB_LEVELS.get(lab_lvl, LAB_LEVELS[1])["odd_bonus"]

    return {
        "fw_card": FUT_CARDS.get(fw_id),
        "gk_card": FUT_CARDS.get(gk_id),
        "co_card": FUT_CARDS.get(co_id),
        "totals_profit_pct": fw_val,
        "loss_cashback_pct": gk_val,
        "express_odd_boost": co_val,
        "lab_odd_boost": lab_bonus
    }

# ================= ДОСРОЧНЫЙ LIVE-РАСЧЕТ И ФОРМАТИРОВАНИЕ СОБЫТИЙ =================
def check_early_live_win(pick_code: str, home_score: int, away_score: int) -> bool:
    code = pick_code.lower()
    total_goals = home_score + away_score

    if code == "btts":
        return home_score >= 1 and away_score >= 1
    elif code == "tb15":
        return total_goals >= 2
    elif code == "tb25":
        return total_goals >= 3
    elif code.startswith("itb1_"):
        try:
            line = float(code.split("_")[1])
            return home_score > line
        except Exception:
            return False
    elif code.startswith("itb2_"):
        try:
            line = float(code.split("_")[1])
            return away_score > line
        except Exception:
            return False
    elif code.startswith("tb_"):
        try:
            line = float(code.split("_")[1])
            return total_goals > line
        except Exception:
            return False
    return False

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
                early_tag = " ⚡Досрочно!" if leg.get("early_win") else ""
                status_tag = f"✅ <b>{f_score}</b> (Зашло{early_tag})"
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
            early_tag = " (⚡ Досрочный расчет в Live!)" if lg.get("early_win") else ""
            icon = f"✅{early_tag}" if st == "win" else ("🔄 Возврат" if st == "push" else "❌")
            score_part = f"\n🏁 Счет расчета: <b><code>{f_score}</code></b> {icon}"
        elif live_sc:
            score_part = f"\n🔴 Идет матч: <b><code>{live_sc}</code></b>"
        else:
            score_part = ""
    else:
        score_part = f"\n🏁 Счет: <b><code>{bet['score_result']}</code></b>" if (with_result and bet.get("score_result")) else ""

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
            "p1": f"П1 ({t1})", "x": "Х (Ничья)", "p2": f"П2 ({t2})",
            "1x": f"1Х ({t1} не проиграет)", "x2": f"Х2 ({t2} не проиграет)",
            "f10": f"Фора 1 (0) — {t1}", "f20": f"Фора 2 (0) — {t2}",
            "btts": "Обе забьют: Да", "btts_no": "Обе забьют: Нет"
        }
        return {"pick_code": code, "label": labels[code], "odds": odds[code], "prob": probs.get(code, 50.0)}

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
        calc_odd = round(max(1.08, min(19.0, 1.0 / (effective_win_prob * 1.045))), 2)
        line_str = f"{int_line}.0" if is_integer_line else f"{line:.1f}"
        refund_note = " (возврат)" if is_integer_line else ""
        return {
            "pick_code": f"{direction}_{line_str}",
            "label": f"{label_prefix} {line_str}{refund_note}",
            "odds": calc_odd,
            "prob": round(effective_win_prob * 100, 1)
        }
    return None

# ================= ПОЛУЧЕНИЕ ПРЕДСТОЯЩИХ И LIVE-МАТЧЕЙ (ESPN API) =================
SCHEDULE_CACHE = {"data": {}, "updated_at": 0}
CACHE_TTL = 300  # Обновление кэша каждые 5 минут для актуальности LIVE-счета

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
        icons = ["✅В" if ch == "W" else ("➖Н" if ch == "D" else "❌П") for ch in form_raw[-5:] if ch in "WDL"]
        form_visual = " ".join(icons) if icons else "н/д"
    elif games_played > 0:
        seq = (["✅В"] * min(5, round((w / games_played) * 5)) +
               ["➖Н"] * min(5, round((d / games_played) * 5)) +
               ["❌П"] * 5)[:5]
        form_visual = " ".join(seq)
    else:
        form_visual = "📊 Старт сезона"

    return {"ppg": base_ppg, "record_str": record_str, "points": w * 3 + d, "games": games_played, "form_visual": form_visual}

def compute_match_metrics_and_odds(comp_obj: dict, home_comp: dict, away_comp: dict, h_name: str, a_name: str):
    h_stats = parse_team_stats_detail(home_comp, h_name)
    a_stats = parse_team_stats_detail(away_comp, a_name)
    h_strength = h_stats["ppg"] + 0.22
    a_strength = a_stats["ppg"]
    diff = h_strength - a_strength

    lam_h = round(max(0.65, min(2.65, 1.38 + (h_strength - 1.50) * 0.62 - (a_strength - 1.45) * 0.22)), 2)
    lam_a = round(max(0.50, min(2.35, 1.12 + (a_strength - 1.45) * 0.58 - (h_strength - 1.50) * 0.22)), 2)
    exp_goals = round(lam_h + lam_a, 2)

    best_score, best_p = "1:1", 0.0
    for gh in range(5):
        for ga in range(5):
            p = poisson_pmf(gh, lam_h) * poisson_pmf(ga, lam_a)
            if p > best_p:
                best_p, best_score = p, f"{gh}:{ga}"

    p1_odd, x_odd, p2_odd = None, None, None
    try:
        for o in (comp_obj.get("odds") or []):
            if not isinstance(o, dict):
                continue
            h_dict = o.get("homeTeamOdds") if isinstance(o.get("homeTeamOdds"), dict) else {}
            a_dict = o.get("awayTeamOdds") if isinstance(o.get("awayTeamOdds"), dict) else {}
            d_raw = o.get("drawOdds")
            d_val = d_raw.get("moneyLine") if isinstance(d_raw, dict) else d_raw
            h_o, a_o, d_o = parse_american_odd(h_dict.get("moneyLine")), parse_american_odd(a_dict.get("moneyLine")), parse_american_odd(d_val)
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
        "1x": odd_1x, "x2": odd_x2, "f10": odd_f10, "f20": odd_f20,
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
        "1x": round(p1 + x, 1), "x2": round(p2 + x, 1),
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
    """Парсит как предстоящие матчи, так и матчи, идущие в ПРЯМОМ ЭФИРЕ (state == 'in')"""
    try:
        if not isinstance(ev, dict):
            return None
        comps = ev.get("competitions") or []
        comp = comps[0] if (comps and isinstance(comps[0], dict)) else {}

        st_obj = (comp.get("status") or ev.get("status") or {}).get("type") or {}
        status_state = str(st_obj.get("state", "pre")).lower()
        completed = bool(st_obj.get("completed", False))

        # Отсекаем только завершенные матчи; LIVE-матчи ('in') оставляем в расписании!
        if completed or status_state == "post":
            return None

        is_live = (status_state == "in")
        live_detail = str(st_obj.get("shortDetail") or "LIVE")

        raw_date = str(ev.get("date") or comp.get("date") or "")
        if len(raw_date) < 16:
            return None
        dt_utc = datetime.strptime(raw_date[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK_TZ)
        start_ts = int(dt_msk.timestamp())

        # Если матч не в LIVE и время старта уже прошло более 15 минут назад — пропускаем
        if not is_live and start_ts <= now_ts:
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

        h_score = int(home_c.get("score") or 0)
        a_score = int(away_c.get("score") or 0)
        live_score_str = f"{h_score}:{a_score}"

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

        btn_teams = f"{short_team_btn(h_name)} — {short_team_btn(a_name)}"

        return {
            "event_id": ev_id,
            "league_key": league_key,
            "league_slug": cfg["slug"],
            "teams": f"{h_name} — {a_name}",
            "btn_teams": btn_teams,
            "home_team": h_name,
            "away_team": a_name,
            "is_live": is_live,
            "live_score": live_score_str,
            "live_detail": live_detail,
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
    except Exception:
        return None

async def fetch_league_schedule(session: aiohttp.ClientSession, league_key: str, cfg: dict, now_dt: datetime, now_ts: int) -> tuple[str, dict]:
    all_events = {}
    months_to_check = [now_dt.strftime("%Y%m")]
    next_month_dt = now_dt + timedelta(days=20)
    if next_month_dt.strftime("%Y%m") not in months_to_check:
        months_to_check.append(next_month_dt.strftime("%Y%m"))

    # Запрашиваем расписание по месяцам + текущий день для точного перехвата LIVE-матчей
    urls = [
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{cfg['slug']}/scoreboard?dates={ now_dt.strftime('%Y%m%d') }",
        *[f"https://site.api.espn.com/apis/site/v2/sports/soccer/{cfg['slug']}/scoreboard?dates={ym}&limit=200" for ym in months_to_check]
    ]

    for url in urls:
        try:
            async with session.get(url, headers=HTTP_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for ev in (data.get("events") or []):
                        parsed = parse_event_object(ev, league_key, cfg, now_ts)
                        if parsed:
                            all_events[parsed["event_id"]] = parsed
        except Exception:
            pass

    # Сортируем: сначала LIVE-матчи, затем по времени начала
    sorted_events = sorted(all_events.values(), key=lambda x: (0 if x.get("is_live") else 1, x["start_ts"]))
    two_weeks_limit = now_ts + (14 * 86400)
    seven_days_limit = now_ts + (7 * 86400)

    matches_14d = {m["event_id"]: m for m in sorted_events if m.get("is_live") or m["start_ts"] <= two_weeks_limit}
    matches_7d = {m["event_id"]: m for m in sorted_events if m.get("is_live") or m["start_ts"] <= seven_days_limit}

    if matches_7d:
        return league_key, {
            "title": cfg["title"],
            "slug": cfg["slug"],
            "matches": matches_7d,
            "has_2w_matches": True,
            "extended": False
        }
    elif matches_14d:
        return league_key, {
            "title": cfg["title"],
            "slug": cfg["slug"],
            "matches": matches_14d,
            "has_2w_matches": True,
            "extended": True
        }

    # Если в ближайшие 14 дней матчей нет (актуально для фильтра Других лиг)
    next_round_matches = {m["event_id"]: m for m in sorted_events[:12]}
    return league_key, {
        "title": cfg["title"],
        "slug": cfg["slug"],
        "matches": next_round_matches,
        "has_2w_matches": False,
        "extended": True
    }

async def get_real_matches(force_refresh: bool = False) -> dict:
    now_dt = now_msk()
    now_ts = int(now_dt.timestamp())

    if not force_refresh and SCHEDULE_CACHE["data"] and (now_ts - SCHEDULE_CACHE["updated_at"] < CACHE_TTL):
        filtered = {}
        for l_k, l_v in SCHEDULE_CACHE["data"].items():
            active_m = {
                m_id: m for m_id, m in l_v["matches"].items()
                if m.get("is_live") or m["start_ts"] > now_ts
            }
            filtered[l_k] = {
                "title": l_v["title"],
                "slug": l_v["slug"],
                "matches": active_m,
                "has_2w_matches": l_v.get("has_2w_matches", len(active_m) > 0),
                "extended": l_v.get("extended", False)
            }
        if any(len(v["matches"]) > 0 for v in filtered.values()):
            return filtered

    result_db = {}
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_league_schedule(session, l_key, cfg, now_dt, now_ts) for l_key, cfg in LEAGUES_CONFIG.items()]
        for l_key, l_data in await asyncio.gather(*tasks):
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
                comps = (data.get("header") or {}).get("competitions") or []
                if comps and isinstance(comps[0], dict):
                    comp = comps[0]
                    st_type = (comp.get("status") or {}).get("type") or {}
                    state = str(st_type.get("state", "pre")).lower()
                    completed = bool(st_type.get("completed", False))
                    detail = str(st_type.get("shortDetail") or "")
                    competitors = comp.get("competitors") or []
                    home_c = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "home"), competitors[0] if competitors else {})
                    away_c = next((c for c in competitors if isinstance(c, dict) and c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})
                    h_score, a_score = int(home_c.get("score") or 0), int(away_c.get("score") or 0)
                    return {
                        "ok": True, "state": state, "completed": completed or (state == "post"),
                        "home_score": h_score, "away_score": a_score, "score_str": f"{h_score}:{a_score}", "detail": detail
                    }
    except Exception:
        pass
    return {"ok": False, "state": "unknown", "completed": False}
    # ================= УНИВЕРСАЛЬНАЯ БАЗА ДАННЫХ (PostgreSQL + SQLite) =================
class Database:
    def __init__(self):
        self.use_pg = bool(DATABASE_URL)
        self.pg_pool = None
        self.sqlite_path = "football_bot.db"

    def _q(self, query: str) -> str:
        if self.use_pg:
            return query
        return re.sub(r"\$\d+", "?", query)

    async def exec(self, query: str, *args):
        q = self._q(query)
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(q, *args)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute(q, args)
                await db.commit()

    async def fetchrow(self, query: str, *args) -> dict | None:
        q = self._q(query)
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(q, *args)
                return dict(row) if row else None
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(q, args) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None

    async def fetch(self, query: str, *args) -> list[dict]:
        q = self._q(query)
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(q, *args)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(q, args) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def fetchval(self, query: str, *args):
        q = self._q(query)
        if self.use_pg:
            async with self.pg_pool.acquire() as conn:
                return await conn.fetchval(q, *args)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                async with db.execute(q, args) as cur:
                    row = await cur.fetchone()
                    return row[0] if row else None

    async def init(self):
        if self.use_pg:
            import asyncpg
            self.pg_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
            id_serial = "SERIAL PRIMARY KEY"
            bigint_t = "BIGINT"
            real_t = "DOUBLE PRECISION"
        else:
            id_serial = "INTEGER PRIMARY KEY AUTOINCREMENT"
            bigint_t = "INTEGER"
            real_t = "REAL"

        await self.exec(f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id {bigint_t} PRIMARY KEY,
                username TEXT,
                balance {real_t} DEFAULT 1000.0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                profit {real_t} DEFAULT 0.0,
                is_vip INTEGER DEFAULT 0,
                last_bonus TEXT DEFAULT '',
                referred_by {bigint_t} DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                favorite_club TEXT DEFAULT '',
                achievements TEXT DEFAULT '[]',
                streak INTEGER DEFAULT 0,
                totals_wins INTEGER DEFAULT 0,
                last_spin TEXT DEFAULT '',
                active_booster TEXT DEFAULT '',
                is_incognito INTEGER DEFAULT 0,
                stadium_level INTEGER DEFAULT 1,
                last_stadium_claim TEXT DEFAULT '',
                lab_level INTEGER DEFAULT 1,
                fut_cards TEXT DEFAULT '{{}}',
                pvp_wins INTEGER DEFAULT 0
            )
        """)
        await self.exec(f"""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id {id_serial},
                user_id {bigint_t},
                match_title TEXT,
                pick TEXT,
                amount INTEGER,
                odds {real_t},
                status TEXT DEFAULT 'pending',
                bet_type TEXT DEFAULT 'single',
                win_prob {real_t} DEFAULT 50.0,
                settle_ts {bigint_t} DEFAULT 0,
                created_at TEXT DEFAULT '',
                score_result TEXT DEFAULT '',
                legs_json TEXT DEFAULT '[]',
                booster_used TEXT DEFAULT '',
                is_all_in INTEGER DEFAULT 0,
                is_fav_club INTEGER DEFAULT 0
            )
        """)
        await self.exec("""
            CREATE TABLE IF NOT EXISTS superexpress_rounds (
                round_key TEXT PRIMARY KEY,
                matches_json TEXT,
                created_at TEXT DEFAULT ''
            )
        """)
        await self.exec(f"""
            CREATE TABLE IF NOT EXISTS superexpress_entries (
                entry_id {id_serial},
                round_key TEXT,
                user_id {bigint_t},
                picks_json TEXT,
                status TEXT DEFAULT 'pending',
                guessed INTEGER DEFAULT 0,
                payout INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ''
            )
        """)
        await self.exec(f"""
            CREATE TABLE IF NOT EXISTS pvp_duels (
                duel_id {id_serial},
                creator_id {bigint_t},
                creator_name TEXT,
                target_id {bigint_t} DEFAULT 0,
                stake INTEGER,
                kick_dir TEXT,
                save_dir TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT DEFAULT ''
            )
        """)
        await self.exec(f"""
            CREATE TABLE IF NOT EXISTS black_market (
                day_key TEXT PRIMARY KEY,
                lot_id TEXT,
                highest_bid INTEGER DEFAULT 3000,
                leader_id {bigint_t} DEFAULT 0,
                leader_name TEXT DEFAULT 'Нет ставок',
                status TEXT DEFAULT 'open'
            )
        """)

        user_cols = [
            f"referred_by {bigint_t} DEFAULT 0", "referrals_count INTEGER DEFAULT 0",
            "favorite_club TEXT DEFAULT ''", "achievements TEXT DEFAULT '[]'",
            "streak INTEGER DEFAULT 0", "totals_wins INTEGER DEFAULT 0",
            "last_spin TEXT DEFAULT ''", "active_booster TEXT DEFAULT ''",
            "is_incognito INTEGER DEFAULT 0", "stadium_level INTEGER DEFAULT 1",
            "last_stadium_claim TEXT DEFAULT ''", "lab_level INTEGER DEFAULT 1",
            "fut_cards TEXT DEFAULT '{}'", "pvp_wins INTEGER DEFAULT 0"
        ]
        for col in user_cols:
            try:
                await self.exec(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass

        bet_cols = [
            "bet_type TEXT DEFAULT 'single'", f"win_prob {real_t} DEFAULT 50.0",
            f"settle_ts {bigint_t} DEFAULT 0", "created_at TEXT DEFAULT ''",
            "score_result TEXT DEFAULT ''", "legs_json TEXT DEFAULT '[]'",
            "booster_used TEXT DEFAULT ''", "is_all_in INTEGER DEFAULT 0", "is_fav_club INTEGER DEFAULT 0"
        ]
        for col in bet_cols:
            try:
                await self.exec(f"ALTER TABLE bets ADD COLUMN {col}")
            except Exception:
                pass

        try:
            await self.exec(f"ALTER TABLE pvp_duels ADD COLUMN target_id {bigint_t} DEFAULT 0")
        except Exception:
            pass

    async def get_or_create_user(self, user_id: int, username: str = "", referrer_id: int = 0) -> tuple[dict, bool]:
        uname = username or f"Capper_{str(user_id)[-4:]}"
        rewarded = False
        row = await self.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not row:
            valid_ref = 0
            if referrer_id and referrer_id != user_id:
                ref_exists = await self.fetchrow("SELECT user_id FROM users WHERE user_id = $1", referrer_id)
                if ref_exists:
                    valid_ref = referrer_id

            start_bal = 1500.0 if valid_ref else 1000.0
            await self.exec(
                "INSERT INTO users (user_id, username, balance, referred_by) VALUES ($1, $2, $3, $4)",
                user_id, uname, start_bal, valid_ref
            )
            if valid_ref:
                await self.exec(
                    "UPDATE users SET balance = balance + 500.0, referrals_count = referrals_count + 1 WHERE user_id = $1",
                    valid_ref
                )
                rewarded = True
            row = await self.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return row, rewarded

    async def get_user(self, user_id: int, username: str = "") -> dict:
        u, _ = await self.get_or_create_user(user_id, username)
        return u

    async def find_user_by_query(self, query_str: str) -> dict | None:
        q = query_str.strip().lstrip("@")
        if q.isdigit():
            row = await self.fetchrow("SELECT * FROM users WHERE user_id = $1", int(q))
            if row:
                return row
        return await self.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", q)

    async def search_users_admin(self, query_str: str) -> list[dict]:
        """Умный поиск игроков для Админа: ищет и по точному ID, и по части никнейма"""
        q = query_str.strip().lstrip("@")
        if q.isdigit():
            row = await self.fetchrow("SELECT * FROM users WHERE user_id = $1", int(q))
            if row:
                return [row]
        like_pat = f"%{q.lower()}%"
        return await self.fetch("SELECT * FROM users WHERE LOWER(username) LIKE $1 ORDER BY balance DESC LIMIT 10", like_pat)

    async def get_users_list_admin(self, limit: int = 15) -> list[dict]:
        """Возвращает список игроков с их ID для быстрого копирования в админке"""
        return await self.fetch("SELECT * FROM users ORDER BY balance DESC LIMIT $1", limit)

    async def toggle_user_vip_admin(self, target_uid: int) -> int:
        u = await self.fetchrow("SELECT * FROM users WHERE user_id = $1", target_uid)
        if not u:
            return -1
        new_vip = 0 if int(u.get("is_vip") or 0) == 1 else 1
        await self.exec("UPDATE users SET is_vip = $1 WHERE user_id = $2", new_vip, target_uid)
        return new_vip

    async def reset_user_cooldowns_admin(self, target_uid: int) -> bool:
        u = await self.fetchrow("SELECT user_id FROM users WHERE user_id = $1", target_uid)
        if not u:
            return False
        await self.exec(
            "UPDATE users SET last_bonus = '', last_spin = '', last_stadium_claim = '' WHERE user_id = $1",
            target_uid
        )
        return True

    async def update_nickname(self, user_id: int, new_nick: str):
        await self.exec("UPDATE users SET username = $1 WHERE user_id = $2", new_nick, user_id)

    async def toggle_user_incognito(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        new_val = 0 if int(user.get("is_incognito") or 0) == 1 else 1
        await self.exec("UPDATE users SET is_incognito = $1 WHERE user_id = $2", new_val, user_id)
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
        cfg = ACHIEVEMENTS_CONFIG[ach_key]
        await self.exec(
            "UPDATE users SET achievements = $1, balance = balance + $2, profit = profit + $2 WHERE user_id = $3",
            ach_json, float(cfg["reward"]), user_id
        )
        try:
            await bot.send_message(
                user_id,
                f"🎖 <b>НОВОЕ ДОСТИЖЕНИЕ!</b>\n\n<blockquote>🏆 <b>{cfg['title']}</b>\n📋 <i>{cfg['desc']}</i>\n💰 Награда: <b><code>+{cfg['reward']} FC</code></b>!</blockquote>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return True

    async def set_favorite_club(self, user_id: int, club_name: str):
        await self.exec("UPDATE users SET favorite_club = $1 WHERE user_id = $2", club_name, user_id)

    # Методы Футбольной Империи, Стадионов и FUT
    async def claim_stadium_income(self, user_id: int) -> tuple[bool, int, str]:
        today_str = now_msk().strftime("%Y-%m-%d")
        user = await self.get_user(user_id)
        lvl = int(user.get("stadium_level") or 1)
        st_cfg = STADIUM_LEVELS.get(lvl, STADIUM_LEVELS[1])
        if user.get("last_stadium_claim") == today_str:
            return False, 0, st_cfg["name"]

        inc = st_cfg["income"]
        await self.exec(
            "UPDATE users SET balance = balance + $1, last_stadium_claim = $2 WHERE user_id = $3",
            float(inc), today_str, user_id
        )
        return True, inc, st_cfg["name"]

    async def upgrade_empire_building(self, user_id: int, b_type: str) -> dict:
        user = await self.get_user(user_id)
        if b_type == "stadium":
            cur_lvl = int(user.get("stadium_level") or 1)
            if cur_lvl >= 10:
                return {"ok": False, "error": "У тебя уже построена максимальная арена!"}
            next_lvl = cur_lvl + 1
            cost = STADIUM_LEVELS[next_lvl]["price"]
            if user["balance"] < cost:
                return {"ok": False, "error": f"Недостаточно средств! Для «{STADIUM_LEVELS[next_lvl]['name']}» нужно {cost} FC."}
            await self.exec(
                "UPDATE users SET balance = balance - $1, stadium_level = $2 WHERE user_id = $3",
                float(cost), next_lvl, user_id
            )
            return {
                "ok": True,
                "new_lvl": next_lvl,
                "name": STADIUM_LEVELS[next_lvl]["name"],
                "income": STADIUM_LEVELS[next_lvl]["income"]
            }
        else:
            cur_lvl = int(user.get("lab_level") or 1)
            if cur_lvl >= 5:
                return {"ok": False, "error": "ИИ-Лаборатория уже максимального 5-го уровня!"}
            next_lvl = cur_lvl + 1
            cost = LAB_LEVELS[next_lvl]["price"]
            if user["balance"] < cost:
                return {"ok": False, "error": f"Недостаточно средств! Нужно {cost} FC."}
            await self.exec(
                "UPDATE users SET balance = balance - $1, lab_level = $2 WHERE user_id = $3",
                float(cost), next_lvl, user_id
            )
            return {"ok": True, "new_lvl": next_lvl, "name": LAB_LEVELS[next_lvl]["name"]}

    async def open_fut_pack_db(self, user_id: int, cost: int, card_id: str) -> dict:
        user = await self.get_user(user_id)
        if user["balance"] < cost:
            return {"ok": False, "error": f"Недостаточно средств! Нужно {cost} FC."}

        card = FUT_CARDS[card_id]
        role = card["role"]
        try:
            equipped = json.loads(user.get("fut_cards") or "{}")
        except Exception:
            equipped = {}

        cur_id = equipped.get(role, "")
        cur_card = FUT_CARDS.get(cur_id)
        cashback = 0

        if not cur_card or card["val"] > cur_card["val"]:
            equipped[role] = card_id
            status_note = "✅ <b>Карточка сразу встала в твой основной состав!</b>"
        else:
            cashback = int(cost * 0.45)
            status_note = f"♻️ На этой позиции уже есть не менее сильный игрок. Дубликат продан за <b>+{cashback} FC</b>!"

        new_bal = round(user["balance"] - cost + cashback, 1)
        await self.exec(
            "UPDATE users SET balance = $1, fut_cards = $2 WHERE user_id = $3",
            new_bal, json.dumps(equipped, ensure_ascii=False), user_id
        )
        return {"ok": True, "card": card, "new_balance": new_bal, "status_note": status_note}

    # Методы Черного рынка (Аукцион)
    async def get_or_rotate_black_market(self) -> dict:
        today_str = now_msk().strftime("%Y-%m-%d")
        old_open = await self.fetch("SELECT * FROM black_market WHERE status = 'open' AND day_key != $1", today_str)
        for lot in old_open:
            await self.exec("UPDATE black_market SET status = 'closed' WHERE day_key = $1", lot["day_key"])
            winner_id = int(lot.get("leader_id") or 0)
            lot_card_id = lot.get("lot_id")
            if winner_id and lot_card_id in FUT_CARDS:
                w_user = await self.get_user(winner_id)
                try:
                    eq = json.loads(w_user.get("fut_cards") or "{}")
                except Exception:
                    eq = {}
                c_obj = FUT_CARDS[lot_card_id]
                eq[c_obj["role"]] = lot_card_id
                await self.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", json.dumps(eq, ensure_ascii=False), winner_id)
                try:
                    await bot.send_message(
                        winner_id,
                        f"🔨 <b>АУКЦИОН ЗАВЕРШЕН — ТЫ ПОБЕДИЛ!</b>\n\n"
                        f"<blockquote>Эксклюзивный лот <b>{c_obj['name']}</b> ({c_obj['desc']}) добавлен в твой основной состав!</blockquote>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        cur = await self.fetchrow("SELECT * FROM black_market WHERE day_key = $1", today_str)
        if not cur:
            day_idx = int(now_msk().strftime("%j")) % len(BLACK_MARKET_ROTATION)
            lot_id = BLACK_MARKET_ROTATION[day_idx]
            await self.exec(
                "INSERT INTO black_market (day_key, lot_id, highest_bid, leader_id, leader_name, status) VALUES ($1, $2, 3000, 0, 'Нет ставок', 'open')",
                today_str, lot_id
            )
            cur = await self.fetchrow("SELECT * FROM black_market WHERE day_key = $1", today_str)
        return cur

    async def place_black_market_bid(self, user_id: int, bid_amount: int) -> dict:
        lot = await self.get_or_rotate_black_market()
        user = await self.get_user(user_id)
        min_next = int(lot["highest_bid"]) + 500 if int(lot["leader_id"]) != 0 else int(lot["highest_bid"])

        if bid_amount < min_next:
            return {"ok": False, "error": f"Минимальная ставка — {min_next} FC!"}
        if user["balance"] < bid_amount:
            return {"ok": False, "error": f"Недостаточно средств! Баланс: {round(user['balance'], 1)} FC."}

        prev_leader = int(lot.get("leader_id") or 0)
        prev_bid = int(lot.get("highest_bid") or 0)

        await self.exec("UPDATE users SET balance = balance - $1 WHERE user_id = $2", float(bid_amount), user_id)

        if prev_leader != 0:
            await self.exec("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(prev_bid), prev_leader)
            if prev_leader != user_id:
                try:
                    await bot.send_message(
                        prev_leader,
                        f"⚠️ <b>ТВОЮ СТАВКУ НА ЧЕРНОМ РЫНКЕ ПЕРЕБИЛИ!</b>\n\n"
                        f"Новая ставка: <b>{bid_amount} FC</b>. Твои <code>+{prev_bid} FC</code> возвращены на баланс.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        await self.exec(
            "UPDATE black_market SET highest_bid = $1, leader_id = $2, leader_name = $3 WHERE day_key = $4",
            bid_amount, user_id, user["username"], lot["day_key"]
        )
        return {"ok": True, "bid": bid_amount}

    # Методы PvP-Пенальти
    async def create_pvp_duel(self, user_id: int, stake: int, kick_dir: str, save_dir: str, target_id: int = 0) -> dict:
        user = await self.get_user(user_id)
        if stake < 50:
            return {"ok": False, "error": "Минимальная ставка для PvP — 50 FC!"}
        if user["balance"] < stake:
            return {"ok": False, "error": f"Недостаточно средств! Баланс: {round(user['balance'], 1)} FC."}

        if target_id == 0:
            existing_open = await self.fetchval(
                "SELECT COUNT(*) FROM pvp_duels WHERE creator_id = $1 AND target_id = 0 AND status = 'open'",
                user_id
            )
            if existing_open and int(existing_open) >= 2:
                return {"ok": False, "error": "У тебя уже есть 2 активных вызова в общем лобби! Дождись соперника или отмени старый вызов."}

        await self.exec("UPDATE users SET balance = balance - $1 WHERE user_id = $2", float(stake), user_id)
        created_str = now_msk().strftime("%H:%M")
        if self.use_pg:
            duel_id = await self.fetchval(
                "INSERT INTO pvp_duels (creator_id, creator_name, target_id, stake, kick_dir, save_dir, status, created_at) VALUES ($1, $2, $3, $4, $5, $6, 'open', $7) RETURNING duel_id",
                user_id, user["username"], target_id, stake, kick_dir, save_dir, created_str
            )
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cur = await db.execute(
                    "INSERT INTO pvp_duels (creator_id, creator_name, target_id, stake, kick_dir, save_dir, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
                    (user_id, user["username"], target_id, stake, kick_dir, save_dir, created_str)
                )
                duel_id = cur.lastrowid
                await db.commit()
        return {"ok": True, "duel_id": duel_id}

    async def get_open_pvp_duels(self, viewer_id: int = 0) -> list[dict]:
        return await self.fetch(
            "SELECT * FROM pvp_duels WHERE status = 'open' AND (target_id = 0 OR target_id = $1 OR creator_id = $1) ORDER BY CASE WHEN target_id = $1 THEN 0 ELSE 1 END, duel_id DESC LIMIT 8",
            viewer_id
        )

    async def get_pvp_duel(self, duel_id: int) -> dict | None:
        return await self.fetchrow("SELECT * FROM pvp_duels WHERE duel_id = $1", duel_id)

    async def cancel_pvp_duel(self, duel_id: int, user_id: int) -> dict | None:
        d = await self.get_pvp_duel(duel_id)
        if not d or d["status"] != "open" or (d["creator_id"] != user_id and d.get("target_id") != user_id):
            return None
        await self.exec("UPDATE pvp_duels SET status = 'cancelled' WHERE duel_id = $1", duel_id)
        await self.exec("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(d["stake"]), d["creator_id"])
        return d

    async def spin_roulette_db(self, user_id: int, coin_win: int, booster_code: str, is_respin: bool) -> dict:
        today_str = "" if is_respin else now_msk().strftime("%Y-%m-%d")
        user = await self.get_user(user_id)
        new_bal = round(user["balance"] + coin_win, 1)
        new_booster = booster_code if booster_code else user.get("active_booster", "")
        await self.exec(
            "UPDATE users SET balance = $1, last_spin = $2, active_booster = $3 WHERE user_id = $4",
            new_bal, today_str, new_booster, user_id
        )
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
        await self.exec("UPDATE users SET balance = balance + $1, last_bonus = $2 WHERE user_id = $3", float(bonus), today_str, user_id)
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

        buffs = get_user_fut_buffs(user)
        final_odds = round(odds + buffs["lab_odd_boost"], 2)
        if bet_type == "express" and buffs["express_odd_boost"] > 0:
            final_odds = round(final_odds + buffs["express_odd_boost"], 2)

        active_booster = user.get("active_booster") or ""
        booster_used = ""
        if active_booster == "boost035":
            final_odds = round(final_odds + 0.35, 2)
            booster_used = "boost035"
        elif active_booster == "insure50":
            booster_used = "insure50"

        new_balance = round(user["balance"] - amount, 1)
        created_str = now_msk().strftime("%d.%m %H:%M")

        await self.exec("UPDATE users SET balance = $1, active_booster = '' WHERE user_id = $2", new_balance, user_id)

        if self.use_pg:
            bet_id = await self.fetchval("""
                INSERT INTO bets (
                    user_id, match_title, pick, amount, odds, status, bet_type,
                    win_prob, settle_ts, created_at, legs_json, booster_used, is_all_in, is_fav_club
                ) VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8, $9, $10, $11, $12, $13) RETURNING bet_id
            """, user_id, match_title, pick, amount, final_odds, bet_type, win_prob, settle_ts, created_str, legs_json, booster_used, is_all_in, is_fav_club)
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cur = await db.execute("""
                    INSERT INTO bets (
                        user_id, match_title, pick, amount, odds, status, bet_type,
                        win_prob, settle_ts, created_at, legs_json, booster_used, is_all_in, is_fav_club
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, match_title, pick, amount, final_odds, bet_type, win_prob, settle_ts, created_str, legs_json, booster_used, is_all_in, is_fav_club))
                bet_id = cur.lastrowid
                await db.commit()

        await self.unlock_achievement(user_id, "first_bet")
        if bet_type == "express":
            await self.unlock_achievement(user_id, "first_express")

        return {
            "ok": True, "bet_id": bet_id, "final_odds": final_odds,
            "booster_used": booster_used, "is_fav_club": is_fav_club,
            "new_balance": new_balance, "potential_win": round(amount * final_odds, 1)
        }

    async def update_bet_legs_progress(self, bet_id: int, updated_legs_json: str):
        await self.exec("UPDATE bets SET legs_json = $1 WHERE bet_id = $2", updated_legs_json, bet_id)

    async def get_user_bets(self, user_id: int, active_only: bool = True) -> list:
        if active_only:
            return await self.fetch("SELECT * FROM bets WHERE user_id = $1 AND status = 'pending' ORDER BY bet_id DESC LIMIT 15", user_id)
        return await self.fetch("SELECT * FROM bets WHERE user_id = $1 AND status != 'pending' ORDER BY bet_id DESC LIMIT 15", user_id)

    async def get_bet_by_id(self, bet_id: int, user_id: int) -> dict | None:
        return await self.fetchrow("SELECT * FROM bets WHERE bet_id = $1 AND user_id = $2", bet_id, user_id)

    async def get_all_pending_bets(self) -> list:
        return await self.fetch("SELECT * FROM bets WHERE status = 'pending'")

    async def settle_bet_in_db(self, bet: dict, outcome_status: str, effective_odds: float, score_str: str, updated_legs_json: str | None = None) -> dict:
        user = await self.get_user(bet["user_id"])
        buffs = get_user_fut_buffs(user)
        amount = bet["amount"]
        legs_str = updated_legs_json if updated_legs_json is not None else bet.get("legs_json", "[]")
        booster_used = bet.get("booster_used") or ""
        is_fav_club = int(bet.get("is_fav_club") or 0)
        is_all_in = int(bet.get("is_all_in") or 0)

        cur_streak = int(user.get("streak") or 0)
        cur_totals_wins = int(user.get("totals_wins") or 0)
        fav_bonus = 0.0
        fut_fw_bonus = 0.0
        insured_refund = 0.0

        try:
            legs_list = json.loads(legs_str)
        except Exception:
            legs_list = []
        has_total_leg = any(str(lg.get("pick_code", "")).startswith(("tb", "tm", "itb")) for lg in legs_list)

        if outcome_status == "win":
            base_payout = round(amount * effective_odds, 1)
            net_profit = round(base_payout - amount, 1)
            if is_fav_club and net_profit > 0:
                fav_bonus = round(net_profit * 0.10, 1)
            if has_total_leg and buffs["totals_profit_pct"] > 0 and net_profit > 0:
                fut_fw_bonus = round(net_profit * (buffs["totals_profit_pct"] / 100.0), 1)
            net_profit = round(net_profit + fav_bonus + fut_fw_bonus, 1)
            payout = round(amount + net_profit, 1)
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc = 1, 0
            new_streak = cur_streak + 1
            new_totals_wins = cur_totals_wins + (1 if has_total_leg else 0)

        elif outcome_status == "push":
            payout, net_profit = float(amount), 0.0
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc, new_streak, new_totals_wins = 0, 0, cur_streak, cur_totals_wins

        elif outcome_status == "cashout":
            payout = round(effective_odds, 1)
            net_profit = round(payout - amount, 1)
            new_balance = round(user["balance"] + payout, 1)
            w_inc, l_inc = (1, 0) if net_profit > 0 else (0, 0)
            new_streak, new_totals_wins = cur_streak, cur_totals_wins

        else:
            if booster_used == "insure50":
                insured_refund = round(amount * 0.50, 1)
            elif buffs["loss_cashback_pct"] > 0:
                insured_refund = round(amount * (buffs["loss_cashback_pct"] / 100.0), 1)
            payout = insured_refund
            net_profit = -round(amount - insured_refund, 1)
            new_balance = round(user["balance"] + insured_refund, 1)
            w_inc, l_inc, new_streak, new_totals_wins = 0, 1, 0, cur_totals_wins

        await self.exec(
            "UPDATE bets SET status = $1, score_result = $2, odds = $3, legs_json = $4 WHERE bet_id = $5",
            outcome_status, score_str, round(effective_odds, 2) if outcome_status != "cashout" else bet["odds"], legs_str, bet["bet_id"]
        )
        await self.exec(
            "UPDATE users SET balance = $1, wins = wins + $2, losses = losses + $3, profit = profit + $4, streak = $5, totals_wins = $6 WHERE user_id = $7",
            new_balance, w_inc, l_inc, net_profit, new_streak, new_totals_wins, bet["user_id"]
        )

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
            "payout": payout, "net_profit": net_profit, "new_balance": new_balance,
            "fav_bonus": fav_bonus, "fut_fw_bonus": fut_fw_bonus, "insured_refund": insured_refund
        }

    # Еженедельный фиксированный Суперэкспресс (1 тираж в неделю)
    async def get_or_create_weekly_superexpress(self, db_schedule: dict) -> tuple[str, list]:
        round_key = get_current_week_key()
        row = await self.fetchrow("SELECT * FROM superexpress_rounds WHERE round_key = $1", round_key)
        if row:
            try:
                return round_key, json.loads(row["matches_json"])
            except Exception:
                pass

        all_upcoming = []
        for l_val in db_schedule.values():
            for m in l_val.get("matches", {}).values():
                if not m.get("is_live"):
                    all_upcoming.append({
                        "event_id": m["event_id"],
                        "league_slug": m["league_slug"],
                        "teams": m["teams"],
                        "short_date": m["short_date"],
                        "start_ts": m["start_ts"]
                    })
        all_upcoming.sort(key=lambda x: x["start_ts"])
        selected_6 = all_upcoming[:6]

        if len(selected_6) == 6:
            await self.exec(
                "INSERT INTO superexpress_rounds (round_key, matches_json, created_at) VALUES ($1, $2, $3)",
                round_key, json.dumps(selected_6, ensure_ascii=False), now_msk().strftime("%d.%m.%Y %H:%M")
            )
        return round_key, selected_6

    async def get_superexpress_entry(self, user_id: int, round_key: str) -> dict | None:
        return await self.fetchrow("SELECT * FROM superexpress_entries WHERE user_id = $1 AND round_key = $2", user_id, round_key)

    async def create_superexpress_entry(self, user_id: int, round_key: str, picks_list: list):
        picks_str = json.dumps(picks_list, ensure_ascii=False)
        created_str = now_msk().strftime("%d.%m %H:%M")
        await self.exec(
            "INSERT INTO superexpress_entries (round_key, user_id, picks_json, status, created_at) VALUES ($1, $2, $3, 'pending', $4)",
            round_key, user_id, picks_str, created_str
        )

    async def get_pending_superexpress_entries(self) -> list:
        return await self.fetch("SELECT * FROM superexpress_entries WHERE status = 'pending'")

    async def settle_superexpress_entry(self, entry_id: int, user_id: int, guessed: int, payout: int, updated_picks_json: str):
        await self.exec(
            "UPDATE superexpress_entries SET status = 'settled', guessed = $1, payout = $2, picks_json = $3 WHERE entry_id = $4",
            guessed, payout, updated_picks_json, entry_id
        )
        if payout > 0:
            await self.exec("UPDATE users SET balance = balance + $1, profit = profit + $1 WHERE user_id = $2", float(payout), user_id)

    async def get_leaderboard(self) -> list:
        return await self.fetch(
            "SELECT user_id, username, balance, wins, losses, is_vip, favorite_club, is_incognito FROM users ORDER BY balance DESC LIMIT 10"
        )

    async def get_project_stats(self) -> dict:
        total_u = await self.fetchval("SELECT COUNT(*) FROM users") or 0
        total_b = await self.fetchval("SELECT COUNT(*) FROM bets") or 0
        active_b = await self.fetchval("SELECT COUNT(*) FROM bets WHERE status = 'pending'") or 0
        total_fc = await self.fetchval("SELECT COALESCE(SUM(balance), 0) FROM users") or 0.0
        open_pvp = await self.fetchval("SELECT COUNT(*) FROM pvp_duels WHERE status = 'open'") or 0
        return {
            "users": total_u, "bets": total_b,
            "active_bets": active_b, "total_fc": round(float(total_fc), 1),
            "open_pvp": open_pvp
        }

    async def get_all_user_ids(self) -> list[int]:
        rows = await self.fetch("SELECT user_id FROM users")
        return [r["user_id"] for r in rows]

    async def add_balance_to_user(self, target_uid: int, add_amt: float) -> bool:
        row = await self.fetchrow("SELECT user_id, balance FROM users WHERE user_id = $1", target_uid)
        if not row:
            return False
        new_b = max(0.0, round(float(row["balance"]) + add_amt, 1))
        await self.exec("UPDATE users SET balance = $1 WHERE user_id = $2", new_b, target_uid)
        return True

db_manager = Database()

# ================= СКОРОСТНОЙ МУЛЬТИ-ШЛЮЗ ИИ С КЭШИРОВАНИЕМ =================
async def ask_ai_cached(cache_key: str, prompt: str, system_prompt: str = "Ты элитный футбольный аналитик.", ttl: int = 10800) -> str | None:
    now_ts = int(now_msk().timestamp())
    cached = AI_CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"] < ttl):
        return cached["text"]

    for groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        try:
            resp = await asyncio.wait_for(
                groq_client.chat.completions.create(
                    model=groq_model,
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                    temperature=0.45, max_tokens=360
                ),
                timeout=3.8
            )
            if resp.choices and resp.choices[0].message.content:
                ans = clean_ai_text(resp.choices[0].message.content)
                AI_CACHE[cache_key] = {"text": ans, "ts": now_ts}
                return ans
        except Exception:
            pass

    if GEMINI_API_KEY:
        try:
            resp = await asyncio.wait_for(
                gemini_client.chat.completions.create(
                    model="gemini-2.5-flash",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                    temperature=0.45, max_tokens=380
                ),
                timeout=4.2
            )
            if resp.choices and resp.choices[0].message.content:
                ans = clean_ai_text(resp.choices[0].message.content)
                AI_CACHE[cache_key] = {"text": ans, "ts": now_ts}
                return ans
        except Exception:
            pass
    return None

# ================= ДОСРОЧНЫЙ И ФИНАЛЬНЫЙ РАСЧЕТ СТАВОК В РЕАЛЬНОМ ВРЕМЕНИ =================
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
        return "win" if home_score > away_score else ("push" if home_score == away_score else "loss")
    elif code == "f20":
        return "win" if away_score > home_score else ("push" if home_score == away_score else "loss")
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
        return ("win" if total_goals > line else "loss") if direction == "tb" else ("win" if total_goals < line else "loss")

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
        leg_odd = float(leg.get("odds") or bet["odds"])
        if leg.get("final_status") == "win":
            any_started = True
            multiplier *= leg_odd
            continue

        res = await fetch_real_match_result(session, leg["league_slug"], str(leg["event_id"]))
        if not res["ok"] or res["state"] == "pre":
            multiplier *= 0.94
            continue
        any_started = True
        cur_state = evaluate_leg_result(leg["pick_code"], res["home_score"], res["away_score"])
        if res["completed"] or check_early_live_win(leg["pick_code"], res["home_score"], res["away_score"]):
            if cur_state == "win":
                multiplier *= leg_odd
            elif cur_state == "push":
                multiplier *= 1.0
            else:
                return 0.0
        else:
            multiplier *= (1.0 + (leg_odd - 1.0) * 0.68) if cur_state == "win" else (0.92 if cur_state == "push" else 0.35)

    if not any_started:
        return round(amount * 0.92, 1)
    return min(round(amount * multiplier, 1), round(amount * bet["odds"] * 0.95, 1))

async def check_and_settle_real_bet(session: aiohttp.ClientSession, bet: dict) -> dict:
    try:
        legs = json.loads(bet.get("legs_json") or "[]")
    except Exception:
        legs = []
    if not legs:
        return {"settled": False, "live_summary": "Ожидание данных матча"}

    all_resolved, any_lost, all_pushed, legs_changed = True, False, True, False
    effective_odds = 1.0
    score_parts, live_parts = [], []

    for leg in legs:
        leg_odd = float(leg.get("odds") or bet["odds"])

        if leg.get("final_status") == "win" and leg.get("early_win"):
            effective_odds *= leg_odd
            all_pushed = False
            f_sc = leg.get("final_score", "Досрочно")
            score_parts.append(f_sc if len(legs) == 1 else f"{leg['teams']} {f_sc} (✅⚡)")
            live_parts.append(f"✅⚡ {leg['teams']} — {f_sc} (Досрочно зашло!)")
            continue

        res = await fetch_real_match_result(session, leg["league_slug"], str(leg["event_id"]))
        if not res["ok"]:
            all_resolved = False
            live_parts.append(f"⏳ {leg['teams']} — ожидание")
            continue

        is_early_win = (not res["completed"] and res["state"] == "in" and check_early_live_win(leg["pick_code"], res["home_score"], res["away_score"]))

        if not res["completed"] and not is_early_win:
            all_resolved = False
            if res["state"] == "in":
                live_tag = f"{res['score_str']} ({res['detail']})"
                if leg.get("live_score") != live_tag:
                    leg["live_score"] = live_tag
                    legs_changed = True
                live_parts.append(f"🔴 LIVE: {leg['teams']} — {live_tag}")
            else:
                live_parts.append(f"📅 {leg['teams']} — ожидает начала")
        else:
            st = "win" if is_early_win else evaluate_leg_result(leg["pick_code"], res["home_score"], res["away_score"])
            score_display = f"{res['score_str']} ({res['detail']})" if is_early_win else res["score_str"]

            if leg.get("final_status") != st or leg.get("final_score") != score_display:
                leg["final_score"] = score_display
                leg["final_status"] = st
                if is_early_win:
                    leg["early_win"] = True
                leg.pop("live_score", None)
                legs_changed = True

            if st == "win":
                effective_odds *= leg_odd
                all_pushed = False
                icon = "✅⚡" if is_early_win else "✅"
            elif st == "push":
                icon = "🔄 Возврат"
            else:
                any_lost, all_pushed, icon = True, False, "❌"

            score_parts.append(f"{score_display}" if len(legs) == 1 else f"{leg['teams']} {score_display} ({icon})")
            live_parts.append(f"🏁 {leg['teams']} — {score_display} {icon}")

    updated_legs_str = json.dumps(legs, ensure_ascii=False)

    if all_resolved:
        final_score_str = " | ".join(score_parts)
        outcome_status = "loss" if any_lost else ("push" if all_pushed else "win")
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
    fav_note = f"\n⭐ <b>Бонус клуба (+10%):</b> <code>+{res['fav_bonus']} FC</code>" if res.get("fav_bonus", 0) > 0 else ""
    fw_note = f"\n⚡ <b>Бонус Форварда FUT:</b> <code>+{res['fut_fw_bonus']} FC</code>" if res.get("fut_fw_bonus", 0) > 0 else ""
    ins_note = f"\n🧤 <b>Кэшбэк / Страховка:</b> возвращено <b><code>+{res['insured_refund']} FC</code></b>!" if res.get("insured_refund", 0) > 0 else ""

    if outcome_status == "win":
        msg = (
            f"🎉 <b>СТАВКА СЫГРАЛА! ({type_label})</b>\n"
            f"🎫 <b>Купон #{bet['bet_id']}</b> • Кэф: <b><code>{round(effective_odds, 2)}</code></b>\n\n"
            f"<blockquote>{events_block}</blockquote>\n"
            f"💵 <b>Сумма ставки:</b> <code>{bet['amount']} FC</code>{fav_note}{fw_note}\n"
            f"💰 <b>Выплата:</b> <b><code>+{res['payout']} FC</code></b> <i>(чистыми: +{res['net_profit']} FC)</i>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )
    elif outcome_status == "push":
        msg = (
            f"🔄 <b>ВОЗВРАТ СТАВКИ (РАСХОД • КЭФ 1.00)</b>\n"
            f"🎫 <b>Купон #{bet['bet_id']}</b>\n\n"
            f"<blockquote>{events_block}</blockquote>\n"
            f"💵 <b>Возвращено:</b> <b><code>+{res['payout']} FC</code></b>\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )
    else:
        msg = (
            f"📢 <b>КУПОН РАССЧИТАН ({type_label}) — ❌ НЕ СЫГРАЛ</b>\n"
            f"🎫 <b>Купон #{bet['bet_id']}</b> • Кэф: <code>{bet['odds']}</code>\n\n"
            f"<blockquote>{events_block}</blockquote>\n"
            f"💸 <b>Итог:</b> <code>{res['net_profit']} FC</code>{ins_note}\n"
            f"🏦 <b>Твой баланс:</b> <b><code>{res['new_balance']} FC</code></b>"
        )

    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
        builder.button(text="👤 Личный кабинет", callback_data="profile")
        builder.adjust(2)
        await bot.send_message(bet["user_id"], msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        pass

async def check_and_settle_superexpress_entry(session: aiohttp.ClientSession, entry: dict):
    try:
        picks = json.loads(entry.get("picks_json") or "[]")
    except Exception:
        return
    if not picks:
        return

    all_completed, guessed = True, 0
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
        lines.append(f"<b>{idx}. {item['teams']}</b> — <code>{item['pick_label']}</code> (<b>{res['score_str']}</b>) {icon}")

    if not all_completed:
        return

    payout = 10000 if guessed == 6 else (2500 if guessed == 5 else (500 if guessed == 4 else 0))
    prize_title = f"🏆 Угадано {guessed} из 6 исходов недели!"
    updated_json = json.dumps(picks, ensure_ascii=False)
    await db_manager.settle_superexpress_entry(entry["entry_id"], entry["user_id"], guessed, payout, updated_json)
    try:
        await bot.send_message(
            entry["user_id"],
            f"🏆 <b>ИТОГИ ЕЖЕНЕДЕЛЬНОГО СУПЕРЭКСПРЕССА</b>\n<b>{prize_title}</b>\n\n<blockquote>" + "\n".join(lines) + f"</blockquote>\n💰 <b>Выигрыш:</b> <b><code>+{payout} FC</code></b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

async def match_settlement_worker():
    while True:
        try:
            await db_manager.get_or_rotate_black_market()
            pending_bets = await db_manager.get_all_pending_bets()
            pending_se = await db_manager.get_pending_superexpress_entries()
            if pending_bets or pending_se:
                async with aiohttp.ClientSession() as session:
                    for b in pending_bets:
                        await check_and_settle_real_bet(session, b)
                    for se in pending_se:
                        await check_and_settle_superexpress_entry(session, se)
        except Exception as e:
            logging.error(f"Ошибка фонового воркера: {e}")
        await asyncio.sleep(90)

# ================= АНАЛИТИКА (С ПОДДЕРЖКОЙ LIVE-СЧЕТА) И ЭКСПРЕСС ДНЯ =================
def get_top_6_upcoming_matches(db: dict) -> list:
    all_upcoming = []
    for l_val in db.values():
        for m in l_val.get("matches", {}).values():
            if not m.get("is_live"):
                all_upcoming.append(m)
    all_upcoming.sort(key=lambda x: x["start_ts"])
    return all_upcoming[:6]

def build_daily_express_data(db: dict) -> dict | None:
    selected = get_top_6_upcoming_matches(db)
    if not selected:
        return None

    picks_text, multiline_pick, legs = [], [], []
    total_odd, combined_prob, max_end_ts = 1.0, 100.0, 0

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
        picks_text.append(f"<b>{len(picks_text)+1}. {m['teams']}</b> <i>({m['short_date']})</i>\n   🎯 Прогноз: <code>{bet_str}</code> • Кэф: <b><code>{k}</code></b>")
        multiline_pick.append(f"{idx+1}. {m['teams']} — {bet_str} ({k})")
        legs.append({"league_slug": m["league_slug"], "event_id": m["event_id"], "teams": m["teams"], "pick_code": pick_code, "pick_label": bet_str, "odds": k})

    final_odd = round(total_odd, 2)
    return {
        "text": "\n\n".join(picks_text) + f"\n\n<blockquote>📈 <b>Итоговый коэффициент:</b> <code>{final_odd}</code></blockquote>",
        "total_odd": final_odd, "prob": round(combined_prob * 100, 1), "end_ts": max_end_ts,
        "summary_title": f"Экспресс дня ({len(legs)} матчей)", "summary_pick": "\n".join(multiline_pick), "legs": legs
    }

def smart_local_match_analysis(match: dict, probs: dict) -> str:
    t1, t2 = match["home_team"], match["away_team"]
    odds = match["odds"]
    p1, p2 = probs["p1"], probs["p2"]

    if match.get("is_live"):
        sc = match.get("live_score", "0:0")
        det = match.get("live_detail", "LIVE")
        return (
            f"🔴 <b>Матч в прямом эфире ({det}, счет {sc}):</b> Игра раскрывается на встречных курсах, суммарный потенциал модели составляет <code>{match['exp_goals']} xG</code>.\n\n"
            f"🎯 <b>Ориентир по модели:</b> Фаворит пары — {t1 if p1 >= p2 else t2} ({max(p1, p2)}%), базовый тотал встречи ТБ 2.5 оценен кэфом <code>{odds['tb25']}</code>."
        )

    if p1 >= 60:
        return f"⚔️ <b>Расклад:</b> {t1} имеет перевес домашнего поля и класса ({p1}%).\n\n🎯 <b>Выбор ИИ:</b> П1 ({t1}) за <code>{odds['p1']}</code> или ТБ 1.5 за <code>{odds['tb15']}</code>"
    elif p2 >= 53:
        return f"⚔️ <b>Расклад:</b> {t2} сильнее в реализации моментов ({p2}% против {p1}%).\n\n🎯 <b>Выбор ИИ:</b> П2 ({t2}) за <code>{odds['p2']}</code> или Фора 2 (0) за <code>{odds['f20']}</code>"
    elif odds["tb25"] <= 1.78:
        return f"⚔️ <b>Расклад:</b> Встреча атакующих команд с высоким потенциалом xG ({match['exp_goals']}).\n\n🎯 <b>Выбор ИИ:</b> ТБ 2.5 за <code>{odds['tb25']}</code> или Обе забьют за <code>{odds['btts']}</code>"
    elif abs(p1 - p2) <= 12:
        return f"⚔️ <b>Расклад:</b> Плотное противостояние ({p1}% на {p2}%). Высока вероятность обмена голами.\n\n🎯 <b>Выбор ИИ:</b> Обе забьют за <code>{odds['btts']}</code> или ТБ 2.0 (возврат)"
    return f"⚔️ <b>Расклад:</b> Инициатива у {t1} ({p1}%), но {t2} опасен на стандартах.\n\n🎯 <b>Выбор ИИ:</b> Фора 1 (0) за <code>{odds['f10']}</code> или ТБ 1.5 за <code>{odds['tb15']}</code>"
# ================= МОБИЛЬНЫЕ КЛАВИАТУРЫ (БЕЗ ОБРЕЗКИ И ТРОЕТОЧИЙ) =================
def main_menu_kb(user_id: int = 0):
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()

    # Кнопка запуска графического Telegram Mini App
    if WEBAPP_BASE_URL.startswith("https://"):
        builder.button(
            text="📱 Открыть WebApp (FUT • Арена • Live)",
            web_app=WebAppInfo(url=f"{WEBAPP_BASE_URL}/app?uid={user_id}")
        )

    builder.button(text="👤 Личный кабинет", callback_data="profile")
    builder.button(text="🏆 Лига Чемпионов", callback_data="league:ucl")
    builder.button(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ", callback_data="league:epl")
    builder.button(text="🇪🇸 Ла Лига", callback_data="league:laliga")
    builder.button(text="🇮🇹 Серия А", callback_data="league:seriea")
    builder.button(text="🇩🇪 Бундеслига", callback_data="league:bundesliga")
    builder.button(text="🇫🇷 Лига 1", callback_data="league:ligue1")
    builder.button(text="🌐 Другие лиги", callback_data="other_leagues")
    builder.button(text="⚡ Экспресс дня", callback_data="express_day")
    builder.button(text="🎯 Суперэкспресс", callback_data="superexpress_menu")
    builder.button(text="🏟 Империя и FUT", callback_data="empire_menu")
    builder.button(text="⚔️ PvP и Аукцион", callback_data="pvp_hub_menu")
    builder.button(text="🏆 Топ-10 капперов", callback_data="leaderboard")

    has_webapp = WEBAPP_BASE_URL.startswith("https://")
    base_layout = [1, 1, 2, 2, 2, 1, 2, 2, 1] if has_webapp else [1, 2, 2, 2, 1, 2, 2, 1]

    if slip_count > 0:
        builder.button(text=f"🧺 Купон экспресса ({slip_count})", callback_data="view_slip")
        base_layout.append(1)

    builder.adjust(*base_layout)
    return builder.as_markup()

def other_leagues_kb(db: dict):
    """Отображает только те лиги, в которых есть матчи в ближайшие 14 дней"""
    builder = InlineKeyboardBuilder()
    visible_count = 0
    for l_key, cfg in OTHER_LEAGUES.items():
        l_data = db.get(l_key, {})
        matches = l_data.get("matches", {})
        has_2w = l_data.get("has_2w_matches", False)
        if has_2w and len(matches) > 0:
            live_cnt = sum(1 for m in matches.values() if m.get("is_live"))
            badge = f" 🔴{live_cnt}" if live_cnt > 0 else f" ({len(matches)})"
            builder.button(text=f"{cfg['title']}{badge}", callback_data=f"league:{l_key}")
            visible_count += 1

    builder.button(text="🔄 Обновить лиги", callback_data="refresh_other_leagues")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")

    rows = [2] * (visible_count // 2)
    if visible_count % 2 == 1:
        rows.append(1)
    rows.append(2)
    builder.adjust(*rows)
    return builder.as_markup()

def profile_kb(active_count: int = 0, bonus_amt: int = 250, ach_count: int = 0, fav_club: str = ""):
    club_btn = f"⭐ {short_team_btn(fav_club)}" if fav_club else "⭐ Мой клуб"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"⏳ Активные ({active_count})", callback_data="active_bets")
    builder.button(text="🗄 Архив ставок", callback_data="archive_bets")
    builder.button(text="🎰 Рулетка", callback_data="roulette_menu")
    builder.button(text=f"🎁 Бонус (+{bonus_amt})", callback_data="claim_bonus")
    builder.button(text=f"🎖 Трофеи ({ach_count}/15)", callback_data="achievements_menu")
    builder.button(text=club_btn, callback_data="fav_club_menu")
    builder.button(text="✏️ Никнейм", callback_data="nick_menu")
    builder.button(text="🤝 Друзья (+500)", callback_data="referral_menu")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

def matches_kb(league_key: str, matches_dict: dict):
    """Компактные кнопки матчей с поддержкой 🔴 LIVE-индикации"""
    builder = InlineKeyboardBuilder()
    items = list(matches_dict.items())[:15]
    for match_id, data in items:
        b_teams = data.get("btn_teams") or data["teams"]
        if data.get("is_live"):
            btn_label = f"🔴 {b_teams} • {data['live_score']} ({data['live_detail']})"
        else:
            btn_label = f"{b_teams} • {data['short_date']}"
        builder.button(text=btn_label, callback_data=f"match:{league_key}:{match_id}")

    builder.button(text="🔄 Обновить", callback_data=f"refresh_league:{league_key}")
    if league_key in OTHER_LEAGUES:
        builder.button(text="⬅️ Другие лиги", callback_data="other_leagues")
    else:
        builder.button(text="🏠 В меню", callback_data="back_to_main")
    builder.adjust(*([1] * len(items)), 2)
    return builder.as_markup()

def match_outcomes_kb(league_key: str, match_id: str, odds: dict, user_id: int, is_live: bool = False):
    slip_count = len(USER_SLIPS.get(user_id, []))
    builder = InlineKeyboardBuilder()

    if is_live:
        builder.button(text="🔄 Обновить LIVE-счет", callback_data=f"match:{league_key}:{match_id}")
        builder.button(text="📊 Сводка команд", callback_data=f"stats_menu:{league_key}:{match_id}")
        builder.button(text="⬅️ К матчам", callback_data=f"league:{league_key}")
        builder.button(text="🏠 Меню", callback_data="back_to_main")
        builder.adjust(1, 1, 2)
        return builder.as_markup()

    builder.button(text=f"П1 ({odds['p1']})", callback_data=f"pick:{league_key}:{match_id}:p1")
    builder.button(text=f"Х ({odds['x']})", callback_data=f"pick:{league_key}:{match_id}:x")
    builder.button(text=f"П2 ({odds['p2']})", callback_data=f"pick:{league_key}:{match_id}:p2")
    builder.button(text="📈 Тотал Б (ТБ)", callback_data=f"totals_menu:{league_key}:{match_id}:tb")
    builder.button(text="📉 Тотал М (ТМ)", callback_data=f"totals_menu:{league_key}:{match_id}:tm")
    builder.button(text="📊 Сводка и ИТБ", callback_data=f"stats_menu:{league_key}:{match_id}")
    builder.button(text="🛡️ Форы / ОЗ", callback_data=f"extras_menu:{league_key}:{match_id}")
    if slip_count > 0:
        builder.button(text=f"🧺 Купон экспресса ({slip_count})", callback_data="view_slip")
    builder.button(text="⬅️ К матчам", callback_data=f"league:{league_key}")
    builder.button(text="🏠 Меню", callback_data="back_to_main")
    builder.adjust(*([3, 2, 2, 1, 2] if slip_count > 0 else [3, 2, 2, 2]))
    return builder.as_markup()

def stats_and_itb_kb(match: dict):
    league_key, match_id = match["league_key"], match["event_id"]
    builder = InlineKeyboardBuilder()
    if not match.get("is_live"):
        for line_val in ["0.5", "1.5", "2.5"]:
            m1, m2 = evaluate_custom_market(match, f"itb1_{line_val}"), evaluate_custom_market(match, f"itb2_{line_val}")
            if m1 and m2:
                builder.button(text=f"🏠 ИТБ1>{line_val} ({m1['odds']})", callback_data=f"pick:{league_key}:{match_id}:itb1_{line_val}")
                builder.button(text=f"✈️ ИТБ2>{line_val} ({m2['odds']})", callback_data=f"pick:{league_key}:{match_id}:itb2_{line_val}")
        builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{league_key}:{match_id}")
        builder.adjust(2, 2, 2, 1)
    else:
        builder.button(text="⬅️ Назад к LIVE-матчу", callback_data=f"match:{league_key}:{match_id}")
        builder.adjust(1)
    return builder.as_markup()

def totals_constructor_kb(match: dict, direction: str):
    league_key, match_id = match["league_key"], match["event_id"]
    prefix = "ТБ" if direction == "tb" else "ТМ"
    builder = InlineKeyboardBuilder()
    for line_val in ["1.0", "1.5", "2.0", "2.5", "3.0", "3.5", "4.0", "4.5"]:
        code = f"{direction}_{line_val}"
        mkt = evaluate_custom_market(match, code)
        if mkt:
            builder.button(text=f"{prefix} {line_val} ({mkt['odds']})", callback_data=f"pick:{league_key}:{match_id}:{code}")
    builder.button(text="⬅️ Назад к матчу", callback_data=f"match:{league_key}:{match_id}")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()

def extras_menu_kb(match: dict):
    league_key, match_id, o = match["league_key"], match["event_id"], match["odds"]
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
    builder.button(text="✍️ Своя сумма", callback_data=f"custom_amt:{target_code}")

    if target_code == "express-day":
        builder.button(text="⬅️ Назад", callback_data="express_day")
        builder.adjust(2, 2, 1, 1, 1)
    elif target_code == "custom-slip":
        builder.button(text="⬅️ Назад", callback_data="view_slip")
        builder.adjust(2, 2, 1, 1, 1)
    else:
        l_key, m_id, p_code = target_code.split("-", 2)
        builder.button(text="➕ В Экспресс", callback_data=f"slipadd:{l_key}:{m_id}:{p_code}")
        builder.button(text="⬅️ Назад", callback_data=f"match:{l_key}:{m_id}")
        builder.adjust(2, 2, 1, 1, 2)
    return builder.as_markup()

# ================= ХАБ 1: 🏟 ИМПЕРИЯ, СТАДИОНЫ (С ГАЛОЧКАМИ) И FUT =================
@dp.callback_query(F.data == "empire_menu")
async def process_empire_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    st_lvl = int(user.get("stadium_level") or 1)
    lab_lvl = int(user.get("lab_level") or 1)
    st_cfg = STADIUM_LEVELS.get(st_lvl, STADIUM_LEVELS[1])
    lab_cfg = LAB_LEVELS.get(lab_lvl, LAB_LEVELS[1])

    today_str = now_msk().strftime("%Y-%m-%d")
    can_claim = user.get("last_stadium_claim") != today_str
    claim_status = f"🟢 <b>Готово к сбору: +{st_cfg['income']} FC</b>" if can_claim else "⏳ <i>Касса собрана (раз в сутки)</i>"

    buffs = get_user_fut_buffs(user)
    fw_txt = f"{buffs['fw_card']['name']} (+{buffs['totals_profit_pct']}% к ТБ)" if buffs["fw_card"] else "Пусто"
    gk_txt = f"{buffs['gk_card']['name']} ({buffs['loss_cashback_pct']}% кэшбэк)" if buffs["gk_card"] else "Пусто"
    co_txt = f"{buffs['co_card']['name']} (+{buffs['express_odd_boost']} к прессам)" if buffs["co_card"] else "Пусто"

    text = (
        f"🏟 <b>ФУТБОЛЬНАЯ ИМПЕРИЯ И FUT</b>\n\n"
        f"<blockquote>💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"✅ <b>Арена ({st_lvl}/10):</b> {st_cfg['name']} ({st_cfg['cap']})\n"
        f"💵 Доход: <code>+{st_cfg['income']} FC/день</code> • {claim_status}\n"
        f"🧠 <b>ИИ-Отдел ({lab_lvl}/5):</b> {lab_cfg['name']} (+{lab_cfg['odd_bonus']} к кэфам)</blockquote>\n"
        f"👕 <b>Мой FUT-Состав (Активные бонусы):</b>\n"
        f"• ⚡ Форвард: <b>{fw_txt}</b>\n"
        f"• 🧤 Вратарь: <b>{gk_txt}</b>\n"
        f"• 📋 Тренер: <b>{co_txt}</b>"
    )

    builder = InlineKeyboardBuilder()
    if can_claim:
        builder.button(text=f"💰 Собрать кассу (+{st_cfg['income']} FC)", callback_data="empire_claim")
    else:
        builder.button(text="⏳ Касса собрана сегодня", callback_data="empire_claim")

    builder.button(text="🏟 Стадионы", callback_data="stadiums_catalog")
    if lab_lvl < 5:
        next_lab_price = LAB_LEVELS[lab_lvl + 1]["price"]
        builder.button(text=f"🧠 ИИ Ур.{lab_lvl+1} ({next_lab_price} FC)", callback_data="empire_up:lab")

    builder.button(text="🃏 Паки FUT", callback_data="fut_packs_menu")
    builder.button(text="🔥 Валуй ИИ", callback_data="ai_value_pick")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")

    if lab_lvl < 5:
        builder.adjust(1, 2, 2, 1)
    else:
        builder.adjust(1, 1, 2, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "stadiums_catalog")
async def process_stadiums_catalog(callback: CallbackQuery):
    """Раздел «🏟 Стадионы» — без лишних слов и с галочками ✅ у всех купленных арен"""
    user = await db_manager.get_user(callback.from_user.id)
    cur_lvl = int(user.get("stadium_level") or 1)

    lines = []
    for lvl, cfg in STADIUM_LEVELS.items():
        price_str = "Базовая" if cfg["price"] == 0 else f"{cfg['price']:,} FC".replace(",", " ")
        inc_str = f"+{cfg['income']} FC/день"

        if lvl < cur_lvl:
            status_icon = "✅"
            note = "<i>Куплена</i>"
        elif lvl == cur_lvl:
            status_icon = "✅"
            note = "<b>Твоя текущая арена</b>"
        elif lvl == cur_lvl + 1:
            status_icon = "🔓"
            note = f"<b>Доступна: <code>{price_str}</code></b>"
        else:
            status_icon = "🔒"
            note = f"Стоимость: <code>{price_str}</code>"

        lines.append(
            f"{status_icon} <b>{lvl}. {cfg['name']}</b> ({cfg['cap']})\n"
            f"   💵 Выручка: <b><code>{inc_str}</code></b> • {note}"
        )

    text = (
        f"🏟 <b>СТАДИОНЫ</b>\n"
        f"💰 Твой банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n\n"
        f"<blockquote>" + "\n\n".join(lines) + "</blockquote>\n"
        f"<i>💡 Выручка от билетов собирается раз в сутки.</i>"
    )

    builder = InlineKeyboardBuilder()
    if cur_lvl < 10:
        nxt = STADIUM_LEVELS[cur_lvl + 1]
        p_fmt = f"{nxt['price']:,}".replace(",", " ")
        builder.button(
            text=f"🏗 Купить «{nxt['name']}» ({p_fmt} FC)",
            callback_data="empire_up:stadium"
        )
    builder.button(text="⬅️ Назад в Империю", callback_data="empire_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "empire_claim")
async def process_empire_claim(callback: CallbackQuery, state: FSMContext):
    ok, inc, name = await db_manager.claim_stadium_income(callback.from_user.id)
    if ok:
        await callback.answer(f"🏟 Выручка «{name}» получена: +{inc} FC!", show_alert=True)
        await process_empire_menu(callback, state)
    else:
        await callback.answer("⏳ Касса сегодня уже собрана! Новая выручка поступит завтра.", show_alert=True)

@dp.callback_query(F.data.startswith("empire_up:"))
async def process_empire_upgrade(callback: CallbackQuery, state: FSMContext):
    b_type = callback.data.split(":")[1]
    res = await db_manager.upgrade_empire_building(callback.from_user.id, b_type)
    if not res["ok"]:
        await callback.answer(f"⚠️ {res['error']}", show_alert=True)
        return
    await callback.answer(f"✅ Приобретено: {res['name']} (Ур. {res['new_lvl']})!", show_alert=True)
    if b_type == "stadium":
        await process_stadiums_catalog(callback)
    else:
        await process_empire_menu(callback, state)

@dp.callback_query(F.data == "ai_value_pick")
async def process_ai_value_pick(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id)
    if int(user.get("lab_level") or 1) < 2:
        await callback.answer("🔒 Прокачай ИИ-Отдел до 2-го уровня для доступа к «Валую дня»!", show_alert=True)
        return

    db = await get_real_matches()
    top_m = get_top_6_upcoming_matches(db)
    if not top_m:
        await callback.answer("Сейчас нет предстоящих матчей в линии.", show_alert=True)
        return

    best_m = max(top_m, key=lambda x: x["exp_goals"])
    mkt = evaluate_custom_market(best_m, "tb_2.0")
    text = (
        f"🧠 <b>СЕКРЕТНЫЙ ВАЛУЙ ДНЯ ОТ ИИ</b>\n\n"
        f"<blockquote>🏟 <b>{best_m['teams']}</b> <i>({best_m['date']})</i>\n"
        f"📊 Ожидаемые голы: <b><code>{best_m['exp_goals']} xG</code></b>\n"
        f"🎯 Рекомендация: <b><code>{mkt['label']}</code></b> за <b><code>{mkt['odds']}</code></b>\n"
        f"📈 Вероятность: <b>{mkt['prob']}%</b></blockquote>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🎯 Поставить {mkt['label']} ({mkt['odds']})", callback_data=f"pick:{best_m['league_key']}:{best_m['event_id']}:tb_2.0")
    builder.button(text="⬅️ Назад в Империю", callback_data="empire_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "fut_packs_menu")
async def process_fut_packs_menu(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id)
    text = (
        f"🃏 <b>ПАКИ КАРТОЧЕК «FUT-КАППЕР»</b>\n\n"
        f"<blockquote>💰 Твой банк: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"Карточки навсегда усиливают твои ставки на реальные матчи!</blockquote>\n"
        f"• 🥉 <b>Базовый пак (1 500 FC)</b> — игроки основы (+5%..+10%)\n"
        f"• 🥇 <b>Золотой пак (5 000 FC)</b> — звезды Топ-5 лиг (+10%..+16%)\n"
        f"• 💎 <b>Элитный пак ЛЧ (15 000 FC)</b> — высокий шанс на TOTY и Иконы"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🥉 Базовый пак (1 500 FC)", callback_data="buy_pack:basic")
    builder.button(text="🥇 Золотой пак (5 000 FC)", callback_data="buy_pack:gold")
    builder.button(text="💎 Элитный пак ЛЧ (15 000 FC)", callback_data="buy_pack:elite")
    builder.button(text="⬅️ Назад в Империю", callback_data="empire_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_pack:"))
async def process_buy_pack(callback: CallbackQuery):
    p_type = callback.data.split(":")[1]
    user = await db_manager.get_user(callback.from_user.id)
    if p_type == "basic":
        cost, pool, weights = 1500, ["fw_1", "gk_1", "co_1", "fw_2", "gk_2"], [30, 30, 25, 10, 5]
    elif p_type == "gold":
        cost, pool, weights = 5000, ["fw_1", "gk_1", "fw_2", "fw_3", "gk_2", "co_2", "fw_4"], [12, 12, 22, 20, 15, 14, 5]
    else:
        cost, pool, weights = 15000, ["fw_2", "gk_2", "co_2", "fw_4", "fw_5", "gk_3", "co_3"], [10, 10, 10, 20, 18, 16, 16]

    if user["balance"] < cost:
        await callback.answer(f"⚠️ Недостаточно средств! Нужно {cost} FC.", show_alert=True)
        return

    await callback.answer("🃏 Открываем пак...")
    card_id = random.choices(pool, weights=weights, k=1)[0]

    for frame in [
        "🃏 <b>ОТКРЫТИЕ НАБОРА FUT...</b>\n\n<blockquote><code>✨ [ ? ? ? ] ✨ — Прожектора зажигаются...</code></blockquote>",
        f"🃏 <b>ОПРЕДЕЛЕНИЕ ПОЗИЦИИ...</b>\n\n<blockquote><code>🔥 Позиция: [ {FUT_CARDS[card_id]['role']} ] — Выход игрока на поле!</code></blockquote>"
    ]:
        try:
            await callback.message.edit_text(frame, parse_mode="HTML")
            await asyncio.sleep(0.65)
        except Exception:
            pass

    res = await db_manager.open_fut_pack_db(callback.from_user.id, cost, card_id)
    if not res["ok"]:
        await callback.answer(res["error"], show_alert=True)
        return

    c = res["card"]
    text = (
        f"🎉 <b>ВЫПАЛА КАРТОЧКА!</b>\n\n"
        f"<blockquote>🌟 <b>{c['name']}</b>\n"
        f"📋 Позиция: <code>{c['role']}</code>\n"
        f"⚡ Эффект: <b>{c['desc']}</b></blockquote>\n"
        f"{res['status_note']}\n"
        f"🏦 <b>Остаток на балансе:</b> <b><code>{res['new_balance']} FC</code></b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🃏 Открыть еще пак", callback_data="fut_packs_menu")
    builder.button(text="🏟 Мой состав и Империя", callback_data="empire_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ================= ХАБ 2: ⚔️ PVP-ПЕНАЛЬТИ И ЧЕРНЫЙ РЫНОК =================
@dp.callback_query(F.data == "pvp_hub_menu")
async def process_pvp_hub_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = callback.from_user.id
    user = await db_manager.get_user(uid)
    open_duels = await db_manager.get_open_pvp_duels(uid)
    lot = await db_manager.get_or_rotate_black_market()
    lot_card = FUT_CARDS.get(lot["lot_id"], {"name": "Секретный лот", "desc": ""})

    text = (
        f"⚔️ <b>PVP-АРЕНА И ЧЕРНЫЙ РЫНОК</b>\n\n"
        f"<blockquote>💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>  •  🏆 Побед в PvP: <b><code>{user.get('pvp_wins', 0)}</code></b>\n"
        f"🎯 Бросай личный вызов по Нику/ID или играй в лобби!</blockquote>\n"
        f"🔨 <b>Черный рынок (до 23:59 МСК):</b>\n"
        f"• Лот: <b>{lot_card['name']}</b> ({lot_card['desc']})\n"
        f"• Ставка: <b><code>{lot['highest_bid']} FC</code></b> (Лидер: <b>{lot['leader_name']}</b>)"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⚽ Создать дуэль Пенальти", callback_data="pvp_create_start")
    builder.button(text=f"🔨 Аукцион • {lot['highest_bid']} FC", callback_data="black_market_menu")

    for d in open_duels[:6]:
        if d["creator_id"] == uid:
            target_tag = "Личный" if int(d.get("target_id") or 0) > 0 else "Лобби"
            builder.button(text=f"❌ Отменить #{d['duel_id']} ({d['stake']} FC • {target_tag})", callback_data=f"pvp_cancel:{d['duel_id']}")
        elif int(d.get("target_id") or 0) == uid:
            builder.button(text=f"🔥 ВЫЗОВ ТЕБЕ: {d['creator_name']} ({d['stake']} FC)", callback_data=f"pvp_accept_start:{d['duel_id']}")
        else:
            builder.button(text=f"⚔️ Принять: {d['creator_name']} • {d['stake']} FC", callback_data=f"pvp_accept_start:{d['duel_id']}")

    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "pvp_create_start")
async def process_pvp_create_start(callback: CallbackQuery, state: FSMContext):
    user = await db_manager.get_user(callback.from_user.id)
    await state.set_state(BetStates.waiting_for_pvp_stake)
    builder = InlineKeyboardBuilder()
    for amt in [100, 500, 1000, 2500]:
        builder.button(text=f"💵 {amt} FC", callback_data=f"pvp_stake_set:{amt}")
    builder.button(text="🔙 Назад в PvP-Арену", callback_data="pvp_hub_menu")
    builder.adjust(2, 2, 1)

    await callback.message.edit_text(
        f"⚽ <b>СОЗДАНИЕ PVP-ДУЭЛИ (ПЕНАЛЬТИ)</b>\n\n"
        f"<blockquote>💰 Твой баланс: <b><code>{round(user['balance'], 1)} FC</code></b>\n"
        f"Минимальная ставка: <code>50 FC</code></blockquote>\n"
        f"👇 <b>Выбери сумму кнопкой ИЛИ напиши любую ставку числом в чат:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(BetStates.waiting_for_pvp_stake)
async def process_pvp_stake_input(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 50:
        await message.answer("⚠️ Введи ставку целым числом от <code>50</code> FC:", parse_mode="HTML")
        return
    stake = int(raw)
    user = await db_manager.get_user(message.from_user.id)
    if user["balance"] < stake:
        await message.answer(f"⚠️ Недостаточно средств! Твой баланс: {round(user['balance'], 1)} FC.")
        return

    await state.clear()
    PVP_DRAFTS[message.from_user.id] = {"stake": stake, "mode": "create", "duel_id": 0}
    await send_pvp_kick_selection(message, stake, is_edit=False)

@dp.callback_query(F.data.startswith("pvp_stake_set:"))
async def process_pvp_stake_btn(callback: CallbackQuery, state: FSMContext):
    stake = int(callback.data.split(":")[1])
    user = await db_manager.get_user(callback.from_user.id)
    if user["balance"] < stake:
        await callback.answer(f"⚠️ Недостаточно средств! Баланс: {round(user['balance'], 1)} FC.", show_alert=True)
        return
    await state.clear()
    PVP_DRAFTS[callback.from_user.id] = {"stake": stake, "mode": "create", "duel_id": 0}
    await send_pvp_kick_selection(callback.message, stake, is_edit=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_accept_start:"))
async def process_pvp_accept_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    duel_id = int(callback.data.split(":")[1])
    d = await db_manager.get_pvp_duel(duel_id)
    if not d or d["status"] != "open":
        await callback.answer("Этот вызов уже закрыт или отменен!", show_alert=True)
        await process_pvp_hub_menu(callback, state)
        return

    user = await db_manager.get_user(callback.from_user.id)
    if user["balance"] < d["stake"]:
        await callback.answer(f"⚠️ Недостаточно средств для принятия вызова ({d['stake']} FC)!", show_alert=True)
        return

    PVP_DRAFTS[callback.from_user.id] = {"stake": d["stake"], "mode": "accept", "duel_id": duel_id}
    await send_pvp_kick_selection(callback.message, d["stake"], is_edit=True)
    await callback.answer()

async def send_pvp_kick_selection(msg_obj: Message, stake: int, is_edit: bool = True):
    builder = InlineKeyboardBuilder()
    builder.button(text="↖️ Влево", callback_data="pvp_kick:L")
    builder.button(text="⬆️ По центру", callback_data="pvp_kick:C")
    builder.button(text="↗️ Вправо", callback_data="pvp_kick:R")
    builder.adjust(3)
    txt = f"⚽ <b>ШАГ 1 ИЗ 2: КУДА БЬЕШЬ ПЕНАЛЬТИ?</b>\n\n<blockquote>💵 Ставка на кону: <b><code>{stake} FC</code></b></blockquote>\n👇 Выбери угол своего удара:"
    if is_edit:
        await msg_obj.edit_text(txt, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await msg_obj.answer(txt, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("pvp_kick:"))
async def process_pvp_kick_choice(callback: CallbackQuery):
    k_dir = callback.data.split(":")[1]
    draft = PVP_DRAFTS.get(callback.from_user.id)
    if not draft:
        await callback.answer("Сессия устарела", show_alert=True)
        return
    draft["kick"] = k_dir

    builder = InlineKeyboardBuilder()
    builder.button(text="↖️ Прыжок влево", callback_data="pvp_save:L")
    builder.button(text="⬆️ Центр", callback_data="pvp_save:C")
    builder.button(text="↗️ Прыжок вправо", callback_data="pvp_save:R")
    builder.adjust(3)
    await callback.message.edit_text(
        f"🧤 <b>ШАГ 2 ИЗ 2: КУДА ПРЫГАЕТ ВРАТАРЬ?</b>\n\n<blockquote>💵 Ставка: <b><code>{draft['stake']} FC</code></b></blockquote>\n👇 Угадай угол удара соперника:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

def resolve_penalty_shootout(k1: str, s1: str, k2: str, s2: str) -> tuple[int, int, str]:
    dir_names = {"L": "↖️ Левый", "C": "⬆️ Центр", "R": "↗️ Правый"}
    g1 = 0 if k1 == s2 else 1
    g2 = 0 if k2 == s1 else 1
    r1_txt = f"⚽ Игрок 1 ({dir_names[k1]}) vs Кипер 2 ({dir_names[s2]}) — {'<b>ГОЛ! ✅</b>' if g1 else '<b>СЕЙВ! ❌</b>'}"
    r2_txt = f"⚽ Игрок 2 ({dir_names[k2]}) vs Кипер 1 ({dir_names[s1]}) — {'<b>ГОЛ! ✅</b>' if g2 else '<b>СЕЙВ! ❌</b>'}"
    return g1, g2, f"{r1_txt}\n{r2_txt}"

@dp.callback_query(F.data.startswith("pvp_save:"))
async def process_pvp_save_choice(callback: CallbackQuery, state: FSMContext):
    s_dir = callback.data.split(":")[1]
    uid = callback.from_user.id
    draft = PVP_DRAFTS.get(uid)
    if not draft:
        return
    draft["save"] = s_dir

    if draft["mode"] == "accept":
        duel_id = draft["duel_id"]
        d = await db_manager.get_pvp_duel(duel_id)
        if not d or d["status"] != "open":
            await callback.answer("Вызов уже неактивен!", show_alert=True)
            await process_pvp_hub_menu(callback, state)
            return

        u2 = await db_manager.get_user(uid)
        stake = int(d["stake"])
        if u2["balance"] < stake:
            await callback.answer("Недостаточно FC!", show_alert=True)
            return

        await db_manager.exec("UPDATE pvp_duels SET status = 'closed' WHERE duel_id = $1", duel_id)
        await db_manager.exec("UPDATE users SET balance = balance - $1 WHERE user_id = $2", float(stake), uid)

        g1, g2, log_txt = resolve_penalty_shootout(d["kick_dir"], d["save_dir"], draft["kick"], draft["save"])
        bank = round(stake * 2 * 0.95, 1)

        if g1 > g2:
            await db_manager.exec("UPDATE users SET balance = balance + $1, pvp_wins = pvp_wins + 1, profit = profit + $2 WHERE user_id = $3", bank, bank - stake, d["creator_id"])
            res_headline = f"🏆 Победитель: <b>{d['creator_name']}</b> (+{bank} FC)!"
        elif g2 > g1:
            await db_manager.exec("UPDATE users SET balance = balance + $1, pvp_wins = pvp_wins + 1, profit = profit + $2 WHERE user_id = $3", bank, bank - stake, uid)
            res_headline = f"🏆 Победитель: <b>{u2['username']}</b> (+{bank} FC)!"
        else:
            await db_manager.exec("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(stake), d["creator_id"])
            await db_manager.exec("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(stake), uid)
            res_headline = f"🤝 Ничья ({g1}:{g2})! Ставки ({stake} FC) возвращены."

        summary_msg = (
            f"⚔️ <b>ИТОГ PVP-ДУЭЛИ #{duel_id}</b>\n"
            f"<b>{d['creator_name']}</b> vs <b>{u2['username']}</b>\n\n"
            f"<blockquote>{log_txt}</blockquote>\n"
            f"{res_headline}"
        )
        try:
            await bot.send_message(d["creator_id"], summary_msg, parse_mode="HTML")
        except Exception:
            pass

        builder = InlineKeyboardBuilder()
        builder.button(text="⚔️ В PvP-Арену", callback_data="pvp_hub_menu")
        await callback.message.edit_text(summary_msg, reply_markup=builder.as_markup(), parse_mode="HTML")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Вызвать игрока (По Нику / ID)", callback_data="pvp_finish:direct")
    builder.button(text="🌐 Опубликовать в Лобби", callback_data="pvp_finish:lobby")
    builder.button(text="🤖 Сыграть с Кипером Лиги", callback_data="pvp_finish:bot")
    builder.button(text="🔙 Отмена", callback_data="pvp_hub_menu")
    builder.adjust(1)
    await callback.message.edit_text(
        f"✅ <b>УГЛЫ ВЫБРАНЫ ({draft['stake']} FC)</b>\n\n"
        f"👇 <b>Выбери, кому отправить вызов:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_finish:"))
async def process_pvp_finish(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    uid = callback.from_user.id
    draft = PVP_DRAFTS.get(uid)
    if not draft:
        return

    if mode == "direct":
        await state.set_state(BetStates.waiting_for_pvp_target)
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Отмена", callback_data="pvp_hub_menu")
        await callback.message.edit_text(
            f"🎯 <b>ЛИЧНЫЙ ВЫЗОВ ({draft['stake']} FC)</b>\n\n"
            f"Напиши в чат <b>Никнейм</b> или <b>ID игрока</b>, которому хочешь бросить вызов:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    PVP_DRAFTS.pop(uid, None)
    if mode == "lobby":
        res = await db_manager.create_pvp_duel(uid, draft["stake"], draft["kick"], draft["save"], target_id=0)
        if not res["ok"]:
            await callback.answer(res["error"], show_alert=True)
            return
        await callback.answer(f"⚔️ Вызов #{res['duel_id']} ({draft['stake']} FC) выставлен в лобби!", show_alert=True)
        await process_pvp_hub_menu(callback, state)
    else:
        user = await db_manager.get_user(uid)
        stake = draft["stake"]
        if user["balance"] < stake:
            await callback.answer("Недостаточно FC!", show_alert=True)
            return

        bot_kick, bot_save = random.choice(["L", "C", "R"]), random.choice(["L", "C", "R"])
        g1, g2, log_txt = resolve_penalty_shootout(draft["kick"], draft["save"], bot_kick, bot_save)

        if g1 > g2:
            win_profit = round(stake * 0.90, 1)
            await db_manager.exec("UPDATE users SET balance = balance + $1, pvp_wins = pvp_wins + 1, profit = profit + $1 WHERE user_id = $2", win_profit, uid)
            res_line = f"🎉 <b>ПОБЕДА!</b> Чистый выигрыш: <b><code>+{win_profit} FC</code></b>!"
        elif g2 > g1:
            await db_manager.exec("UPDATE users SET balance = balance - $1, profit = profit - $1 WHERE user_id = $2", float(stake), uid)
            res_line = f"❌ <b>ПОРАЖЕНИЕ!</b> Потеряно: <code>-{stake} FC</code>."
        else:
            res_line = f"🤝 <b>НИЧЬЯ ({g1}:{g2})!</b> Твои <code>{stake} FC</code> остались при тебе."

        builder = InlineKeyboardBuilder()
        builder.button(text="⚽ Сыграть еще раз", callback_data="pvp_create_start")
        builder.button(text="⚔️ В PvP-Арену", callback_data="pvp_hub_menu")
        builder.adjust(1)
        await callback.message.edit_text(
            f"⚽ <b>СЕРИЯ ПЕНАЛЬТИ ЗАВЕРШЕНА!</b>\n\n<blockquote>{log_txt}</blockquote>\n{res_line}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()

@dp.message(BetStates.waiting_for_pvp_target)
async def process_pvp_target_input(message: Message, state: FSMContext):
    uid = message.from_user.id
    draft = PVP_DRAFTS.get(uid)
    if not draft:
        await state.clear()
        return

    target_user = await db_manager.find_user_by_query(message.text or "")
    if not target_user:
        await message.answer("⚠️ Игрок с таким Ником или ID не найден. Проверь написание и отправь еще раз:")
        return
    if target_user["user_id"] == uid:
        await message.answer("⚠️ Нельзя вызвать самого себя! Введи Ник или ID другого игрока:")
        return

    PVP_DRAFTS.pop(uid, None)
    await state.clear()
    res = await db_manager.create_pvp_duel(uid, draft["stake"], draft["kick"], draft["save"], target_id=target_user["user_id"])
    if not res["ok"]:
        await message.answer(f"⚠️ {res['error']}", reply_markup=main_menu_kb(uid))
        return

    sender = await db_manager.get_user(uid)
    duel_id = res["duel_id"]

    try:
        t_kb = InlineKeyboardBuilder()
        t_kb.button(text=f"⚔️ Принять вызов ({draft['stake']} FC)", callback_data=f"pvp_accept_start:{duel_id}")
        t_kb.button(text="❌ Отклонить", callback_data=f"pvp_cancel:{duel_id}")
        t_kb.adjust(1)
        await bot.send_message(
            target_user["user_id"],
            f"🔥 <b>ЛИЧНЫЙ ВЫЗОВ В ПЕНАЛЬТИ!</b>\n\n"
            f"<blockquote>👤 Соперник: <b>{sender['username']}</b> (ID: <code>{sender['user_id']}</code>)\n"
            f"💵 Ставка: <b><code>{draft['stake']} FC</code></b>\n"
            f"🏆 Банк: <b><code>{round(draft['stake'] * 2 * 0.95, 1)} FC</code></b></blockquote>\n"
            f"👇 Прими дуэль или отклони вызов:",
            reply_markup=t_kb.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass

    b_back = InlineKeyboardBuilder()
    b_back.button(text="⚔️ В PvP-Арену", callback_data="pvp_hub_menu")
    await message.answer(
        f"✅ <b>Вызов #{duel_id} отправлен игроку {target_user['username']}!</b>\n"
        f"Как только он ответит, тебе придет уведомление.",
        reply_markup=b_back.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("pvp_cancel:"))
async def process_pvp_cancel(callback: CallbackQuery, state: FSMContext):
    duel_id = int(callback.data.split(":")[1])
    cancelled_duel = await db_manager.cancel_pvp_duel(duel_id, callback.from_user.id)
    if cancelled_duel:
        if callback.from_user.id == cancelled_duel.get("target_id"):
            await callback.answer("❌ Вызов отклонен.", show_alert=True)
            try:
                await bot.send_message(
                    cancelled_duel["creator_id"],
                    f"📢 Игрок отклонил твой вызов #{duel_id}. Ставка <b><code>+{cancelled_duel['stake']} FC</code></b> возвращена.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            await callback.answer("✅ Вызов отменен, ставка возвращена!", show_alert=True)
    await process_pvp_hub_menu(callback, state)

# ================= ЧЕРНЫЙ РЫНОК (ЕЖЕДНЕВНЫЙ АУКЦИОН) =================
@dp.callback_query(F.data == "black_market_menu")
async def process_black_market_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lot = await db_manager.get_or_rotate_black_market()
    user = await db_manager.get_user(callback.from_user.id)
    c = FUT_CARDS.get(lot["lot_id"], {"name": "Секретный лот", "desc": ""})
    cur_bid = int(lot["highest_bid"])
    min_next = cur_bid + 500 if int(lot["leader_id"]) != 0 else cur_bid

    text = (
        f"🔨 <b>ЧЕРНЫЙ РЫНОК — АУКЦИОН ДНЯ</b>\n\n"
        f"<blockquote>🌟 <b>Эксклюзивный лот:</b>\n"
        f"<b>{c['name']}</b>\n"
        f"⚡ Бонус навсегда: <b>{c['desc']}</b></blockquote>\n"
        f"📊 <b>Текущие торги:</b>\n"
        f"• Текущая ставка: <b><code>{cur_bid} FC</code></b>\n"
        f"• Лидер: <b>{lot['leader_name']}</b>\n"
        f"• Твой баланс: <b><code>{round(user['balance'], 1)} FC</code></b>\n\n"
        f"<i>💡 В 00:00 МСК лидер забирает карточку! Перебитая ставка мгновенно возвращается.</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🔨 Поставить {min_next} FC", callback_data=f"bm_bid:{min_next}")
    builder.button(text=f"🔥 Шаг +2 000 ({min_next + 1500} FC)", callback_data=f"bm_bid:{min_next + 1500}")
    builder.button(text="✍️ Ввести свою ставку", callback_data="bm_custom")
    builder.button(text="⬅️ Назад в PvP-Арену", callback_data="pvp_hub_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("bm_bid:"))
async def process_bm_bid(callback: CallbackQuery, state: FSMContext):
    amt = int(callback.data.split(":")[1])
    res = await db_manager.place_black_market_bid(callback.from_user.id, amt)
    if not res["ok"]:
        await callback.answer(f"⚠️ {res['error']}", show_alert=True)
        return
    await callback.answer(f"🔨 Ставка {amt} FC принята! Ты лидер торгов!", show_alert=True)
    await process_black_market_menu(callback, state)

@dp.callback_query(F.data == "bm_custom")
async def process_bm_custom_ask(callback: CallbackQuery, state: FSMContext):
    lot = await db_manager.get_or_rotate_black_market()
    min_next = int(lot["highest_bid"]) + 500 if int(lot["leader_id"]) != 0 else int(lot["highest_bid"])
    await state.set_state(BetStates.waiting_for_auction_bid)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="black_market_menu")
    await callback.message.edit_text(
        f"✍️ <b>СТАВКА НА АУКЦИОНЕ</b>\n\nНапиши сумму в чат (минимум <code>{min_next}</code> FC):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(BetStates.waiting_for_auction_bid)
async def process_bm_custom_input(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("⚠️ Введи целое число без букв:")
        return
    res = await db_manager.place_black_market_bid(message.from_user.id, int(raw))
    if not res["ok"]:
        await message.answer(f"⚠️ {res['error']}\nВведи другую сумму:")
        return
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔨 На Черный рынок", callback_data="black_market_menu")
    await message.answer(f"🔨 Ставка <b>{raw} FC</b> принята! Ты возглавил торги!", reply_markup=builder.as_markup(), parse_mode="HTML")

# ================= СТАРТ, КОМАНДА /PROFILE И НАВИГАЦИЯ =================
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
                f"🎉 <b>НОВЫЙ РЕФЕРАЛ!</b>\n\nИгрок <b>{user['username']}</b> присоединился по твоей ссылке!\n💰 Начислено <b><code>+500 FC</code></b>!",
                parse_mode="HTML"
            )
        except Exception:
            pass

    rank_name, _ = get_user_rank_info(user["balance"], user["is_vip"])
    bonus_note = "\n🎁 <i>Начислено +500 FC по приглашению друга!</i>\n" if rewarded else ""
    text = (
        f"⚽ <b>AI_BET_BOT • ФУТБОЛЬНАЯ ЭКОСИСТЕМА</b>\n\n"
        f"<blockquote>👤 Каппер: <b>{user['username']}</b>\n"
        f"🆔 Твой ID: <code>{user['user_id']}</code> <i>(нажми для копирования)</i>\n"
        f"🏅 Ранг: <b>{rank_name}</b>\n"
        f"💰 Банк: <b><code>{round(user['balance'], 1)} FC</code></b>  •  🏆 Побед: <b><code>{user['wins']}</code></b></blockquote>"
        f"{bonus_note}"
        f"👇 <b>Выбери турнир, Империю FUT или PvP-Арену:</b>"
    )
    await message.answer(text, reply_markup=main_menu_kb(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_main")
async def process_back_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    rank_name, _ = get_user_rank_info(user["balance"], user["is_vip"])
    text = (
        f"⚽ <b>ГЛАВНОЕ МЕНЮ • AI_BET_BOT</b>\n\n"
        f"<blockquote>👤 <b>{user['username']}</b>  •  ID: <code>{user['user_id']}</code>\n"
        f"🏅 Ранг: <b>{rank_name}</b>\n"
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
        "🌐 <b>ДРУГИЕ ЧЕМПИОНАТЫ И СБОРНЫЕ</b>\n\n"
        "<blockquote>Показаны турниры с матчами в ближайшие 14 дней (включая РПЛ и Лигу Наций). Лиги на паузе скрываются автоматически.</blockquote>\n"
        "👇 <b>Выбери турнир:</b>"
    )
    await callback.message.edit_text(text, reply_markup=other_leagues_kb(db), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "refresh_other_leagues")
async def process_refresh_other_leagues(callback: CallbackQuery, state: FSMContext):
    await callback.answer("📡 Обновляю расписание всех турниров...")
    db = await get_real_matches(force_refresh=True)
    text = (
        "🌐 <b>ДРУГИЕ ЧЕМПИОНАТЫ И СБОРНЫЕ</b>\n\n"
        "<blockquote>Показаны турниры с матчами в ближайшие 14 дней (включая РПЛ и Лигу Наций).</blockquote>\n"
        "👇 <b>Выбери турнир:</b>"
    )
    await callback.message.edit_text(text, reply_markup=other_leagues_kb(db), parse_mode="HTML")

# ================= ЛИЧНЫЙ КАБИНЕТ (С КОПИРОВАНИЕМ ID В 1 КАСАНИЕ) =================
def build_profile_View_data(user: dict, active_bets: list) -> tuple[str, InlineKeyboardMarkup]:
    total_settled = user["wins"] + user["losses"]
    winrate = round((user["wins"] / total_settled) * 100, 1) if total_settled > 0 else 0.0
    rank_name, bonus_amt = get_user_rank_info(user["balance"], user["is_vip"])
    profit_sign = "+" if user["profit"] >= 0 else ""

    try:
        unlocked = json.loads(user.get("achievements") or "[]")
    except Exception:
        unlocked = []

    streak = int(user.get("streak") or 0)
    streak_target = f" <i>(до «Хет-трика»: {3 - streak})</i>" if streak < 3 else (f" <i>(до «Снайпера»: {7 - streak})</i>" if streak < 7 else " 🔥")
    fav_club = user.get("favorite_club") or ""
    club_line = f"⭐ Клуб: <b>{fav_club}</b> <i>(+10% к выплатам)</i>\n" if fav_club else ""
    booster_code = user.get("active_booster") or ""
    booster_line = f"\n🚀 <b>Активный бустер:</b> {BOOSTER_NAMES.get(booster_code, booster_code)}\n" if booster_code else ""

    text = (
        f"👤 <b>КАБИНЕТ КАППЕРА</b>\n\n"
        f"<blockquote>👤 Ник: <b>{user['username']}</b>\n"
        f"🆔 Твой ID: <code>{user['user_id']}</code> <i>(нажми для копирования)</i>\n"
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
    kb = profile_kb(len(active_bets), bonus_amt, len(unlocked), fav_club)
    return text, kb

@dp.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    user = await db_manager.get_user(message.from_user.id, message.from_user.username)
    active_bets = await db_manager.get_user_bets(message.from_user.id, active_only=True)
    text, kb = build_profile_View_data(user, active_bets)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    active_bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    text, kb = build_profile_View_data(user, active_bets)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

def nick_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Случайный ник", callback_data="nick_random")
    builder.button(text="🔄 Имя из Telegram", callback_data="nick_reset")
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
        f"• Напиши в чат любой свой псевдоним (3–16 символов).\n"
        f"• Или выбери случайный футбольный ник кнопкой ниже:"
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
        f"• Нажми «🎲 Случайный ник» еще раз, напиши свой в чат или вернись в кабинет:"
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
    ok, result_or_err = validate_custom_nickname(message.text or "")
    if not ok:
        await message.answer(f"⚠️ {result_or_err}\nПопробуй ввести другое имя:", reply_markup=nick_menu_kb(), parse_mode="HTML")
        return
    await db_manager.update_nickname(message.from_user.id, result_or_err)
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Вернуться в кабинет", callback_data="profile")
    await message.answer(f"✅ Псевдоним изменен на <b>{result_or_err}</b>!", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "roulette_menu")
async def process_roulette_menu(callback: CallbackQuery):
    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    today_str = now_msk().strftime("%Y-%m-%d")
    can_spin = user.get("last_spin") != today_str
    booster_code = user.get("active_booster") or ""
    booster_info = f"\n🚀 <b>Активен бустер:</b> {BOOSTER_NAMES.get(booster_code, '')}\n" if booster_code else ""

    text = (
        f"🎰 <b>ФУТБОЛЬНАЯ РУЛЕТКА УДАЧИ</b>\n\n"
        f"<blockquote>Бесплатное вращение доступно <b>1 раз в сутки</b>!</blockquote>"
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
        builder.button(text="⏳ Доступно завтра", callback_data="spin_cooldown")
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

    for frame_txt in [
        "🎰 <b>БАРАБАН НАБИРАЕТ СКОРОСТЬ...</b>\n\n<blockquote><code>[ 💰 +150 FC ] ➔ [ ⚡ Кэф-буст ] ➔ [ 💎 +750 FC ]</code></blockquote>",
        "🎰 <b>БАРАБАН ЗАМЕДЛЯЕТСЯ...</b>\n\n<blockquote><code>[ 🛡 Страховка ] ➔ [ 🔥 ДЖЕКПОТ ] ➔ [ 🎟 Билет ]</code></blockquote>"
    ]:
        try:
            await callback.message.edit_text(frame_txt, parse_mode="HTML")
            await asyncio.sleep(0.65)
        except Exception:
            pass

    res = await db_manager.spin_roulette_db(callback.from_user.id, chosen["coins"], chosen["booster"], chosen["respin"])
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

    lines, total_bonus_earned = [], 0
    for key, cfg in ACHIEVEMENTS_CONFIG.items():
        status_icon = "✅" if key in unlocked else "🔒"
        if key in unlocked:
            total_bonus_earned += cfg["reward"]
        lines.append(f"{status_icon} <b>{cfg['title']}</b> (<code>+{cfg['reward']} FC</code>)\n   <i>{cfg['desc']}</i>")

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
        f"Победная ставка на матч любимого клуба приносит <b>+10% к чистой прибыли</b>!</blockquote>\n"
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

# ================= ЕЖЕНЕДЕЛЬНЫЙ ФИКСИРОВАННЫЙ СУПЕРЭКСПРЕСС =================
@dp.callback_query(F.data == "superexpress_menu")
async def process_superexpress_menu(callback: CallbackQuery):
    db = await get_real_matches()
    round_key, weekly_matches = await db_manager.get_or_create_weekly_superexpress(db)
    builder = InlineKeyboardBuilder()

    if len(weekly_matches) < 6:
        builder.button(text="🏠 Главное меню", callback_data="back_to_main")
        await callback.message.edit_text("🎯 <b>СУПЕРЭКСПРЕСС НЕДЕЛИ</b>\n\nФормируется новый еженедельный тираж.", reply_markup=builder.as_markup(), parse_mode="HTML")
        return

    existing = await db_manager.get_superexpress_entry(callback.from_user.id, round_key)

    if existing:
        picks = json.loads(existing["picks_json"])
        lines = []
        for i, p in enumerate(picks, 1):
            sc_info = f" • Счет: <b>{p['final_score']}</b> ({'✅' if p.get('won') else '❌'})" if p.get("final_score") else ""
            lines.append(f"<b>{i}. {p['teams']}</b>\n   🎯 Выбор: <code>{p['pick_label']}</code>{sc_info}")

        if existing["status"] == "pending":
            status_txt = "⏳ В игре (прогноз зафиксирован на эту неделю, новый тираж — в пятницу)"
        else:
            status_txt = f"🏁 Рассчитан (Угадано: {existing['guessed']}/6 • Выплата: +{existing['payout']} FC). Следующий тираж — в пятницу!"

        text = (
            f"🎯 <b>ЕЖЕНЕДЕЛЬНЫЙ СУПЕРЭКСПРЕСС ({round_key.upper()})</b>\n\n"
            f"<blockquote>" + "\n".join(lines) + f"</blockquote>\n"
            f"📡 <b>Статус:</b> {status_txt}\n\n"
            f"🏆 <b>Призовой фонд:</b> 4/6 — <code>+500 FC</code> | 5/6 — <code>+2 500 FC</code> | 6/6 — <b><code>+10 000 FC</code></b>"
        )
        builder.button(text="🏠 Главное меню", callback_data="back_to_main")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await callback.answer()
        return

    uid = callback.from_user.id
    draft = SUPEREXPRESS_DRAFTS.get(uid, {})
    lines = []
    for idx, m in enumerate(weekly_matches):
        cur_pick = draft.get(idx, "")
        lbl = {"p1": "П1", "x": "Х", "p2": "П2"}.get(cur_pick, "—")
        lines.append(f"<b>{idx+1}. {m['teams']}</b> <i>({m['short_date']})</i> • Выбор: <b><code>{lbl}</code></b>")
        for code, btn_txt in [("p1", "П1"), ("x", "Х"), ("p2", "П2")]:
            mark = "✅ " if cur_pick == code else ""
            builder.button(text=f"{mark}#{idx+1} {btn_txt}", callback_data=f"se_pick:{idx}:{code}")

    if len(draft) == 6:
        builder.button(text="🔥 Зафиксировать купон недели (Бесплатно)", callback_data="se_submit")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(*([3, 3, 3, 3, 3, 3, 1, 1] if len(draft) == 6 else [3, 3, 3, 3, 3, 3, 1]))

    text = (
        f"🎯 <b>СУПЕРЭКСПРЕСС НЕДЕЛИ (1 РАЗ В НЕДЕЛЮ)</b>\n\n"
        f"<blockquote>Угадай исходы 6 главных матчей недели!\n"
        f"4/6: <b>+500 FC</b> • 5/6: <b>+2 500 FC</b> • 6/6: <b>+10 000 FC</b></blockquote>\n" +
        "\n".join(lines) + f"\n\n👇 <i>Выбери исходы кнопками ниже ({len(draft)}/6):</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("se_pick:"))
async def process_se_pick(callback: CallbackQuery):
    _, idx_str, code = callback.data.split(":")
    uid = callback.from_user.id
    draft = SUPEREXPRESS_DRAFTS.get(uid, {})
    draft[int(idx_str)] = code
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
    round_key, weekly_matches = await db_manager.get_or_create_weekly_superexpress(db)
    if len(weekly_matches) < 6:
        return
    if await db_manager.get_superexpress_entry(uid, round_key):
        await callback.answer("Ты уже участвуешь в тираже этой недели!", show_alert=True)
        return

    lbl_map = {"p1": "П1", "x": "Х", "p2": "П2"}
    picks_list = [
        {
            "event_id": m["event_id"],
            "league_slug": m["league_slug"],
            "teams": m["teams"],
            "pick_code": draft[idx],
            "pick_label": lbl_map[draft[idx]]
        }
        for idx, m in enumerate(weekly_matches)
    ]
    await db_manager.create_superexpress_entry(uid, round_key, picks_list)
    SUPEREXPRESS_DRAFTS.pop(uid, None)
    await callback.answer("🎉 Еженедельный Суперэкспресс принят!", show_alert=True)
    await process_superexpress_menu(callback)

# ================= РЕФЕРАЛЫ, АКТИВНЫЕ СТАВКИ, АРХИВ И ТОП-10 =================
@dp.callback_query(F.data == "referral_menu")
async def process_referral_menu(callback: CallbackQuery):
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await bot.get_me()
        BOT_USERNAME = me.username

    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['user_id']}"
    share_text = quote("⚽ Залетайте в AI_BET_BOT! Реальная футбольная линия, FUT-карточки, PvP-пенальти и турнир капперов.\n🎁 По моей ссылке стартовый банк 1 500 FC:")
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_text}"

    text = (
        f"🤝 <b>ПАРТНЕРСКАЯ ПРОГРАММА (+500 FC)</b>\n\n"
        f"<blockquote>👥 Приглашено друзей: <b><code>{user.get('referrals_count', 0)}</code></b>\n"
        f"💰 Заработано: <b><code>{user.get('referrals_count', 0) * 500} FC</code></b></blockquote>\n"
        f"• Тебе мгновенно начисляется <b><code>+500 FC</code></b> за каждого друга\n"
        f"• Друг получает повышенный стартовый банк <b><code>1 500 FC</code></b>\n\n"
        f"🔗 <b>Твоя ссылка (нажми для копирования):</b>\n<code>{ref_link}</code>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Отправить другу", url=share_url)
    builder.button(text="⬅️ Назад в кабинет", callback_data="profile")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "active_bets")
async def process_active_bets(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=True)
    builder = InlineKeyboardBuilder()

    if not bets:
        text = "⏳ <b>АКТИВНЫЕ СТАВКИ</b>\n\n<blockquote>Сейчас у тебя нет купонов в игре.</blockquote>\nОткрой любую лигу или «⚡ Экспресс дня», чтобы сделать ставку!"
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
                f"⏱ Расчет: <i>досрочно при пробитии в Live или ~{end_dt}</i></blockquote>"
            )
            builder.button(text=f"💸 CashOut купона #{b['bet_id']}", callback_data=f"cashout_ask:{b['bet_id']}")

        text = "⏳ <b>МОИ АКТИВНЫЕ КУПОНЫ В ИГРЕ:</b>\n\n" + "\n".join(lines)
        builder.button(text="📡 Обновить Live-счет и расчет", callback_data="check_live_status")

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
    bet_id, offer = int(bet_id_str), float(offer_str)
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
    settled_count, live_info = 0, []
    async with aiohttp.ClientSession() as session:
        for b in bets:
            res = await check_and_settle_real_bet(session, b)
            if res["settled"]:
                settled_count += 1
            else:
                live_info.append(f"#{b['bet_id']}:\n{res.get('live_summary', '')}")
    if settled_count > 0:
        await callback.answer(f"⚡ Рассчитано купонов (включая досрочные!): {settled_count}!", show_alert=True)
    else:
        clean_alert = re.sub(r"<.*?>", "", "\n".join(live_info))[:195]
        await callback.answer(f"📡 Live-радар:\n{clean_alert}", show_alert=True)
    await process_active_bets(callback)

@dp.callback_query(F.data == "archive_bets")
async def process_archive_bets(callback: CallbackQuery):
    bets = await db_manager.get_user_bets(callback.from_user.id, active_only=False)
    if not bets:
        text = "🗄 <b>АРХИВ СТАВОК ПУСТ</b>\n\n<blockquote>Сюда попадают все купоны после расчета.</blockquote>"
    else:
        lines = []
        for b in bets:
            st = b["status"]
            badge = f"✅ ВЫИГРЫШ (+{round(b['amount']*b['odds'], 1)} FC)" if st == "win" else (f"🔄 ВОЗВРАТ (+{b['amount']} FC)" if st == "push" else (f"💸 CASHOUT ({b.get('score_result', '')})" if st == "cashout" else f"❌ ПРОИГРЫШ (-{b['amount']} FC)"))
            events_multiline = format_bet_legs_multiline(b, with_result=True)
            lines.append(f"<blockquote>🎫 <b>Купон #{b['bet_id']}</b> — <b>{badge}</b>\n{events_multiline}\n💵 Сумма: <code>{b['amount']} FC</code> • Кэф: <code>{b['odds']}</code></blockquote>")
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
        lines.append(f"{place_str} {disp_name}{club_tag} — <b><code>{round(u['balance'], 1)} FC</code></b> <i>(Побед: {u['wins']})</i>")

    body = "\n".join(lines) if lines else "Рейтинг пока формируется."
    incog_btn_txt = "🟢 Инкогнито: ВКЛ" if is_incog else "🕶 Инкогнито: ВЫКЛ"
    builder = InlineKeyboardBuilder()
    builder.button(text=incog_btn_txt, callback_data="toggle_incognito")
    builder.button(text="👤 Кабинет", callback_data="profile")
    builder.button(text="🏠 В меню", callback_data="back_to_main")
    builder.adjust(2, 1)
    await callback.message.edit_text(f"🏆 <b>ТОП-10 КАППЕРОВ ПРОЕКТА</b>\n\n<blockquote>{body}</blockquote>", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "leaderboard")
async def process_leaderboard(callback: CallbackQuery):
    await render_leaderboard_view(callback)
    await callback.answer()

@dp.callback_query(F.data == "toggle_incognito")
async def process_toggle_incognito(callback: CallbackQuery):
    new_state = await db_manager.toggle_user_incognito(callback.from_user.id)
    msg = "🕶 Инкогнито ВКЛЮЧЕН: твой ник скрыт в Топ-10!" if new_state == 1 else "👀 Инкогнито ВЫКЛЮЧЕН: твой ник снова виден!"
    await callback.answer(msg, show_alert=True)
    await render_leaderboard_view(callback)

# ================= ЭКСПРЕСС ДНЯ И КОРЗИНА ЭКСПРЕССА =================
@dp.callback_query(F.data == "express_day")
async def process_express(callback: CallbackQuery):
    db = await get_real_matches()
    exp_data = build_daily_express_data(db)
    builder = InlineKeyboardBuilder()
    if not exp_data:
        builder.button(text="🏠 Главное меню", callback_data="back_to_main")
        await callback.message.edit_text("На ближайшие дни матчей не найдено.", reply_markup=builder.as_markup())
        return
    builder.button(text=f"🔥 Поставить на Экспресс (Кэф {exp_data['total_odd']})", callback_data="pick:express_day:all:exp")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await callback.message.edit_text(
        f"⚡ <b>ЭКСПРЕСС ДНЯ (ТОП-6 СОБЫТИЙ)</b>\n\n{exp_data['text']}\n\n👇 <i>Нажми кнопку ниже, чтобы поставить на весь экспресс:</i>",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("slipadd:"))
async def process_slip_add(callback: CallbackQuery):
    _, league_key, match_id, pick_code = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match or match.get("is_live"):
        await callback.answer("⛔ Матч уже идет в LIVE или начался!", show_alert=True)
        return
    mkt = evaluate_custom_market(match, pick_code)
    if not mkt:
        return
    uid = callback.from_user.id
    slip = [item for item in USER_SLIPS.get(uid, []) if item["event_id"] != match["event_id"]]
    if len(slip) >= 6:
        await callback.answer("⚠️ Максимум 6 матчей в одном экспрессе!", show_alert=True)
        return
    slip.append({
        "event_id": match["event_id"], "league_slug": match["league_slug"], "match_title": match["teams"],
        "pick_code": mkt["pick_code"], "pick": mkt["label"], "odds": mkt["odds"], "prob": mkt["prob"],
        "start_ts": match["start_ts"], "end_ts": match["end_ts"]
    })
    USER_SLIPS[uid] = slip
    await callback.answer(f"✅ Добавлено: {match['teams']} — {mkt['label']} ({mkt['odds']}). В купоне: {len(slip)}", show_alert=True)
    await render_match_card(callback.message, league_key, match_id, uid)

@dp.callback_query(F.data == "view_slip")
async def process_view_slip(callback: CallbackQuery):
    uid = callback.from_user.id
    slip = USER_SLIPS.get(uid, [])
    if not slip:
        await callback.answer("Корзина экспресса пуста!", show_alert=True)
        return
    total_odd, lines = 1.0, []
    for i, item in enumerate(slip):
        total_odd *= item["odds"]
        lines.append(f"<b>{i+1}. {item['match_title']}</b>\n   🎯 Исход: <code>{item['pick']}</code> • Кэф: <b><code>{item['odds']}</code></b>")
    total_odd = round(total_odd, 2)
    text = f"🧺 <b>ТВОЙ КУПОН ЭКСПРЕССА ({len(slip)} МАТЧЕЙ)</b>\n\n" + "\n\n".join(lines) + f"\n\n<blockquote>📈 <b>Общий коэффициент:</b> <code>{total_odd}</code></blockquote>"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✅ Оформить ставку (Кэф {total_odd})", callback_data="pick:custom_slip:all:exp")
    builder.button(text="🗑 Очистить", callback_data="clear_slip")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(1, 2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "clear_slip")
async def process_clear_slip(callback: CallbackQuery, state: FSMContext):
    USER_SLIPS.pop(callback.from_user.id, None)
    await callback.answer("🗑 Купон экспресса очищен!", show_alert=True)
    await process_back_main(callback, state)

# ================= КАРТОЧКА МАТЧА (ПРЕДСТОЯЩИЕ + 🔴 LIVE) =================
@dp.callback_query(F.data.startswith("refresh_league:"))
async def process_refresh_league(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    await callback.answer("📡 Синхронизация LIVE и расписания...")
    db = await get_real_matches(force_refresh=True)
    league_data = db.get(league_key, {})
    matches = league_data.get("matches", {})
    text = f"<b>{league_data.get('title', 'Лига')}</b>\n📅 <i>Матчи в прямом эфире (🔴 LIVE) и расписание (МСК):</i>" if matches else f"<b>{league_data.get('title', 'Лига')}</b>\n\n<blockquote>📅 На ближайшие дни матчей не найдено.</blockquote>"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")

@dp.callback_query(F.data.startswith("league:"))
async def process_league_select(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    league_key = callback.data.split(":")[1]
    db = await get_real_matches()
    league_data = db.get(league_key, {})
    matches = league_data.get("matches", {})
    text = f"<b>{league_data.get('title', 'Турнир')}</b>\n📅 <i>Матчи в прямом эфире (🔴 LIVE) и расписание (МСК):</i>" if matches else f"<b>{league_data.get('title', 'Турнир')}</b>\n\n<blockquote>📅 На ближайшие дни матчей не найдено. Нажми «🔄 Обновить».</blockquote>"
    await callback.message.edit_text(text, reply_markup=matches_kb(league_key, matches), parse_mode="HTML")
    await callback.answer()

async def render_match_card(message_obj: Message, league_key: str, match_id: str, user_id: int):
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        return False

    is_live = bool(match.get("is_live"))
    # Если матч в LIVE — подтягиваем свежий счет напрямую из summary API
    if is_live:
        async with aiohttp.ClientSession() as session:
            fresh = await fetch_real_match_result(session, match["league_slug"], str(match["event_id"]))
            if fresh.get("ok"):
                match["live_score"] = fresh["score_str"]
                match["live_detail"] = fresh["detail"] or "LIVE"

    user = await db_manager.get_user(user_id)
    fav_club = user.get("favorite_club") or ""
    fav_banner = f"\n⭐ <b>Матч любимого клуба ({fav_club}) • +10% к выплате!</b>" if (fav_club and fav_club in match["teams"]) else ""
    league_title, odds = db[league_key]["title"], match["odds"]
    probs = calculate_ai_probabilities(odds)

    cache_k = f"live_{match['event_id']}_{match.get('live_score', '')}" if is_live else match["event_id"]
    if cache_k not in AI_CACHE:
        await message_obj.edit_text(f"🧠 <i>ИИ анализирует матч {match['teams']}...</i>", parse_mode="HTML")

    if is_live:
        prompt = (
            f"Матч идет ПРЯМО СЕЙЧАС (LIVE). Турнир: {league_title}.\n"
            f"Матч: {match['home_team']} — {match['away_team']}. Текущий счет: {match['live_score']} ({match['live_detail']}).\n"
            f"Предматчевый потенциал xG: {match['exp_goals']}. Статистика сезона: {match['records_info']}.\n"
            f"Дай краткий живой комментарий эксперта (до 45 слов) в 2 пункта:\n"
            f"1. 🔴 Оценка текущего счета и хода встречи.\n"
            f"2. 📊 Чего ждать в оставшееся время матча по модели xG."
        )
        ai_verdict = await ask_ai_cached(cache_k, prompt, ttl=300) or smart_local_match_analysis(match, probs)
        header_status = f"🔴 <b>ПРЯМОЙ ЭФИР (LIVE • {match['live_detail']})</b>\n🔢 Текущий счет: <b><code>{match['live_score']}</code></b>"
    else:
        prompt = (
            f"Предстоящий матч. Турнир: {league_title}. Дата: {match['date']}.\n"
            f"Хозяева: {match['home_team']}. Гости: {match['away_team']}. Статистика: {match['records_info']}.\n"
            f"Ожидаемые голы xG: {match['exp_goals']}. Линия: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}, ТБ 1.5={odds['tb15']}, ТБ 2.5={odds['tb25']}, ОЗ(Да)={odds['btts']}.\n"
            f"Дай краткий разбор (до 50 слов) в 2 пункта:\n1. ⚔️ Тактика и атака.\n2. 🎯 Лучшая ставка из линии с кэфом."
        )
        ai_verdict = await ask_ai_cached(cache_k, prompt) or smart_local_match_analysis(match, probs)
        header_status = f"🕒 Начало: <code>{match['date']}</code>"

    text = (
        f"🏟 <b>{league_title}</b>\n"
        f"🏠 <b>{match['home_team']}</b>  vs  ✈️ <b>{match['away_team']}</b>\n"
        f"{header_status}{fav_banner}\n\n"
        f"<blockquote>📊 <b>Котировки 1Х2:</b> П1: <b><code>{odds['p1']}</code></b> ({probs['p1']}%) | Х: <b><code>{odds['x']}</code></b> ({probs['x']}%) | П2: <b><code>{odds['p2']}</code></b> ({probs['p2']}%)\n"
        f"⚽ <b>Потенциал xG:</b> <b><code>{match['exp_goals']}</code></b>  •  Прогноз счета ИИ: <b><code>{match['best_score']}</code></b></blockquote>\n"
        f"🤖 <b>Аналитика ИИ:</b>\n{ai_verdict}"
    )
    await message_obj.edit_text(text, reply_markup=match_outcomes_kb(league_key, match_id, odds, user_id, is_live=is_live), parse_mode="HTML")
    return True

@dp.callback_query(F.data.startswith("match:"))
async def process_match_select(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, league_key, match_id = callback.data.split(":")
    if not await render_match_card(callback.message, league_key, match_id, callback.from_user.id):
        await callback.answer("⛔ Этот матч уже завершен!", show_alert=True)
        return
    await callback.answer()

@dp.callback_query(F.data.startswith("stats_menu:"))
async def process_stats_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, league_key, match_id = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match:
        await callback.answer("⛔ Матч уже завершен!", show_alert=True)
        return
    hs, as_ = match["h_stats"], match["a_stats"]
    live_line = f"\n🔴 <b>Текущий счет в LIVE:</b> <b><code>{match['live_score']}</code></b> ({match['live_detail']})" if match.get("is_live") else ""
    text = (
        f"📊 <b>СВОДКА КОМАНД И ИТБ</b>\n\n🏟 <b>Арена:</b> {match['venue']}{live_line}\n\n"
        f"<blockquote>🏠 <b>{match['home_team']}</b>\n• Сезон: <code>{hs['record_str']}</code> ({hs['points']} очк.)\n• Форма: {hs['form_visual']} | xG: <b><code>{match['lam_h']}</code></b></blockquote>\n"
        f"<blockquote>✈️ <b>{match['away_team']}</b>\n• Сезон: <code>{as_['record_str']}</code> ({as_['points']} очк.)\n• Форма: {as_['form_visual']} | xG: <b><code>{match['lam_a']}</code></b></blockquote>"
    )
    await callback.message.edit_text(text, reply_markup=stats_and_itb_kb(match), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("totals_menu:"))
async def process_totals_menu(callback: CallbackQuery, state: FSMContext):
    _, league_key, match_id, direction = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match or match.get("is_live"):
        await callback.answer("⛔ Матч уже идет в LIVE!", show_alert=True)
        return
    await state.set_state(BetStates.waiting_for_custom_total)
    await state.update_data(league_key=league_key, match_id=match_id, direction=direction)
    dir_title = "📈 ТОТАЛ БОЛЬШЕ (ТБ)" if direction == "tb" else "📉 ТОТАЛ МЕНЬШЕ (ТМ)"
    text = (
        f"⚽ <b>{dir_title}</b>\n\n<blockquote>🏟 <b>{match['teams']}</b>\n📊 <b>Ожидаемые голы (xG):</b> <b><code>{match['exp_goals']}</code></b>\n"
        f"⚡ <i>Ставки на ТБ рассчитываются ДОСРОЧНО прямо во время матча, как только команды пробили тотал!</i></blockquote>\n"
        f"👇 <b>Выбери кнопкой ИЛИ напиши любое число в чат</b> (например: <code>2.5</code> или <code>3</code>):"
    )
    await callback.message.edit_text(text, reply_markup=totals_constructor_kb(match, direction), parse_mode="HTML")
    await callback.answer()

@dp.message(BetStates.waiting_for_custom_total)
async def process_custom_total_input(message: Message, state: FSMContext):
    data = await state.get_data()
    league_key, match_id, direction = data.get("league_key"), data.get("match_id"), data.get("direction", "tb")
    try:
        val = float((message.text or "").strip().replace(",", "."))
    except Exception:
        await message.answer("⚠️ Введи значение тотала числом (например: <code>1.5</code>, <code>2</code> или <code>3.5</code>):", parse_mode="HTML")
        return

    rounded_val = round(val * 2) / 2
    if rounded_val < 0.5 or rounded_val > 6.5:
        await message.answer("⚠️ Допустимый диапазон — от <code>0.5</code> до <code>6.5</code> голов:", parse_mode="HTML")
        return

    is_int = abs(rounded_val - round(rounded_val)) < 1e-5
    line_str = f"{int(round(rounded_val))}.0" if is_int else f"{rounded_val:.1f}"
    await state.clear()
    target_code = f"{league_key}-{match_id}-{direction}_{line_str}"
    info = await resolve_bet_target(target_code, message.from_user.id)
    if not info:
        await message.answer("⛔ Матч уже начался.", reply_markup=main_menu_kb(message.from_user.id))
        return

    user = await db_manager.get_user(message.from_user.id, message.from_user.username)
    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m.%Y в %H:%M МСК")
    text = (
        f"🎫 <b>ОФОРМЛЕНИЕ КУПОНА</b>\n\n<blockquote>{info['events_preview']}\n📈 <b>Коэффициент:</b> <b><code>{info['odds']}</code></b>\n"
        f"⏱ <b>Расчет:</b> <i>досрочно при заходе тотала или ~{end_str}</i></blockquote>\n💰 <b>Доступный баланс:</b> <code>{round(user['balance'], 1)} FC</code>\n\n"
        f"👇 <b>Выбери сумму ставки или добавь исход в Экспресс:</b>"
    )
    await message.answer(text, reply_markup=amount_selection_kb(target_code, user["balance"]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("extras_menu:"))
async def process_extras_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, league_key, match_id = callback.data.split(":")
    db = await get_real_matches()
    match = db.get(league_key, {}).get("matches", {}).get(match_id)
    if not match or match.get("is_live"):
        await callback.answer("⛔ Матч уже начался!", show_alert=True)
        return
    text = (
        f"🛡️ <b>ФОРЫ, ДВОЙНОЙ ШАНС И ОЗ</b>\n\n<blockquote>🏟 <b>{match['teams']}</b>\n"
        f"• <b>1Х / Х2</b> — команда не проиграет\n• <b>Фора (0)</b> — победа с возвратом при ничьей\n• <b>ОЗ: Да</b> — рассчитывается досрочно сразу после голов обеих команд!</blockquote>\n👇 <b>Выбери исход:</b>"
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
        preview_lines = [f"<b>{i+1}. {leg['teams']}</b>\n   🎯 <code>{leg['pick_label']}</code> (кэф <code>{leg['odds']}</code>)" for i, leg in enumerate(exp["legs"])]
        return {
            "match_title": exp["summary_title"], "pick": exp["summary_pick"], "events_preview": "\n".join(preview_lines),
            "odds": exp["total_odd"], "prob": exp["prob"], "end_ts": exp["end_ts"],
            "bet_type": "express", "legs_json": json.dumps(exp["legs"], ensure_ascii=False)
        }
    elif target_code == "custom-slip":
        slip = USER_SLIPS.get(user_id, [])
        if not slip:
            return None
        total_odd, comb_prob, max_ts = 1.0, 1.0, 0
        multiline_titles, preview_lines, legs = [], [], []
        for idx, s in enumerate(slip, 1):
            if s["start_ts"] <= now_ts:
                return None
            total_odd *= s["odds"]
            comb_prob *= (s["prob"] / 100.0)
            if s["end_ts"] > max_ts:
                max_ts = s["end_ts"]
            multiline_titles.append(f"{idx}. {s['match_title']} — {s['pick']} ({s['odds']})")
            preview_lines.append(f"<b>{idx}. {s['match_title']}</b>\n   🎯 <code>{s['pick']}</code> (кэф <code>{s['odds']}</code>)")
            legs.append({"league_slug": s["league_slug"], "event_id": s["event_id"], "teams": s["match_title"], "pick_code": s["pick_code"], "pick_label": s["pick"], "odds": s["odds"]})
        return {
            "match_title": f"Персональный экспресс ({len(slip)} матчей)", "pick": "\n".join(multiline_titles),
            "events_preview": "\n".join(preview_lines), "odds": round(total_odd, 2), "prob": round(comb_prob * 100, 1),
            "end_ts": max_ts, "bet_type": "express", "legs_json": json.dumps(legs, ensure_ascii=False)
        }
    else:
        l_key, m_id, p_code = target_code.split("-", 2)
        match = db.get(l_key, {}).get("matches", {}).get(m_id)
        if not match or match.get("is_live") or match["start_ts"] <= now_ts:
            return None
        mkt = evaluate_custom_market(match, p_code)
        if not mkt:
            return None
        legs = [{"league_slug": match["league_slug"], "event_id": match["event_id"], "teams": match["teams"], "pick_code": mkt["pick_code"], "pick_label": mkt["label"], "odds": mkt["odds"]}]
        return {
            "match_title": f"{match['teams']} ({match['short_date']})", "pick": mkt["label"],
            "events_preview": f"🏟 <b>Матч:</b> {match['teams']} ({match['short_date']})\n🎯 <b>Исход:</b> <code>{mkt['label']}</code>",
            "odds": mkt["odds"], "prob": mkt["prob"], "end_ts": match["end_ts"],
            "bet_type": "single", "legs_json": json.dumps(legs, ensure_ascii=False)
        }

@dp.callback_query(F.data.startswith("pick:"))
async def process_pick_outcome(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, p1, p2, p3 = callback.data.split(":")
    target_code = "express-day" if p1 == "express_day" else ("custom-slip" if p1 == "custom_slip" else f"{p1}-{p2}-{p3}")
    info = await resolve_bet_target(target_code, callback.from_user.id)
    if not info:
        await callback.answer("⛔ Матч уже начался или купон устарел!", show_alert=True)
        return

    user = await db_manager.get_user(callback.from_user.id, callback.from_user.username)
    end_str = datetime.fromtimestamp(info["end_ts"], tz=MSK_TZ).strftime("%d.%m.%Y в %H:%M МСК")
    booster_code = user.get("active_booster") or ""
    booster_note = f"\n🚀 <b>Будет применен бустер:</b> {BOOSTER_NAMES.get(booster_code, '')}" if booster_code else ""

    text = (
        f"🎫 <b>ОФОРМЛЕНИЕ КУПОНА</b>\n\n<blockquote>{info['events_preview']}\n📈 <b>Базовый кэф:</b> <b><code>{info['odds']}</code></b>\n"
        f"⏱ <b>Расчет:</b> <i>досрочно при заходе в Live или ~{end_str}</i></blockquote>{booster_note}\n💰 <b>Доступный баланс:</b> <code>{round(user['balance'], 1)} FC</code>\n\n"
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
        f"📈 <b>Итоговый кэф (с учетом FUT/Лаб):</b> <b><code>{res['final_odds']}</code></b>\n"
        f"💵 <b>Сумма ставки:</b> <code>{amount} FC</code>\n"
        f"💰 <b>Возможная выплата:</b> <b><code>{res['potential_win']} FC</code></b></blockquote>"
        f"{b_note}{fav_note}\n"
        f"🏦 <b>Остаток на балансе:</b> <code>{res['new_balance']} FC</code>\n"
        f"📡 <b>Расчет:</b> <i>мгновенно при пробитии в Live или ~{end_str}</i>"
    )

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    share_txt = quote(f"🎫 Мой купон #{bet_id} в AI_BET_BOT (Кэф {res['final_odds']})!\n💰 Выплата: {res['potential_win']} FC.\nЗаходи и получай 1 500 FC на старт:")
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_txt}"

    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Поделиться купоном", url=share_url)
    builder.button(text="⏳ Мои активные ставки", callback_data="active_bets")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
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
        callback.from_user.id, callback.from_user.username, info["match_title"], info["pick"],
        amount, info["odds"], info["prob"], info["end_ts"], info["bet_type"], info["legs_json"]
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
        f"✍️ <b>ВВОД СВОЕЙ СУММЫ СТАВКИ</b>\n\n<blockquote>💰 Доступный баланс: <b><code>{round(user['balance'], 1)} FC</code></b>\nМинимальная сумма: <code>10 FC</code></blockquote>\nНапиши в чат целое число:",
        reply_markup=builder.as_markup(), parse_mode="HTML"
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
        message.from_user.id, message.from_user.username, info["match_title"], info["pick"],
        amount, info["odds"], info["prob"], info["end_ts"], info["bet_type"], info["legs_json"]
    )
    if not res["ok"]:
        await message.answer(f"⚠️ {res['error']}\nВведи другую сумму:")
        return

    await state.clear()
    if target_code == "custom-slip":
        USER_SLIPS.pop(message.from_user.id, None)

    text, builder = await build_bet_accepted_response(message.from_user.id, res["bet_id"], info, amount, res)
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ================= РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ (/admin) =================
def is_admin(user_id: int) -> bool:
    global ADMIN_ID
    if ADMIN_ID == 0:
        ADMIN_ID = user_id
    return user_id == ADMIN_ID

def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Найти игрока / Узнать ID", callback_data="admin_lookup")
    builder.button(text="📋 Список игроков и их ID", callback_data="admin_users_list")
    builder.button(text="🎁 Выдать / Списать FC", callback_data="admin_gift")
    builder.button(text="⚡ Принудительный Live-расчет", callback_data="admin_force_settle")
    builder.button(text="📢 Рассылка всем", callback_data="admin_broadcast")
    builder.button(text="🔄 Обновить сводку", callback_data="admin_panel")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(1, 2, 1, 2, 1)
    return builder.as_markup()

def build_admin_user_dossier(u: dict) -> tuple[str, InlineKeyboardMarkup]:
    st_lvl = int(u.get("stadium_level") or 1)
    st_name = STADIUM_LEVELS.get(st_lvl, STADIUM_LEVELS[1])["name"]
    vip_str = "👑 Да" if int(u.get("is_vip") or 0) == 1 else "Нет"
    uid = u["user_id"]

    text = (
        f"🕵️‍♂️ <b>ДОСЬЕ ИГРОКА (АДМИН-ПРОСМОТР)</b>\n\n"
        f"<blockquote>👤 Никнейм: <b>{u['username']}</b>\n"
        f"🆔 ID (нажми для копирования): <code>{uid}</code>\n"
        f"💰 Баланс: <b><code>{round(u['balance'], 1)} FC</code></b>\n"
        f"👑 Статус VIP: <b>{vip_str}</b>\n"
        f"🏟 Арена: <b>Ур. {st_lvl} ({st_name})</b> | ИИ: <b>Ур. {u.get('lab_level', 1)}</b>\n"
        f"📊 Статистика: ✅ <code>{u['wins']}</code> | ❌ <code>{u['losses']}</code> | Профит: <code>{round(u['profit'], 1)} FC</code>\n"
        f"🤝 Рефералов: <code>{u.get('referrals_count', 0)}</code> | Побед PvP: <code>{u.get('pvp_wins', 0)}</code></blockquote>\n"
        f"👇 <b>Быстрые действия с игроком:</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ +1 000 FC", callback_data=f"adm_act:add1k:{uid}")
    builder.button(text="➕ +5 000 FC", callback_data=f"adm_act:add5k:{uid}")
    builder.button(text="👑 Переключить VIP", callback_data=f"adm_act:vip:{uid}")
    builder.button(text="🔄 Сбросить таймеры", callback_data=f"adm_act:reset:{uid}")
    builder.button(text="⬅️ Назад в Админ-панель", callback_data="admin_panel")
    builder.adjust(2, 2, 1)
    return text, builder.as_markup()

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    st = await db_manager.get_project_stats()
    text = (
        f"⚙️ <b>ПАНЕЛЬ УПРАВЛЕНИЯ ПРОЕКТОМ (ADMIN)</b>\n\n"
        f"<blockquote>👥 Игроков в базе: <b><code>{st['users']}</code></b>\n"
        f"🎫 Всего купонов: <b><code>{st['bets']}</code></b> (в игре: <b><code>{st['active_bets']}</code></b>)\n"
        f"⚔️ Открытых дуэлей PvP: <b><code>{st['open_pvp']}</code></b>\n"
        f"🏦 Суммарный банк: <b><code>{st['total_fc']} FC</code></b></blockquote>\n👇 Выбери инструмент:"
    )
    await message.answer(text, reply_markup=admin_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "admin_panel")
async def process_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        return
    st = await db_manager.get_project_stats()
    text = (
        f"⚙️ <b>ПАНЕЛЬ УПРАВЛЕНИЯ ПРОЕКТОМ (ADMIN)</b>\n\n"
        f"<blockquote>👥 Игроков в базе: <b><code>{st['users']}</code></b>\n"
        f"🎫 Всего купонов: <b><code>{st['bets']}</code></b> (в игре: <b><code>{st['active_bets']}</code></b>)\n"
        f"⚔️ Открытых дуэлей PvP: <b><code>{st['open_pvp']}</code></b>\n"
        f"🏦 Суммарный банк: <b><code>{st['total_fc']} FC</code></b></blockquote>\n👇 Выбери инструмент:"
    )
    await callback.message.edit_text(text, reply_markup=admin_kb(), parse_mode="HTML")
    await callback.answer("Сводка обновлена")

@dp.callback_query(F.data == "admin_users_list")
async def process_admin_users_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    users = await db_manager.get_users_list_admin(15)
    lines = []
    builder = InlineKeyboardBuilder()
    for i, u in enumerate(users, 1):
        lines.append(
            f"<b>{i}. {u['username']}</b> — ID: <code>{u['user_id']}</code> • <b><code>{round(u['balance'], 1)} FC</code></b>"
        )
        builder.button(text=f"🕵️‍♂️ {u['username']}", callback_data=f"adm_view:{u['user_id']}")

    builder.button(text="⬅️ Назад в Админку", callback_data="admin_panel")
    rows = [2] * (len(users) // 2)
    if len(users) % 2 == 1:
        rows.append(1)
    rows.append(1)
    builder.adjust(*rows)

    text = (
        "📋 <b>СПИСОК ИГРОКОВ И ИХ ID</b>\n"
        "<i>Нажми на любой ID в тексте, чтобы скопировать его, или открой досье кнопкой ниже:</i>\n\n"
        "<blockquote>" + ("\n".join(lines) if lines else "Нет игроков") + "</blockquote>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_view:"))
async def process_adm_view_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    target_uid = int(callback.data.split(":")[1])
    u = await db_manager.fetchrow("SELECT * FROM users WHERE user_id = $1", target_uid)
    if not u:
        await callback.answer("Игрок не найден", show_alert=True)
        return
    text, kb = build_admin_user_dossier(u)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_act:"))
async def process_adm_quick_action(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    _, action, uid_str = callback.data.split(":")
    target_uid = int(uid_str)

    if action == "add1k":
        await db_manager.add_balance_to_user(target_uid, 1000.0)
        await callback.answer("✅ Начислено +1 000 FC!", show_alert=True)
    elif action == "add5k":
        await db_manager.add_balance_to_user(target_uid, 5000.0)
        await callback.answer("✅ Начислено +5 000 FC!", show_alert=True)
    elif action == "vip":
        new_v = await db_manager.toggle_user_vip_admin(target_uid)
        await callback.answer(f"👑 VIP статус: {'ВКЛЮЧЕН' if new_v == 1 else 'ВЫКЛЮЧЕН'}!", show_alert=True)
    elif action == "reset":
        await db_manager.reset_user_cooldowns_admin(target_uid)
        await callback.answer("🔄 Таймеры бонуса, рулетки и арены сброшены!", show_alert=True)

    u = await db_manager.fetchrow("SELECT * FROM users WHERE user_id = $1", target_uid)
    if u:
        text, kb = build_admin_user_dossier(u)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_lookup")
async def process_admin_lookup_ask(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_user_lookup)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text(
        "🔍 <b>ОПРЕДЕЛЕНИЕ ID И ПОИСК ДОСЬЕ ИГРОКА</b>\n\n"
        "Напиши в чат <b>Никнейм</b> (можно часть ника) или <b>ID игрока</b>:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_lookup)
async def process_admin_lookup_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    found = await db_manager.search_users_admin(message.text or "")
    if not found:
        await message.answer("⚠️ Игроки по такому запросу не найдены. Попробуй ввести другой ник или ID:")
        return

    await state.clear()
    if len(found) == 1:
        text, kb = build_admin_user_dossier(found[0])
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    lines = []
    builder = InlineKeyboardBuilder()
    for u in found:
        lines.append(f"• <b>{u['username']}</b> — ID: <code>{u['user_id']}</code> ({round(u['balance'], 1)} FC)")
        builder.button(text=f"🕵️‍♂️ {u['username']}", callback_data=f"adm_view:{u['user_id']}")
    builder.button(text="⬅️ В Админку", callback_data="admin_panel")
    builder.adjust(2)
    await message.answer(
        "🔍 <b>Найдено несколько игроков:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_force_settle")
async def process_admin_force_settle(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer("⚡ Запущена проверка всех активных купонов и LIVE-матчей...")
    pending_bets = await db_manager.get_all_pending_bets()
    settled_cnt = 0
    if pending_bets:
        async with aiohttp.ClientSession() as session:
            for b in pending_bets:
                r = await check_and_settle_real_bet(session, b)
                if r.get("settled"):
                    settled_cnt += 1
    await callback.answer(f"✅ Проверено купонов: {len(pending_bets)}. Рассчитано сейчас: {settled_cnt}!", show_alert=True)
    await process_admin_panel(callback, state)

@dp.callback_query(F.data == "admin_broadcast")
async def process_admin_broadcast_ask(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_broadcast)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data="admin_panel")
    await callback.message.edit_text("📢 <b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n\nОтправь текст сообщения в чат:", reply_markup=builder.as_markup(), parse_mode="HTML")
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
        "🎁 <b>ИЗМЕНЕНИЕ БАЛАНСА ИГРОКА</b>\n\n"
        "Отправь через пробел <code>ID_или_Ник Сумму</code> (для списания укажи минус, например: <code>123456789 -500</code>):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_for_gift_data)
async def process_admin_gift_exec(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").strip().rsplit(maxsplit=1)
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("⚠️ Введи корректно через пробел: <code>ID_или_Ник Сумма</code>", parse_mode="HTML")
        return

    target_user = await db_manager.find_user_by_query(parts[0])
    if not target_user:
        await message.answer("⚠️ Игрок с таким ID или Ником не найден.", reply_markup=admin_kb(), parse_mode="HTML")
        return

    add_amt = float(parts[1])
    target_uid = target_user["user_id"]
    ok = await db_manager.add_balance_to_user(target_uid, add_amt)
    await state.clear()
    if ok:
        if add_amt > 0:
            try:
                await bot.send_message(target_uid, f"🎁 Администратор начислил тебе <b><code>+{add_amt} FC</code></b> на баланс!", parse_mode="HTML")
            except Exception:
                pass
        await message.answer(
            f"✅ Баланс игрока <b>{target_user['username']}</b> (ID: <code>{target_uid}</code>) изменен на <b>{add_amt} FC</b>!",
            reply_markup=admin_kb(),
            parse_mode="HTML"
        )

# ================= ВЕБ-СЕРВЕР + ЗАЩИЩЕННОЕ ЯДРО WEBAPP, 12 КОНТЕЙНЕРОВ, P2P В БД И ПРОСМОТР ПРОФИЛЕЙ =================
from collections import defaultdict
from aiogram.types import MenuButtonWebApp, WebAppInfo, BufferedInputFile

WEBAPP_BASE_URL = (os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
}

# 1. МИНИМАЛИСТИЧНОЕ МЕНЮ БОТА В ЧАТЕ + КОМАНДА /BACKUP ДЛЯ АДМИНА
def minimalist_chat_menu_kb(user_id: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if WEBAPP_BASE_URL.startswith("https://"):
        builder.button(
            text="🎄 Открыть игру (Web-App)",
            web_app=WebAppInfo(url=f"{WEBAPP_BASE_URL}/app?uid={user_id}")
        )
    builder.button(text="👤 Мой профиль и ID", callback_data="chat_only_profile")
    builder.button(text="⏳ Активные ставки", callback_data="chat_only_active_bets")
    if user_id == ADMIN_ID:
        builder.button(text="⚙️ Админ-панель", callback_data="admin_panel")
        builder.button(text="💾 Скачать бэкап БД", callback_data="admin_make_backup")
        builder.adjust(1, 2, 2)
    else:
        builder.adjust(1, 2)
    return builder.as_markup()

globals()["main_menu_kb"] = minimalist_chat_menu_kb

async def send_database_backup_to_admin(trigger_note: str = "Ручной запрос"):
    """Выгружает полную копию БД (игроки, активные ставки, лоты P2P) в JSON-файл и отправляет админу"""
    try:
        users_rows = await db_manager.fetch("SELECT * FROM users")
        bets_rows = await db_manager.fetch("SELECT * FROM bets WHERE status = 'pending'")
        p2p_rows = await db_manager.fetch("SELECT * FROM p2p_lots")

        backup_data = {
            "created_at": now_msk().strftime("%Y-%m-%d %H:%M:%S MSK"),
            "trigger": trigger_note,
            "users_count": len(users_rows),
            "pending_bets_count": len(bets_rows),
            "p2p_lots_count": len(p2p_rows),
            "users": [dict(r) for r in users_rows],
            "pending_bets": [dict(r) for r in bets_rows],
            "p2p_lots": [dict(r) for r in p2p_rows]
        }
        raw_bytes = json.dumps(backup_data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        fname = f"backup_aibet_{now_msk().strftime('%Y%m%d_%H%M')}.json"
        doc = BufferedInputFile(raw_bytes, filename=fname)
        await bot.send_document(
            ADMIN_ID,
            document=doc,
            caption=(
                f"💾 <b>РЕЗЕРВНАЯ КОПИЯ БАЗЫ ДАННЫХ</b>\n\n"
                f"<blockquote>📌 Тип: <b>{trigger_note}</b>\n"
                f"👥 Игроков в базе: <b>{len(users_rows)}</b>\n"
                f"🎫 Активных купонов: <b>{len(bets_rows)}</b>\n"
                f"🌐 Лотов на P2P-Бирже: <b>{len(p2p_rows)}</b>\n"
                f"🕒 Время: <code>{backup_data['created_at']}</code></blockquote>"
            ),
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logging.warning(f"Ошибка создания бэкапа: {e}")
        return False

@dp.message(Command("backup"))
async def cmd_admin_backup(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("⏳ Формирую резервную копию базы данных PostgreSQL...")
    ok = await send_database_backup_to_admin("Команда /backup")
    if not ok:
        await message.answer("⚠️ Не удалось сформировать бэкап, проверь логи.")

@dp.callback_query(F.data == "admin_make_backup")
async def cb_admin_backup(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Только для администратора!", show_alert=True)
    await callback.answer("⏳ Выгружаю базу в файл...")
    await send_database_backup_to_admin("Кнопка из меню")

@dp.callback_query(F.data == "chat_only_profile")
async def process_chat_only_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    u = await db_manager.get_user(uid, callback.from_user.username)
    st = parse_user_fut_state(u)
    is_vip_now = is_user_vip_active(u, st)
    rank_name, _ = get_user_rank_info(u["balance"], 1 if is_vip_now else 0)
    total = u["wins"] + u["losses"]
    wr = round((u["wins"] / total) * 100, 1) if total > 0 else 0.0
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ КАППЕРА</b>\n\n"
        f"<blockquote>🏷 Никнейм: <b>{'👑 ' if is_vip_now else ''}{u['username']}</b>\n"
        f"🆔 Твой ID: <code>{uid}</code> <i>(нажми для копирования)</i>\n"
        f"🏅 Ранг: <b>{rank_name}</b>\n"
        f"💰 Баланс: <b><code>{round(u['balance'], 1)} FC</code></b>\n"
        f"💎 Капитал Форбс: <b><code>{calculate_forbes_net_worth(u, st)} FC</code></b>\n"
        f"📊 Статистика: <b>{u['wins']}В / {u['losses']}П ({wr}%)</b>\n"
        f"📈 Чистый профит: <b><code>{round(u['profit'], 1)} FC</code></b></blockquote>\n\n"
        f"📱 <i>Все ставки, 12 контейнеров, VIP-Клуб и просмотр профилей других игроков доступны в Web-App!</i>"
    )
    await callback.message.edit_text(text, reply_markup=minimalist_chat_menu_kb(uid), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "chat_only_active_bets")
async def process_chat_only_active_bets(callback: CallbackQuery):
    uid = callback.from_user.id
    bets = await db_manager.get_user_bets(uid, active_only=True)
    if not bets:
        text = "⏳ <b>АКТИВНЫЕ СТАВКИ</b>\n\n<blockquote>У тебя сейчас нет активных купонов в игре. Открой Web-App, чтобы собрать ординар или экспресс!</blockquote>"
    else:
        lines = []
        for b in bets[:8]:
            ins_tag = " 🛡[Застрахован 50%]" if b.get("booster_used") == "insure50" else ""
            lines.append(
                f"🎫 <b>Купон #{b['bet_id']}</b> (Кэф <code>{b['odds']}</code>){ins_tag}\n"
                f"⚽ {b['match_title']}\n"
                f"🎯 Исход: <code>{b['pick']}</code>\n"
                f"💵 Ставка: <code>{b['amount']} FC</code> ➔ Выплата: <b><code>{round(b['amount']*b['odds'], 1)} FC</code></b>"
            )
        text = "⏳ <b>ТВОИ АКТИВНЫЕ СТАВКИ В ИГРЕ:</b>\n\n<blockquote>" + "\n\n".join(lines) + "</blockquote>"
    await callback.message.edit_text(text, reply_markup=minimalist_chat_menu_kb(uid), parse_mode="HTML")
    await callback.answer()

# 2. ЭТАЛОННЫЙ СЛОВАРЬ КЛУБОВ И СБОРНЫХ (С МГНОВЕННЫМ ХЭШ-КЭШЕМ)
EXACT_CLUB_DICTIONARY = {
    "CSKA Moscow": "ЦСКА", "PFC CSKA Moscow": "ЦСКА", "Spartak Moscow": "Спартак", "FC Spartak Moscow": "Спартак",
    "Zenit St Petersburg": "Зенит", "FC Zenit Saint Petersburg": "Зенит", "Zenit": "Зенит",
    "Krasnodar": "Краснодар", "FC Krasnodar": "Краснодар", "Dynamo Moscow": "Динамо Москва", "FC Dynamo Moscow": "Динамо Москва",
    "Lokomotiv Moscow": "Локомотив", "FC Lokomotiv Moscow": "Локомотив", "Rostov": "Ростов", "FC Rostov": "Ростов",
    "Rubin Kazan": "Рубин", "FC Rubin Kazan": "Рубин", "Krylia Sovetov": "Крылья Советов", "PFC Krylia Sovetov Samara": "Крылья Советов",
    "Akhmat Grozny": "Ахмат", "RFK Akhmat Grozny": "Ахмат", "Pari Nizhny Novgorod": "Пари НН", "FC Pari Nizhny Novgorod": "Пари НН",
    "Fakel Voronezh": "Факел", "FC Fakel Voronezh": "Факел", "Orenburg": "Оренбург", "FC Orenburg": "Оренбург",
    "Khimki": "Химки", "FC Khimki": "Химки", "Akron Togliatti": "Акрон", "FC Akron Togliatti": "Акрон",
    "Dynamo Makhachkala": "Динамо Махачкала", "FC Dynamo Makhachkala": "Динамо Махачкала",
    "Baltika Kaliningrad": "Балтика", "Torpedo Moscow": "Торпедо", "Ural Yekaterinburg": "Урал", "Sochi": "Сочи",
    "Arsenal": "Арсенал", "Aston Villa": "Астон Вилла", "Bournemouth": "Борнмут", "AFC Bournemouth": "Борнмут",
    "Brentford": "Брентфорд", "Brighton & Hove Albion": "Брайтон", "Brighton and Hove Albion": "Брайтон", "Brighton": "Брайтон",
    "Chelsea": "Челси", "Crystal Palace": "Кристал Пэлас", "Everton": "Эвертон", "Fulham": "Фулхэм",
    "Ipswich Town": "Ипсвич Таун", "Ipswich": "Ипсвич Таун", "Leicester City": "Лестер Сити", "Leicester": "Лестер Сити",
    "Liverpool": "Ливерпуль", "Manchester City": "Манчестер Сити", "Man City": "Манчестер Сити",
    "Manchester United": "Манчестер Юнайтед", "Man United": "Манчестер Юнайтед", "Newcastle United": "Ньюкасл", "Newcastle": "Ньюкасл",
    "Nottingham Forest": "Ноттингем Форест", "Southampton": "Саутгемптон", "Tottenham Hotspur": "Тоттенхэм", "Tottenham": "Тоттенхэм",
    "West Ham United": "Вест Хэм", "West Ham": "Вест Хэм", "Wolverhampton Wanderers": "Вулверхэмптон", "Wolves": "Вулверхэмптон",
    "Leeds United": "Лидс Юнайтед", "Leeds": "Лидс Юнайтед", "Burnley": "Бёрнли", "Sunderland": "Сандерленд",
    "Sheffield United": "Шеффилд Юнайтед", "Sheffield Wednesday": "Шеффилд Уэнсдей", "West Bromwich Albion": "Вест Бромвич",
    "Middlesbrough": "Мидлсбро", "Norwich City": "Норвич Сити", "Coventry City": "Ковентри Сити", "Watford": "Уотфорд",
    "Blackburn Rovers": "Блэкберн Роверс", "Bristol City": "Бристоль Сити", "Hull City": "Халл Сити", "Stoke City": "Сток Сити",
    "Swansea City": "Суонси Сити", "Millwall": "Миллуолл", "Queens Park Rangers": "КПР", "QPR": "КПР",
    "Preston North End": "Престон", "Cardiff City": "Кардифф Сити", "Derby County": "Дерби Каунти",
    "Portsmouth": "Портсмут", "Oxford United": "Оксфорд Юнайтед", "Plymouth Argyle": "Плимут Аргайл", "Luton Town": "Лутон Таун",
    "Real Madrid": "Реал Мадрид", "Barcelona": "Барселона", "FC Barcelona": "Барселона",
    "Atlético Madrid": "Атлетико Мадрид", "Atletico Madrid": "Атлетико Мадрид", "Club Atlético de Madrid": "Атлетико Мадрид",
    "Athletic Club": "Атлетик Бильбао", "Athletic Bilbao": "Атлетик Бильбао", "Real Sociedad": "Реал Сосьедад",
    "Real Betis": "Реал Бетис", "Villarreal": "Вильярреал", "Valencia": "Валенсия", "Sevilla": "Севилья",
    "Girona": "Жирона", "Celta Vigo": "Сельта", "RC Celta": "Сельта", "Osasuna": "Осасуна", "CA Osasuna": "Осасуна",
    "Getafe": "Хетафе", "Rayo Vallecano": "Райо Вальекано", "Mallorca": "Мальорка", "RCD Mallorca": "Мальорка",
    "Las Palmas": "Лас-Пальмас", "UD Las Palmas": "Лас-Пальмас", "Alavés": "Алавес", "Deportivo Alavés": "Алавес", "Alaves": "Алавес",
    "Espanyol": "Эспаньол", "RCD Espanyol": "Эспаньол", "Leganés": "Леганес", "CD Leganés": "Леганес", "Leganes": "Леганес",
    "Real Valladolid": "Реал Вальядолид", "Valladolid": "Реал Вальядолид",
    "Internazionale": "Интер", "Inter Milan": "Интер", "FC Internazionale Milano": "Интер",
    "AC Milan": "Милан", "Milan": "Милан", "Juventus": "Ювентус", "Napoli": "Наполи", "SSC Napoli": "Наполи",
    "AS Roma": "Рома", "Roma": "Рома", "Lazio": "Лацио", "SS Lazio": "Лацио", "Atalanta": "Аталанта",
    "Fiorentina": "Фиорентина", "ACF Fiorentina": "Фиорентина", "Bologna": "Болонья", "Torino": "Торино",
    "Udinese": "Удинезе", "Genoa": "Дженоа", "Como": "Комо", "Como 1907": "Комо", "Parma": "Парма",
    "Hellas Verona": "Верона", "Verona": "Верона", "Empoli": "Эмполи", "Cagliari": "Кальяри",
    "Lecce": "Лечче", "US Lecce": "Лечче", "Monza": "Монца", "AC Monza": "Монца", "Venezia": "Венеция",
    "Bayern Munich": "Бавария", "FC Bayern Munich": "Бавария", "Borussia Dortmund": "Боруссия Дортмунд",
    "Bayer Leverkusen": "Байер Леверкузен", "Bayer 04 Leverkusen": "Байер Леверкузен", "RB Leipzig": "РБ Лейпциг",
    "VfB Stuttgart": "Штутгарт", "Stuttgart": "Штутгарт", "Eintracht Frankfurt": "Айнтрахт Франкфурт",
    "SC Freiburg": "Фрайбург", "Freiburg": "Фрайбург", "TSG Hoffenheim": "Хоффенхайм", "Hoffenheim": "Хоффенхайм",
    "Werder Bremen": "Вердер Бремен", "SV Werder Bremen": "Вердер Бремен", "Heidenheim": "Хайденхайм", "1. FC Heidenheim 1846": "Хайденхайм",
    "FC Augsburg": "Аугсбург", "Augsburg": "Аугсбург", "VfL Wolfsburg": "Вольфсбург", "Wolfsburg": "Вольфсбург",
    "Borussia Mönchengladbach": "Боруссия Мёнхенгладбах", "Borussia Monchengladbach": "Боруссия Мёнхенгладбах",
    "Mainz": "Майнц", "1. FSV Mainz 05": "Майнц", "Mainz 05": "Майнц", "1. FC Union Berlin": "Унион Берлин", "Union Berlin": "Унион Берлин",
    "VfL Bochum": "Бохум", "Bochum": "Бохум", "FC St. Pauli": "Санкт-Паули", "St. Pauli": "Санкт-Паули",
    "Holstein Kiel": "Хольштайн Киль", "Hamburger SV": "Гамбург", "FC Cologne": "Кёльн", "1. FC Köln": "Кёльн",
    "Paris Saint-Germain": "ПСЖ", "PSG": "ПСЖ", "AS Monaco": "Монако", "Monaco": "Монако",
    "Marseille": "Марсель", "Olympique de Marseille": "Марсель", "Lille": "Лилль", "LOSC Lille": "Лилль",
    "Lyon": "Лион", "Olympique Lyonnais": "Лион", "Nice": "Ницца", "OGC Nice": "Ницца",
    "Lens": "Ланс", "RC Lens": "Ланс", "Rennes": "Ренн", "Stade Rennais": "Ренн",
    "Stade Brestois 29": "Брест", "Stade Brestois": "Брест", "Brest": "Брест",
    "Reims": "Реймс", "Stade de Reims": "Реймс", "Strasbourg": "Страсбур", "RC Strasbourg Alsace": "Страсбур",
    "Toulouse": "Тулуза", "Montpellier": "Монпелье", "Nantes": "Нант", "FC Nantes": "Нант",
    "Auxerre": "Осер", "AJ Auxerre": "Осер", "Angers": "Анже", "Angers SCO": "Анже",
    "Saint-Étienne": "Сент-Этьен", "AS Saint-Étienne": "Сент-Этьен", "AS Saint-Etienne": "Сент-Этьен", "Le Havre": "Гавр", "Le Havre AC": "Гавр",
    "Sporting CP": "Спортинг", "Sporting Lisbon": "Спортинг", "Benfica": "Бенфика", "SL Benfica": "Бенфика",
    "FC Porto": "Порту", "Porto": "Порту", "SC Braga": "Брага", "Braga": "Брага",
    "Vitória de Guimarães": "Витория Гимарайнш", "Vitoria Guimaraes": "Витория Гимарайнш",
    "Famalicão": "Фамаликан", "Famalicao": "Фамаликан", "Rio Ave": "Риу Аве", "Boavista": "Боавишта",
    "Moreirense": "Морейренсе", "Santa Clara": "Санта-Клара", "Gil Vicente": "Жил Висенте",
    "Casa Pia": "Каза Пия", "Estoril": "Эшторил", "Arouca": "Арока", "Nacional": "Насьонал", "Farense": "Фаренсе",
    "PSV Eindhoven": "ПСВ Эйндховен", "PSV": "ПСВ Эйндховен", "Feyenoord": "Фейеноорд", "Ajax": "Аякс", "AFC Ajax": "Аякс",
    "AZ Alkmaar": "АЗ Алкмар", "AZ": "АЗ Алкмар", "FC Twente": "Твенте", "Twente": "Твенте", "FC Utrecht": "Утрехт",
    "Go Ahead Eagles": "Гоу Эхед Иглс", "Fortuna Sittard": "Фортуна Ситтард", "NEC Nijmegen": "НЕК Неймеген",
    "SC Heerenveen": "Херенвен", "Heerenveen": "Херенвен", "PEC Zwolle": "Зволле", "NAC Breda": "НАК Бреда",
    "Willem II": "Виллем II", "FC Groningen": "Гронинген", "Heracles Almelo": "Хераклес",
    "Sparta Rotterdam": "Спарта Роттердам", "Almere City": "Алмере Сити", "RKC Waalwijk": "РКК Валвейк",
    "Galatasaray": "Галатасарай", "Fenerbahce": "Фенербахче", "Fenerbahçe": "Фенербахче",
    "Besiktas": "Бешикташ", "Beşiktaş": "Бешикташ", "Trabzonspor": "Трабзонспор",
    "Istanbul Basaksehir": "Башакшехир", "Basaksehir": "Башакшехир", "Başakşehir": "Башакшехир",
    "Samsunspor": "Самсунспор", "Antalyaspor": "Антальяспор", "Eyüpspor": "Эюпспор", "Eyupspor": "Эюпспор",
    "Göztepe": "Гёзтепе", "Goztepe": "Гёзтепе", "Sivasspor": "Сивасспор", "Kasımpaşa": "Касымпаша", "Kasimpasa": "Касымпаша",
    "Konyaspor": "Коньяспор", "Alanyaspor": "Аланьяспор", "Çaykur Rizespor": "Ризеспор", "Rizespor": "Ризеспор",
    "Gaziantep FK": "Газиантеп", "Kayserispor": "Кайсериспор", "Bodrum FK": "Бодрумспор", "Hatayspor": "Хатайспор", "Adana Demirspor": "Адана Демирспор",
    "Flamengo": "Фламенго", "Palmeiras": "Палмейрас", "Botafogo": "Ботафого", "São Paulo": "Сан-Паулу", "Sao Paulo": "Сан-Паулу",
    "Corinthians": "Коринтианс", "Fluminense": "Флуминенсе", "Grêmio": "Гремио", "Gremio": "Гремио",
    "Internacional": "Интернасьонал", "Atlético Mineiro": "Атлетико Минейро", "Atletico Mineiro": "Атлетико Минейро",
    "Cruzeiro": "Крузейро", "Vasco da Gama": "Васко да Гама", "Santos": "Сантос", "Fortaleza": "Форталеза",
    "Bahia": "Баия", "EC Vitória": "Витория Салвадор", "Juventude": "Жувентуде", "Red Bull Bragantino": "РБ Брагантино",
    "Athletico Paranaense": "Атлетико Паранаэнсе", "Criciúma": "Крисиума", "Cuiabá": "Куяба", "Atlético Goianiense": "Атлетико Гоияниенсе",
    "Celtic": "Селтик", "Rangers": "Рейнджерс", "Club Brugge": "Брюгге", "Anderlecht": "Андерлехт", "RSC Anderlecht": "Андерлехт",
    "Shakhtar Donetsk": "Шахтёр Донецк", "Dynamo Kyiv": "Динамо Киев", "Red Bull Salzburg": "РБ Зальцбург", "FC Salzburg": "РБ Зальцбург",
    "Sturm Graz": "Штурм Грац", "SK Sturm Graz": "Штурм Грац", "Sparta Prague": "Спарта Прага", "Slavia Prague": "Славия Прага",
    "Olympiacos": "Олимпиакос", "PAOK": "ПАОК", "Panathinaikos": "Панатинаикос", "AEK Athens": "АЕК Афины",
    "Dinamo Zagreb": "Динамо Загреб", "GNK Dinamo Zagreb": "Динамо Загреб", "Young Boys": "Янг Бойз", "BSC Young Boys": "Янг Бойз",
    "Crvena Zvezda": "Црвена Звезда", "Red Star Belgrade": "Црвена Звезда", "Slovan Bratislava": "Слован Братислава",
    "Bodø/Glimt": "Будё-Глимт", "Bodo/Glimt": "Будё-Глимт", "FC Midtjylland": "Мидтьюлланд", "Midtjylland": "Мидтьюлланд",
    "FCSB": "ФКСБ Стяуа", "IF Elfsborg": "Эльфсборг", "Elfsborg": "Эльфсборг", "Malmö FF": "Мальмё", "Malmo FF": "Мальмё",
    "Qarabağ": "Карабах", "Qarabag": "Карабах", "Ludogorets Razgrad": "Лудогорец", "Ludogorets": "Лудогорец",
    "Ferencváros": "Ференцварош", "Ferencvaros": "Ференцварош", "Maccabi Tel Aviv": "Маккаби Тель-Авив",
    "Viktoria Plzeň": "Виктория Пльзень", "Viktoria Plzen": "Виктория Пльзень", "RFS": "РФШ Рига", "Rigas FS": "РФШ Рига",
    "Union Saint-Gilloise": "Юнион Сент-Жиллуа", "Union SG": "Юнион Сент-Жиллуа", "Legia Warsaw": "Легия Варшава",
    "Jagiellonia Białystok": "Ягеллония", "Jagiellonia Bialystok": "Ягеллония", "Heart of Midlothian": "Хартс", "Hearts": "Хартс",
    "FC Astana": "Астана", "Astana": "Астана", "Rapid Wien": "Рапид Вена", "SK Rapid": "Рапид Вена", "LASK": "ЛАСК",
    "KAA Gent": "Гент", "Gent": "Гент", "Cercle Brugge": "Серкль Брюгге", "Molde": "Мольде", "Molde FK": "Мольде",
    "Djurgårdens IF": "Юргорден", "Djurgarden": "Юргорден", "FC Copenhagen": "Копенгаген", "Copenhagen": "Копенгаген",
    "FC Lugano": "Лугано", "Lugano": "Лугано", "FC St. Gallen": "Санкт-Галлен", "St. Gallen": "Санкт-Галлен",
    "Omonia Nicosia": "Омония", "APOEL Nicosia": "АПОЭЛ", "APOEL": "АПОЭЛ", "Pafos FC": "Пафос", "Pafos": "Пафос",
    "NK Celje": "Целе", "Celje": "Целе", "Olimpija Ljubljana": "Олимпия Любляна", "FC Noah": "Ноа", "Noah": "Ноа",
    "Petrocub Hîncești": "Петрокуб", "TSC Bačka Topola": "ТСЦ Бачка-Топола", "Borac Banja Luka": "Борац Баня-Лука",
    "Shamrock Rovers": "Шемрок Роверс", "The New Saints": "ТНС", "Larne": "Ларн", "Víkingur Reykjavík": "Викингур",
    "Russia": "Россия", "France": "Франция", "Spain": "Испания", "England": "Англия", "Germany": "Германия",
    "Italy": "Италия", "Portugal": "Португалия", "Netherlands": "Нидерланды", "Belgium": "Бельгия", "Croatia": "Хорватия",
    "Switzerland": "Швейцария", "Denmark": "Дания", "Austria": "Австрия", "Serbia": "Сербия", "Hungary": "Венгрия",
    "Poland": "Польша", "Scotland": "Шотландия", "Ukraine": "Украина", "Turkey": "Турция", "Türkiye": "Турция",
    "Czechia": "Чехия", "Czech Republic": "Чехия", "Wales": "Уэльс", "Norway": "Норвегия", "Sweden": "Швеция",
    "Greece": "Греция", "Romania": "Румыния", "Slovakia": "Словакия", "Slovenia": "Словения", "Georgia": "Грузия",
    "Finland": "Финляндия", "Republic of Ireland": "Ирландия", "Ireland": "Ирландия", "Northern Ireland": "Северная Ирландия",
    "Kazakhstan": "Казахстан", "Armenia": "Армения", "Belarus": "Беларусь", "Azerbaijan": "Азербайджан", "Iceland": "Исландия",
    "Bosnia and Herzegovina": "Босния и Герцеговина", "Israel": "Израиль", "Albania": "Албания", "North Macedonia": "Северная Македония",
    "Montenegro": "Черногория", "Bulgaria": "Болгария", "Kosovo": "Косово", "Luxembourg": "Люксембург", "Cyprus": "Кипр",
    "Estonia": "Эстония", "Latvia": "Latvia", "Lithuania": "Литва", "Moldova": "Молдова", "Malta": "Мальта",
    "Andorra": "Андорра", "San Marino": "Сан-Марино", "Liechtenstein": "Лихтенштейн", "Gibraltar": "Гибралтар", "Faroe Islands": "Фарерские о-ва",
    "Brazil": "Бразилия", "Argentina": "Аргентина", "Uruguay": "Уругвай", "Colombia": "Колумбия", "USA": "США", "Mexico": "Мексика"
}

TEAM_TRANSLATIONS.update(EXACT_CLUB_DICTIONARY)
_SORTED_DICT_KEYS = sorted(TEAM_TRANSLATIONS.keys(), key=len, reverse=True)
_TRANSLATE_MEMO = {}

def translate_team_ru(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "Команда"
    if raw in _TRANSLATE_MEMO:
        return _TRANSLATE_MEMO[raw]
    if raw in TEAM_TRANSLATIONS:
        _TRANSLATE_MEMO[raw] = TEAM_TRANSLATIONS[raw]
        return _TRANSLATE_MEMO[raw]

    raw_low = raw.lower()
    for k in _SORTED_DICT_KEYS:
        if k.lower() == raw_low:
            _TRANSLATE_MEMO[raw] = TEAM_TRANSLATIONS[k]
            return _TRANSLATE_MEMO[raw]

    cleaned = re.sub(r"\b(FC|AFC|CF|SC|AC|AS|SV|VfL|VfB|TSG|1\.|RC|RCD|CD|UD|SD|FK|SK|NK|BK|IF|BSC|GNK|KAA|RSC)\b", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{2,4}\b", "", cleaned).strip(" .-")
    if cleaned in TEAM_TRANSLATIONS:
        _TRANSLATE_MEMO[raw] = TEAM_TRANSLATIONS[cleaned]
        return _TRANSLATE_MEMO[raw]

    cl_low = cleaned.lower()
    for k in _SORTED_DICT_KEYS:
        if k.lower() == cl_low:
            _TRANSLATE_MEMO[raw] = TEAM_TRANSLATIONS[k]
            return _TRANSLATE_MEMO[raw]

    for k in _SORTED_DICT_KEYS:
        if len(k) >= 4 and k.lower() in raw_low:
            _TRANSLATE_MEMO[raw] = TEAM_TRANSLATIONS[k]
            return _TRANSLATE_MEMO[raw]

    res = cleaned if cleaned else raw
    _TRANSLATE_MEMO[raw] = res
    return res

globals()["translate_team"] = translate_team_ru

# 3. АНТИ-ДЮП БЛОКИРОВКИ, RAM-КЭШ ПРОФИЛЯ И ЗАЩИЩЕННЫЙ ПУЛ БД
_orig_db_exec = db_manager.exec
_orig_db_fetchrow = db_manager.fetchrow
_orig_db_fetch = db_manager.fetch
_orig_db_fetchval = db_manager.fetchval
_orig_get_user = db_manager.get_user
_DB_RECONNECT_LOCK = asyncio.Lock()

RAM_USER_CACHE = {}  # {user_id: {"data": dict, "ts": float}}
USER_ACTION_LOCKS = defaultdict(asyncio.Lock)  # Защита от двойного клика и дюпа валюты/предметов

async def _safe_db_call(func, *args):
    for attempt in range(2):
        try:
            return await func(*args)
        except Exception as e:
            if attempt == 0 and db_manager.use_pg:
                async with _DB_RECONNECT_LOCK:
                    try:
                        import asyncpg
                        if db_manager.pg_pool:
                            try:
                                await asyncio.wait_for(db_manager.pg_pool.close(), timeout=1.5)
                            except Exception:
                                pass
                        db_manager.pg_pool = await asyncpg.create_pool(
                            DATABASE_URL, min_size=2, max_size=8,
                            max_inactive_connection_lifetime=120.0, command_timeout=8.0, statement_cache_size=0
                        )
                    except Exception:
                        pass
                await asyncio.sleep(0.02)
            else:
                raise e

async def _cached_exec(query: str, *args):
    res = await _safe_db_call(_orig_db_exec, query, *args)
    if "users" in query.lower():
        for a in args:
            if isinstance(a, int) and a in RAM_USER_CACHE:
                RAM_USER_CACHE.pop(a, None)
    return res

async def _fast_get_user(user_id: int, *args, **kwargs) -> dict:
    now_f = now_msk().timestamp()
    if not args and not kwargs:
        cached = RAM_USER_CACHE.get(user_id)
        if cached and (now_f - cached["ts"] < 25.0):
            return dict(cached["data"])
    u = await _orig_get_user(user_id, *args, **kwargs)
    if u:
        u_dict = dict(u)
        RAM_USER_CACHE[user_id] = {"data": u_dict, "ts": now_f}
        return u_dict
    return u

db_manager.exec = _cached_exec
db_manager.fetchrow = lambda q, *a: _safe_db_call(_orig_db_fetchrow, q, *a)
db_manager.fetch = lambda q, *a: _safe_db_call(_orig_db_fetch, q, *a)
db_manager.fetchval = lambda q, *a: _safe_db_call(_orig_db_fetchval, q, *a)
db_manager.get_user = _fast_get_user

# 4. СОХРАНЕНИЕ P2P-БИРЖИ В БАЗЕ ДАННЫХ (ЗАЩИТА ОТ ПОТЕРИ ЛОТОВ ПРИ ПЕРЕЗАПУСКЕ СЕРВЕРА)
P2P_CONTAINER_MARKET = []
_P2P_LOT_SEQ = 100

async def init_and_load_p2p_market():
    """Создает таблицу p2p_lots и восстанавливает все лоты игроков после перезапуска сервера"""
    global _P2P_LOT_SEQ
    try:
        await db_manager.exec("""
            CREATE TABLE IF NOT EXISTS p2p_lots (
                lot_id INTEGER PRIMARY KEY,
                seller_id BIGINT,
                seller_name TEXT,
                seller_vip INTEGER DEFAULT 0,
                price INTEGER,
                item_json TEXT,
                created_at TEXT
            )
        """)
        rows = await db_manager.fetch("SELECT * FROM p2p_lots ORDER BY lot_id DESC LIMIT 60")
        P2P_CONTAINER_MARKET.clear()
        max_id = 100
        for r in rows:
            rd = dict(r)
            lid = int(rd["lot_id"])
            if lid > max_id:
                max_id = lid
            try:
                item_obj = json.loads(rd.get("item_json") or "{}")
            except Exception:
                item_obj = {}
            if item_obj:
                P2P_CONTAINER_MARKET.append({
                    "lot_id": lid,
                    "seller_id": int(rd["seller_id"]),
                    "seller_name": rd["seller_name"],
                    "seller_vip": bool(rd.get("seller_vip")),
                    "price": int(rd["price"]),
                    "item": item_obj
                })
        _P2P_LOT_SEQ = max_id
    except Exception as e:
        logging.warning(f"Инициализация таблицы P2P-Биржи: {e}")

async def db_insert_p2p_lot(lot_obj: dict):
    try:
        if db_manager.use_pg:
            await db_manager.exec(
                "INSERT INTO p2p_lots (lot_id, seller_id, seller_name, seller_vip, price, item_json, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                lot_obj["lot_id"], lot_obj["seller_id"], lot_obj["seller_name"],
                1 if lot_obj.get("seller_vip") else 0, lot_obj["price"],
                json.dumps(lot_obj["item"], ensure_ascii=False), now_msk().strftime("%d.%m %H:%M")
            )
        else:
            async with aiosqlite.connect(db_manager.sqlite_path) as db:
                await db.execute(
                    "INSERT INTO p2p_lots (lot_id, seller_id, seller_name, seller_vip, price, item_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (lot_obj["lot_id"], lot_obj["seller_id"], lot_obj["seller_name"],
                     1 if lot_obj.get("seller_vip") else 0, lot_obj["price"],
                     json.dumps(lot_obj["item"], ensure_ascii=False), now_msk().strftime("%d.%m %H:%M"))
                )
                await db.commit()
    except Exception as e:
        logging.warning(f"Ошибка сохранения P2P-лота в БД: {e}")

async def db_delete_p2p_lot(lot_id: int):
    try:
        if db_manager.use_pg:
            await db_manager.exec("DELETE FROM p2p_lots WHERE lot_id = $1", lot_id)
        else:
            async with aiosqlite.connect(db_manager.sqlite_path) as db:
                await db.execute("DELETE FROM p2p_lots WHERE lot_id = ?", (lot_id,))
                await db.commit()
    except Exception as e:
        logging.warning(f"Ошибка удаления P2P-лота из БД: {e}")

# 5. 12 КОНТЕЙНЕРОВ (ОТ 1 000 ДО 300 000 FC) И 84 УНИКАЛЬНЫХ ПРЕДМЕТА + СПРОС ДНЯ (+15%)
DEMAND_CATEGORIES = {
    "tech": {"key": "tech", "title": "💻 Электроника и ИИ", "ico": "💻"},
    "auto": {"key": "auto", "title": "🏎 Авто и Болиды", "ico": "🏎"},
    "sport": {"key": "sport", "title": "⚽ Спорт и Трофеи", "ico": "⚽"},
    "art": {"key": "art", "title": "💎 Искусство и Люкс", "ico": "💎"},
    "crypto": {"key": "crypto", "title": "₿ Крипто и Финансы", "ico": "₿"},
    "space": {"key": "space", "title": "🛸 Секретные Технологии", "ico": "🛸"}
}

def get_daily_port_demand() -> dict:
    day_seed = now_msk().timetuple().tm_yday
    keys = list(DEMAND_CATEGORIES.keys())
    chosen_k = keys[day_seed % len(keys)]
    return {**DEMAND_CATEGORIES[chosen_k], "bonus_pct": 15, "mult": 1.15}

CONTAINERS_CATALOG = {
    "c_1": {
        "id": "c_1", "name": "📦 Гараж в Детройте", "price": 1000, "ico": "🏚️",
        "desc": "Старая электроника, винтажный инструмент и забытые заначки", "max_win": "3 600 FC",
        "items": [
            {"id": "c1_1", "name": "🧰 Перфоратор DeWalt Pro", "ico": "🧰", "cat": "tech", "base": 650, "rarity": 1, "show_inc": 35, "show_odd": 0.01},
            {"id": "c1_2", "name": "🎮 Приставка PS2 Slim Limited", "ico": "🎮", "cat": "tech", "base": 850, "rarity": 1, "show_inc": 45, "show_odd": 0.01},
            {"id": "c1_3", "name": "🛞 Литые диски BBS (Комплект)", "ico": "🛞", "cat": "auto", "base": 1050, "rarity": 1, "show_inc": 55, "show_odd": 0.01},
            {"id": "c1_4", "name": "🥊 Автограф Майка Тайсона на перчатке", "ico": "🥊", "cat": "sport", "base": 1250, "rarity": 2, "show_inc": 70, "show_odd": 0.01},
            {"id": "c1_5", "name": "📻 Ретро-Джукбокс 1972 года", "ico": "📻", "cat": "art", "base": 1500, "rarity": 2, "show_inc": 85, "show_odd": 0.02},
            {"id": "c1_6", "name": "⚙️ Карбюратор V8 Ford Mustang", "ico": "⚙️", "cat": "auto", "base": 1750, "rarity": 2, "show_inc": 100, "show_odd": 0.02},
            {"id": "c1_7", "name": "🔐 Ржавый сейф инкассатора", "ico": "🔐", "cat": "crypto", "base": 2100, "rarity": 3, "show_inc": 120, "show_odd": 0.02}
        ]
    },
    "c_2": {
        "id": "c_2", "name": "🧳 Карго-Бокс Аэропорта", "price": 2500, "ico": "✈️",
        "desc": "Невостребованный VIP-багаж международных авиарейсов", "max_win": "9 000 FC",
        "items": [
            {"id": "c2_1", "name": "🧳 Дорожный кофр Louis Vuitton", "ico": "🧳", "cat": "art", "base": 1650, "rarity": 1, "show_inc": 80, "show_odd": 0.01},
            {"id": "c2_2", "name": "🚁 Квадрокоптер DJI Mavic 3 Pro", "ico": "🚁", "cat": "tech", "base": 2100, "rarity": 1, "show_inc": 105, "show_odd": 0.02},
            {"id": "c2_3", "name": "📷 Дальномерная камера Leica M6", "ico": "📷", "cat": "art", "base": 2650, "rarity": 2, "show_inc": 130, "show_odd": 0.02},
            {"id": "c2_4", "name": "⌚ Швейцарский хронограф Tissot", "ico": "⌚", "cat": "art", "base": 3200, "rarity": 2, "show_inc": 155, "show_odd": 0.02},
            {"id": "c2_5", "name": "🎾 Ракетка финала Уимблдона", "ico": "🎾", "cat": "sport", "base": 3800, "rarity": 2, "show_inc": 180, "show_odd": 0.02},
            {"id": "c2_6", "name": "💻 Ноутбук Razer Blade 18", "ico": "💻", "cat": "tech", "base": 4400, "rarity": 3, "show_inc": 210, "show_odd": 0.03},
            {"id": "c2_7", "name": "🪙 Кейс инвестиционного серебра", "ico": "🪙", "cat": "crypto", "base": 5200, "rarity": 3, "show_inc": 250, "show_odd": 0.03}
        ]
    },
    "c_3": {
        "id": "c_3", "name": "⚓ Таможня Роттердама", "price": 5000, "ico": "🚢",
        "desc": "Конфискат европейского порта: техника, байки и бренды", "max_win": "18 000 FC",
        "items": [
            {"id": "c3_1", "name": "📱 Партия смартфонов iPhone 16 Pro", "ico": "📱", "cat": "tech", "base": 3400, "rarity": 1, "show_inc": 160, "show_odd": 0.02},
            {"id": "c3_2", "name": "🛵 Итальянский скутер Vespa Primavera", "ico": "🛵", "cat": "auto", "base": 4300, "rarity": 2, "show_inc": 195, "show_odd": 0.02},
            {"id": "c3_3", "name": "⌚ Часы TAG Heuer Monaco", "ico": "⌚", "cat": "art", "base": 5300, "rarity": 2, "show_inc": 230, "show_odd": 0.03},
            {"id": "c3_4", "name": "⚡ Ферма асиков Antminer S21", "ico": "⚡", "cat": "crypto", "base": 6500, "rarity": 2, "show_inc": 280, "show_odd": 0.03},
            {"id": "c3_5", "name": "🔊 Акустика Bang & Olufsen Gold", "ico": "🔊", "cat": "tech", "base": 7800, "rarity": 3, "show_inc": 340, "show_odd": 0.03},
            {"id": "c3_6", "name": "🏍️ Чоппер Harley-Davidson Fat Boy", "ico": "🏍️", "cat": "auto", "base": 9200, "rarity": 3, "show_inc": 410, "show_odd": 0.04},
            {"id": "c3_7", "name": "💎 Алмазный тубус Антверпена", "ico": "💎", "cat": "art", "base": 10800, "rarity": 3, "show_inc": 460, "show_odd": 0.04}
        ]
    },
    "c_4": {
        "id": "c_4", "name": "🎸 Студия Abbey Road (Лондон)", "price": 10000, "ico": "🎙️",
        "desc": "Музыкальные реликвии, редкий винил и коллекционные гитары", "max_win": "36 000 FC",
        "items": [
            {"id": "c4_1", "name": "🎛️ Ламповый пульт Neve Vintage", "ico": "🎛️", "cat": "tech", "base": 6800, "rarity": 2, "show_inc": 290, "show_odd": 0.03},
            {"id": "c4_2", "name": "💿 Платиновый диск Queen (1975)", "ico": "💿", "cat": "art", "base": 8600, "rarity": 2, "show_inc": 350, "show_odd": 0.03},
            {"id": "c4_3", "name": "🎸 Электрогитара Gibson Les Paul 1959", "ico": "🎸", "cat": "art", "base": 10800, "rarity": 2, "show_inc": 430, "show_odd": 0.04},
            {"id": "c4_4", "name": "🎹 Синтезатор Moog Modular", "ico": "🎹", "cat": "tech", "base": 13200, "rarity": 3, "show_inc": 510, "show_odd": 0.04},
            {"id": "c4_5", "name": "🚗 Классический Mini Cooper S", "ico": "🚗", "cat": "auto", "base": 15800, "rarity": 3, "show_inc": 590, "show_odd": 0.05},
            {"id": "c4_6", "name": "🎤 Золотой микрофон Фредди Меркьюри", "ico": "🎤", "cat": "art", "base": 18500, "rarity": 3, "show_inc": 680, "show_odd": 0.05},
            {"id": "c4_7", "name": "🏆 Оригинальная статуэтка Грэмми", "ico": "🏆", "cat": "art", "base": 21500, "rarity": 4, "show_inc": 780, "show_odd": 0.06}
        ]
    },
    "c_5": {
        "id": "c_5", "name": "⚽ Раздевалка Легенд Футбола", "price": 20000, "ico": "🏟️",
        "desc": "Музейные реликвии Чемпионатов Мира и финалов Лиги Чемпионов", "max_win": "72 000 FC",
        "items": [
            {"id": "c5_1", "name": "⚽ Мяч Финала ЛЧ с автографами", "ico": "⚽", "cat": "sport", "base": 13500, "rarity": 2, "show_inc": 520, "show_odd": 0.04},
            {"id": "c5_2", "name": "👕 Футболка Зидана (Финал ЧМ-1998)", "ico": "👕", "cat": "sport", "base": 17500, "rarity": 2, "show_inc": 640, "show_odd": 0.05},
            {"id": "c5_3", "name": "👟 Золотые бутсы Роналдиньо", "ico": "👟", "cat": "sport", "base": 21500, "rarity": 3, "show_inc": 760, "show_odd": 0.05},
            {"id": "c5_4", "name": "🧤 Вратарские перчатки Льва Яшина", "ico": "🧤", "cat": "sport", "base": 26000, "rarity": 3, "show_inc": 890, "show_odd": 0.06},
            {"id": "c5_5", "name": "🥇 Золотая медаль АПЛ (Invincibles)", "ico": "🥇", "cat": "sport", "base": 31000, "rarity": 3, "show_inc": 1050, "show_odd": 0.06},
            {"id": "c5_6", "name": "👟 Именная награда «Золотая Бутса»", "ico": "👟", "cat": "sport", "base": 37000, "rarity": 4, "show_inc": 1220, "show_odd": 0.07},
            {"id": "c5_7", "name": "🏆 Реплика «Золотого Мяча» France Football", "ico": "🏆", "cat": "sport", "base": 43000, "rarity": 4, "show_inc": 1400, "show_odd": 0.08}
        ]
    },
    "c_6": {
        "id": "c_6", "name": "🏎 Паддок Монако Гран-При", "price": 35000, "ico": "🏁",
        "desc": "Гоночные болиды, карбоновые узлы и трофеи пилотов Формулы-1", "max_win": "125 000 FC",
        "items": [
            {"id": "c6_1", "name": "🛞 Карбоновый обвес Ferrari SF", "ico": "🛞", "cat": "auto", "base": 24000, "rarity": 2, "show_inc": 820, "show_odd": 0.05},
            {"id": "c6_2", "name": "🎮 Руль болида F1 с телеметрией", "ico": "🎮", "cat": "tech", "base": 30000, "rarity": 3, "show_inc": 980, "show_odd": 0.06},
            {"id": "c6_3", "name": "⚙️ Оппозитный мотор Porsche GT3 RS", "ico": "⚙️", "cat": "auto", "base": 37000, "rarity": 3, "show_inc": 1180, "show_odd": 0.07},
            {"id": "c6_4", "name": "🪖 Шлем Айртона Сенны (Оригинал)", "ico": "🪖", "cat": "sport", "base": 45000, "rarity": 3, "show_inc": 1420, "show_odd": 0.08},
            {"id": "c6_5", "name": "⌚ Часы Rolex Cosmograph Daytona", "ico": "⌚", "cat": "art", "base": 54000, "rarity": 3, "show_inc": 1680, "show_odd": 0.08},
            {"id": "c6_6", "name": "🏎️ Шасси болида Red Bull Racing", "ico": "🏎️", "cat": "auto", "base": 64000, "rarity": 4, "show_inc": 1950, "show_odd": 0.09},
            {"id": "c6_7", "name": "🏎️ Чемпионский болид McLaren MP4/4", "ico": "🏎️", "cat": "auto", "base": 75000, "rarity": 4, "show_inc": 2250, "show_odd": 0.10}
        ]
    },
    "c_7": {
        "id": "c_7", "name": "💻 Бункер Кремниевой Долины", "price": 60000, "ico": "🛰️",
        "desc": "Квантовые серверы, нейрочипы и забытые крипто-кошельки", "max_win": "215 000 FC",
        "items": [
            {"id": "c7_1", "name": "🧠 Серверная стойка Nvidia H200", "ico": "🧠", "cat": "tech", "base": 41000, "rarity": 2, "show_inc": 1350, "show_odd": 0.07},
            {"id": "c7_2", "name": "🕶️ Прототип нейро-шлема Apple Vision X", "ico": "🕶️", "cat": "tech", "base": 52000, "rarity": 3, "show_inc": 1650, "show_odd": 0.08},
            {"id": "c7_3", "name": "🔑 Зашифрованный Ledger (Архив 2013)", "ico": "🔑", "cat": "crypto", "base": 64000, "rarity": 3, "show_inc": 1980, "show_odd": 0.09},
            {"id": "c7_4", "name": "🔋 Твердотельный реактор Tesla", "ico": "🔋", "cat": "space", "base": 78000, "rarity": 3, "show_inc": 2350, "show_odd": 0.10},
            {"id": "c7_5", "name": "⚛️ Квантовый процессор IBM Condor", "ico": "⚛️", "cat": "tech", "base": 92000, "rarity": 4, "show_inc": 2750, "show_odd": 0.11},
            {"id": "c7_6", "name": "🤖 Андроид-прототип Tesla Optimus", "ico": "🤖", "cat": "tech", "base": 108000, "rarity": 4, "show_inc": 3150, "show_odd": 0.12},
            {"id": "c7_7", "name": "💾 Исходный код ИИ первого поколения", "ico": "💾", "cat": "crypto", "base": 128000, "rarity": 4, "show_inc": 3600, "show_odd": 0.13}
        ]
    },
    "c_8": {
        "id": "c_8", "name": "🖼️ Закрытый Аукцион Сотбис", "price": 95000, "ico": "🏛️",
        "desc": "Музейные шедевры, яйца Фаберже и королевские драгоценности", "max_win": "340 000 FC",
        "items": [
            {"id": "c8_1", "name": "🏺 Античная амфора династии Мин", "ico": "🏺", "cat": "art", "base": 65000, "rarity": 3, "show_inc": 2100, "show_odd": 0.09},
            {"id": "c8_2", "name": "🎻 Скрипка Страдивари (1715 г.)", "ico": "🎻", "cat": "art", "base": 82000, "rarity": 3, "show_inc": 2550, "show_odd": 0.10},
            {"id": "c8_3", "name": "⌚ Часы Patek Philippe Grandmaster", "ico": "⌚", "cat": "art", "base": 102000, "rarity": 3, "show_inc": 3050, "show_odd": 0.11},
            {"id": "c8_4", "name": "💍 Розовый бриллиант «Звезда Востока»", "ico": "💍", "cat": "art", "base": 124000, "rarity": 4, "show_inc": 3550, "show_odd": 0.12},
            {"id": "c8_5", "name": "🥚 Императорское яйцо Фаберже", "ico": "🥚", "cat": "art", "base": 148000, "rarity": 4, "show_inc": 4100, "show_odd": 0.13},
            {"id": "c8_6", "name": "🖼️ Неизвестный эскиз Пикассо", "ico": "🖼️", "cat": "art", "base": 175000, "rarity": 4, "show_inc": 4700, "show_odd": 0.14},
            {"id": "c8_7", "name": "👑 Корона герцога Бургундского", "ico": "👑", "cat": "art", "base": 205000, "rarity": 4, "show_inc": 5300, "show_odd": 0.15}
        ]
    },
    "c_9": {
        "id": "c_9", "name": "👑 Золотой Борт Шейха (Дубай)", "price": 135000, "ico": "🛩️",
        "desc": "Гиперкары из пустыни, слитки 999 пробы и люксовые яхты", "max_win": "480 000 FC",
        "items": [
            {"id": "c9_1", "name": "💎 Часы Richard Mille Tourbillon", "ico": "💎", "cat": "art", "base": 92000, "rarity": 3, "show_inc": 2900, "show_odd": 0.11},
            {"id": "c9_2", "name": "🚙 Бронированный Mercedes G63 6x6", "ico": "🚙", "cat": "auto", "base": 116000, "rarity": 3, "show_inc": 3500, "show_odd": 0.12},
            {"id": "c9_3", "name": "🪙 Палета золотых слитков Dubai 999", "ico": "🪙", "cat": "crypto", "base": 142000, "rarity": 3, "show_inc": 4200, "show_odd": 0.13},
            {"id": "c9_4", "name": "🟡 Суперкар Lamborghini Aventador SVJ", "ico": "🟡", "cat": "auto", "base": 172000, "rarity": 4, "show_inc": 4900, "show_odd": 0.15},
            {"id": "c9_5", "name": "🐎 Арабский скакун чемпиона Мира", "ico": "🐎", "cat": "sport", "base": 205000, "rarity": 4, "show_inc": 5600, "show_odd": 0.16},
            {"id": "c9_6", "name": "🛥️ Супер-катер Brabus Shadow 900", "ico": "🛥️", "cat": "auto", "base": 245000, "rarity": 4, "show_inc": 6400, "show_odd": 0.17},
            {"id": "c9_7", "name": "🛩️ Бизнес-джет Gulfstream (Доля)", "ico": "🛩️", "cat": "space", "base": 290000, "rarity": 4, "show_inc": 7300, "show_odd": 0.19}
        ]
    },
    "c_10": {
        "id": "c_10", "name": "🏦 Швейцарское Крипто-Хранилище", "price": 180000, "ico": "🔐",
        "desc": "Альпийский бункер с холодными кошельками и банковскими резервами", "max_win": "640 000 FC",
        "items": [
            {"id": "c10_1", "name": "💳 Платиновая карта Centurion Безлимит", "ico": "💳", "cat": "crypto", "base": 122000, "rarity": 3, "show_inc": 3800, "show_odd": 0.13},
            {"id": "c10_2", "name": "📦 Банковская ячейка Цюриха #001", "ico": "📦", "cat": "crypto", "base": 154000, "rarity": 3, "show_inc": 4600, "show_odd": 0.14},
            {"id": "c10_3", "name": "🔷 Валидатор сети Ethereum (32 ETH)", "ico": "🔷", "cat": "crypto", "base": 190000, "rarity": 4, "show_inc": 5500, "show_odd": 0.16},
            {"id": "c10_4", "name": "🔵 Гиперкар Bugatti Chiron Pur Sport", "ico": "🔵", "cat": "auto", "base": 230000, "rarity": 4, "show_inc": 6500, "show_odd": 0.18},
            {"id": "c10_5", "name": "📜 Акции технологического гиганта (Пакет)", "ico": "📜", "cat": "crypto", "base": 275000, "rarity": 4, "show_inc": 7500, "show_odd": 0.19},
            {"id": "c10_6", "name": "₿ Холодный узел Genesis Block", "ico": "₿", "cat": "crypto", "base": 330000, "rarity": 4, "show_inc": 8600, "show_odd": 0.21},
            {"id": "c10_7", "name": "🏛️ Золотой резерв Альпийского Банка", "ico": "🏛️", "cat": "crypto", "base": 385000, "rarity": 4, "show_inc": 9800, "show_odd": 0.23}
        ]
    },
    "c_11": {
        "id": "c_11", "name": "🛸 Секретный Сектор «Зона-51»", "price": 240000, "ico": "👽",
        "desc": "Засекреченные военные разработки и внеземные артефакты", "max_win": "860 000 FC",
        "items": [
            {"id": "c11_1", "name": "✈️ Беспилотник-невидимка X-47B", "ico": "✈️", "cat": "space", "base": 165000, "rarity": 3, "show_inc": 5100, "show_odd": 0.16},
            {"id": "c11_2", "name": "🦾 Военный экзоскелет поколения V", "ico": "🦾", "cat": "space", "base": 205000, "rarity": 4, "show_inc": 6200, "show_odd": 0.18},
            {"id": "c11_3", "name": "🖼️ Утраченное полотно Леонардо да Винчи", "ico": "🖼️", "cat": "art", "base": 252000, "rarity": 4, "show_inc": 7400, "show_odd": 0.20},
            {"id": "c11_4", "name": "🧬 Капсула криогенной регенерации", "ico": "🧬", "cat": "space", "base": 305000, "rarity": 4, "show_inc": 8800, "show_odd": 0.22},
            {"id": "c11_5", "name": "₿ Архивный диск Сатоши Накамото", "ico": "₿", "cat": "crypto", "base": 365000, "rarity": 4, "show_inc": 10200, "show_odd": 0.24},
            {"id": "c11_6", "name": "☄️ Метеорит из чистого иридия", "ico": "☄️", "cat": "space", "base": 435000, "rarity": 4, "show_inc": 11800, "show_odd": 0.26},
            {"id": "c11_7", "name": "🛸 Антигравитационный двигатель Зоны-51", "ico": "🛸", "cat": "space", "base": 515000, "rarity": 4, "show_inc": 13500, "show_odd": 0.29}
        ]
    },
    "c_12": {
        "id": "c_12", "name": "🌌 Орбитальный Ковчег Миллиардеров", "price": 300000, "ico": "🚀",
        "desc": "Финальный контейнер игры: космические станции, острова и сверхразум", "max_win": "1 100 000 FC",
        "items": [
            {"id": "c12_1", "name": "🛰️ Частный спутник связи Starlink-VIP", "ico": "🛰️", "cat": "space", "base": 205000, "rarity": 4, "show_inc": 6800, "show_odd": 0.20},
            {"id": "c12_2", "name": "🏎️ Единственный гиперкар Koenigsegg Jesko Absolut", "ico": "🏎️", "cat": "auto", "base": 260000, "rarity": 4, "show_inc": 8200, "show_odd": 0.22},
            {"id": "c12_3", "name": "🏝️ Частный архипелаг в Полинезии", "ico": "🏝️", "cat": "art", "base": 320000, "rarity": 4, "show_inc": 9800, "show_odd": 0.25},
            {"id": "c12_4", "name": "☀️ Реактор холодного ядерного синтеза", "ico": "☀️", "cat": "space", "base": 385000, "rarity": 4, "show_inc": 11500, "show_odd": 0.28},
            {"id": "c12_5", "name": "🧠 Квантовый ИИ-Сверхразум «Оракул»", "ico": "🧠", "cat": "tech", "base": 460000, "rarity": 4, "show_inc": 13500, "show_odd": 0.31},
            {"id": "c12_6", "name": "🚀 Межпланетный шаттл колонизации", "ico": "🚀", "cat": "space", "base": 545000, "rarity": 4, "show_inc": 15800, "show_odd": 0.35},
            {"id": "c12_7", "name": "👑 Императорский Монолит Мирового Синдиката", "ico": "👑", "cat": "crypto", "base": 640000, "rarity": 4, "show_inc": 18500, "show_odd": 0.40}
        ]
    }
}

# 6. ТАРИФЫ VIP-КЛУБА ЗА FC (НАЧИНАЯ ОТ 20 000 FC)
VIP_PLANS_FC = {
    "vip_3d": {"id": "vip_3d", "days": 3, "price": 20000, "title": "👑 VIP-Статус на 3 дня", "sub": "Идеально на тур еврокубков"},
    "vip_14d": {"id": "vip_14d", "days": 14, "price": 65000, "title": "👑 VIP-Статус на 14 дней", "sub": "Выгода 30% • 2 недели привилегий"},
    "vip_30d": {"id": "vip_30d", "days": 30, "price": 120000, "title": "👑 VIP-Магнат на 30 дней", "sub": "Максимальная выгода на весь месяц"}
}

VIP_BENEFITS_LIST = [
    "⚡ <b>+0.15 к коэффициенту</b> каждого Ординара и Экспресса автоматически",
    "📦 <b>Скидка 10% на покупку всех 12 Контейнеров</b> в Портовом Аукционе",
    "🔧 <b>Шанс успешной реставрации 84%</b> (вместо 72%) + склад на <b>12 мест</b> и <b>4 витрины Шоурума</b>",
    "🌐 <b>0% комиссии на P2P-Бирже</b> при продаже находок другим игрокам",
    "🏟 <b>Подписание любых спонсоров без залога</b> + удвоенный бонус ранга",
    "👑 <b>Золотая корона VIP</b> рядом с твоим ником в Топ-10 и прямой трансляции"
]

LIVE_TICKER_FEED = [
    "🎄 Добро пожаловать в Новогодний сезон AI_BET_BOT 2027! Вскрывай контейнеры и собирай состав мечты!",
    "🔥 Каппер Alex_Bet выбил «🏎️ Шасси болида F1» в контейнере Монако!",
    "⚡ Игрок Маэстро_99 собрал Экспресс с кэфом 6.45 и забрал +16 125 FC!",
    "💎 На P2P-Бирже продан «🔑 Зашифрованный Ledger» за 68 500 FC!",
    "👑 Игрок KaperPro активировал VIP-Статус и открыл «🛸 Сектор Зона-51»!"
]

def push_live_ticker(event_text: str):
    LIVE_TICKER_FEED.insert(0, event_text)
    if len(LIVE_TICKER_FEED) > 12:
        LIVE_TICKER_FEED.pop()

# 7. КОНТРАКТЫ СПОНСОРОВ И КАЛЕНДАРЬ ВХОДА (ОТ 200 ДО 3 500 FC)
STADIUM_SPONSORS = [
    {
        "id": "sp_1", "name": "🟢 Winter Cup Energy", "min_lvl": 1, "deposit": 0, "bonus": 350,
        "task_code": "any_bet", "task": "Сделать минимум 1 любую ставку сегодня (Без риска)"
    },
    {
        "id": "sp_2", "name": "🔵 Gazprom Media Sport", "min_lvl": 2, "deposit": 150, "bonus": 850,
        "task_code": "bet_500_or_pvp", "task": "Активная ставка от 500 FC ИЛИ победа в PvP (Залог 150 FC)"
    },
    {
        "id": "sp_3", "name": "🟡 CyberBet Syndicate", "min_lvl": 4, "deposit": 400, "bonus": 1900,
        "task_code": "express_bet", "task": "Иметь в игре Экспресс минимум из 2 матчей (Залог 400 FC)"
    },
    {
        "id": "sp_4", "name": "🟣 Qatar Airways VIP", "min_lvl": 6, "deposit": 1000, "bonus": 4500,
        "task_code": "streak_or_fut", "task": "Серия от 1 победы ИЛИ собранный состав FUT (Залог 1 000 FC)"
    },
    {
        "id": "sp_5", "name": "👑 Rolex Champions Club", "min_lvl": 8, "deposit": 2500, "bonus": 9800,
        "task_code": "showroom_and_bet", "task": "Активная ставка + минимум 1 экспонат в Шоуруме Контейнеров (Залог 2 500 FC)"
    }
]

STREAK_CALENDAR = [
    {"day": 1, "coins": 200, "booster": "", "label": "+200 FC"},
    {"day": 2, "coins": 350, "booster": "", "label": "+350 FC"},
    {"day": 3, "coins": 550, "booster": "", "label": "+550 FC"},
    {"day": 4, "coins": 850, "booster": "", "label": "+850 FC"},
    {"day": 5, "coins": 1300, "booster": "boost035", "label": "+1 300 FC + ⚡ Буст +0.35"},
    {"day": 6, "coins": 2000, "booster": "", "label": "+2 000 FC"},
    {"day": 7, "coins": 3500, "booster": "insure50", "label": "🎁 +3 500 FC + 🛡 Страховка 50%"}
]

# 8. 36 КАРТОЧЕК FUT
FUT_CARDS.clear()
FUT_CARDS.update({
    "fw_1": {"id": "fw_1", "role": "FW", "tier": 1, "ovr": 84, "nation": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "name": "🥉 Джейми Варди", "val": 6, "desc": "+6% к прибыли на Тоталах", "pack": "Базовый"},
    "fw_6": {"id": "fw_6", "role": "FW", "tier": 1, "ovr": 85, "nation": "🇪🇸", "name": "🥉 Альваро Мората", "val": 7, "desc": "+7% к прибыли на Тоталах", "pack": "Базовый"},
    "fw_7": {"id": "fw_7", "role": "FW", "tier": 1, "ovr": 86, "nation": "🇷🇺", "name": "🥉 Константин Тюкавин", "val": 8, "desc": "+8% к прибыли на Тоталах", "pack": "Базовый"},
    "fw_2": {"id": "fw_2", "role": "FW", "tier": 2, "ovr": 90, "nation": "🇪🇬", "name": "🥇 Мохамед Салах", "val": 11, "desc": "+11% к прибыли на Тоталах", "pack": "Золотой"},
    "fw_3": {"id": "fw_3", "role": "FW", "tier": 2, "ovr": 91, "nation": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "name": "🥇 Харри Кейн", "val": 12, "desc": "+12% к прибыли на Тоталах", "pack": "Золотой"},
    "fw_8": {"id": "fw_8", "role": "FW", "tier": 2, "ovr": 91, "nation": "🇵🇱", "name": "🥇 Роберт Левандовски", "val": 12, "desc": "+12% к прибыли на Тоталах", "pack": "Золотой"},
    "fw_9": {"id": "fw_9", "role": "FW", "tier": 2, "ovr": 90, "nation": "🇪🇸", "name": "🥇 Ламин Ямаль", "val": 13, "desc": "+13% к прибыли на Тоталах", "pack": "Золотой"},
    "fw_4": {"id": "fw_4", "role": "FW", "tier": 3, "ovr": 95, "nation": "🇫🇷", "name": "💎 Килиан Мбаппе (TOTY)", "val": 17, "desc": "+17% к прибыли на Тоталах", "pack": "Элитный ЛЧ"},
    "fw_5": {"id": "fw_5", "role": "FW", "tier": 3, "ovr": 95, "nation": "🇳🇴", "name": "💎 Эрлинг Холанд (ICON)", "val": 18, "desc": "+18% к прибыли на Тоталах", "pack": "Элитный ЛЧ"},
    "fw_10": {"id": "fw_10", "role": "FW", "tier": 3, "ovr": 95, "nation": "🇧🇷", "name": "💎 Винисиус Жуниор (TOTY)", "val": 18, "desc": "+18% к прибыли на Тоталах", "pack": "Элитный ЛЧ"},
    "mid_1": {"id": "mid_1", "role": "MID", "tier": 1, "ovr": 85, "nation": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "name": "🥉 Коул Палмер", "val": 6, "desc": "+6% к прибыли на 1Х2 и Таймах", "pack": "Базовый"},
    "mid_4": {"id": "mid_4", "role": "MID", "tier": 1, "ovr": 85, "nation": "🇷🇺", "name": "🥉 Александр Головин", "val": 7, "desc": "+7% к прибыли на 1Х2 и Таймах", "pack": "Базовый"},
    "mid_2": {"id": "mid_2", "role": "MID", "tier": 2, "ovr": 91, "nation": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "name": "🥇 Джуд Беллингем", "val": 12, "desc": "+12% к прибыли на 1Х2 и Таймах", "pack": "Золотой"},
    "mid_5": {"id": "mid_5", "role": "MID", "tier": 2, "ovr": 90, "nation": "🇩🇪", "name": "🥇 Джамал Мусиала", "val": 11, "desc": "+11% к прибыли на 1Х2 и Таймах", "pack": "Золотой"},
    "mid_6": {"id": "mid_6", "role": "MID", "tier": 2, "ovr": 92, "nation": "🇪🇸", "name": "🥇 Родри", "val": 13, "desc": "+13% к прибыли на 1Х2 и Таймах", "pack": "Золотой"},
    "mid_3": {"id": "mid_3", "role": "MID", "tier": 3, "ovr": 95, "nation": "🇧🇪", "name": "💎 Кевин Де Брёйне (TOTY)", "val": 18, "desc": "+18% к прибыли на 1Х2 и Таймах", "pack": "Элитный ЛЧ"},
    "mid_7": {"id": "mid_7", "role": "MID", "tier": 3, "ovr": 96, "nation": "🇫🇷", "name": "💎 Зинедин Зидан (ICON)", "val": 19, "desc": "+19% к прибыли на 1Х2 и Таймах", "pack": "Элитный ЛЧ"},
    "def_1": {"id": "def_1", "role": "DEF", "tier": 1, "ovr": 84, "nation": "🇫🇷", "name": "🥉 Вильям Салиба", "val": 6, "desc": "+6% к прибыли на Форах и ОЗ", "pack": "Базовый"},
    "def_4": {"id": "def_4", "role": "DEF", "tier": 1, "ovr": 85, "nation": "🇭🇷", "name": "🥉 Йошко Гвардиол", "val": 7, "desc": "+7% к прибыли на Форах и ОЗ", "pack": "Базовый"},
    "def_2": {"id": "def_2", "role": "DEF", "tier": 2, "ovr": 90, "nation": "🇳🇱", "name": "🥇 Вирджил ван Дейк", "val": 12, "desc": "+12% к прибыли на Форах и ОЗ", "pack": "Золотой"},
    "def_5": {"id": "def_5", "role": "DEF", "tier": 2, "ovr": 89, "nation": "🇩🇪", "name": "🥇 Антонио Рюдигер", "val": 11, "desc": "+11% к прибыли на Форах и ОЗ", "pack": "Золотой"},
    "def_6": {"id": "def_6", "role": "DEF", "tier": 2, "ovr": 90, "nation": "🇪🇸", "name": "🥇 Дани Карвахаль", "val": 12, "desc": "+12% к прибыли на Форах и ОЗ", "pack": "Золотой"},
    "def_3": {"id": "def_3", "role": "DEF", "tier": 3, "ovr": 95, "nation": "🇮🇹", "name": "💎 Паоло Мальдини (ICON)", "val": 18, "desc": "+18% к прибыли на Форах и ОЗ", "pack": "Элитный ЛЧ"},
    "def_7": {"id": "def_7", "role": "DEF", "tier": 3, "ovr": 94, "nation": "🇧🇷", "name": "💎 Роберто Карлос (ICON)", "val": 17, "desc": "+17% к прибыли на Форах и ОЗ", "pack": "Элитный ЛЧ"},
    "gk_1": {"id": "gk_1", "role": "GK", "tier": 1, "ovr": 84, "nation": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "name": "🥉 Джордан Пикфорд", "val": 8, "desc": "8% кэшбэк при проигрыше", "pack": "Базовый"},
    "gk_4": {"id": "gk_4", "role": "GK", "tier": 1, "ovr": 86, "nation": "🇷🇺", "name": "🥉 Игорь Акинфеев", "val": 9, "desc": "9% кэшбэк при проигрыше", "pack": "Базовый"},
    "gk_2": {"id": "gk_2", "role": "GK", "tier": 2, "ovr": 90, "nation": "🇧🇷", "name": "🥇 Алиссон Бекер", "val": 14, "desc": "14% кэшбэк при проигрыше", "pack": "Золотой"},
    "gk_5": {"id": "gk_5", "role": "GK", "tier": 2, "ovr": 90, "nation": "🇮🇹", "name": "🥇 Джанлуиджи Доннарумма", "val": 14, "desc": "14% кэшбэк при проигрыше", "pack": "Золотой"},
    "gk_3": {"id": "gk_3", "role": "GK", "tier": 3, "ovr": 95, "nation": "🇧🇪", "name": "💎 Тибо Куртуа (TOTY)", "val": 20, "desc": "20% кэшбэк при проигрыше", "pack": "Элитный ЛЧ"},
    "gk_6": {"id": "gk_6", "role": "GK", "tier": 3, "ovr": 96, "nation": "🇮🇹", "name": "💎 Джанлуиджи Буффон (ICON)", "val": 21, "desc": "21% кэшбэк при проигрыше", "pack": "Элитный ЛЧ"},
    "co_1": {"id": "co_1", "role": "COACH", "tier": 1, "ovr": 85, "nation": "🇪🇸", "name": "🥉 Микель Артета", "val": 0.10, "desc": "+0.10 к кэфу Экспресса", "pack": "Базовый"},
    "co_4": {"id": "co_4", "role": "COACH", "tier": 1, "ovr": 86, "nation": "🇪🇸", "name": "🥉 Хаби Алонсо", "val": 0.12, "desc": "+0.12 к кэфу Экспресса", "pack": "Базовый"},
    "co_2": {"id": "co_2", "role": "COACH", "tier": 2, "ovr": 92, "nation": "🇩🇪", "name": "🥇 Юрген Клопп", "val": 0.20, "desc": "+0.20 к кэфу Экспресса", "pack": "Золотой"},
    "co_5": {"id": "co_5", "role": "COACH", "tier": 2, "ovr": 91, "nation": "🇵🇹", "name": "🥇 Жозе Моуринью", "val": 0.18, "desc": "+0.18 к кэфу Экспресса", "pack": "Золотой"},
    "co_3": {"id": "co_3", "role": "COACH", "tier": 3, "ovr": 96, "nation": "🇮🇹", "name": "💎 Карло Анчелотти (ICON)", "val": 0.30, "desc": "+0.30 к кэфу Экспресса", "pack": "Элитный ЛЧ"},
    "co_6": {"id": "co_6", "role": "COACH", "tier": 3, "ovr": 97, "nation": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "name": "💎 Сэр Алекс Фергюсон (ICON)", "val": 0.35, "desc": "+0.35 к кэфу Экспресса", "pack": "Элитный ЛЧ"},
    "goat_messi": {"id": "goat_messi", "role": "FW", "tier": 4, "ovr": 99, "nation": "🇦🇷", "name": "🐐 Лионель Месси (GOAT)", "val": 24, "desc": "+24% к прибыли на Тоталах", "pack": "Черный рынок"},
    "goat_ronaldo": {"id": "goat_ronaldo", "role": "FW", "tier": 4, "ovr": 99, "nation": "🇵🇹", "name": "🐐 Криштиану Роналду (GOAT)", "val": 24, "desc": "+24% к прибыли на Тоталах", "pack": "Черный рынок"},
    "goat_yashin": {"id": "goat_yashin", "role": "GK", "tier": 4, "ovr": 99, "nation": "🇷🇺", "name": "🐐 Лев Яшин (GOAT)", "val": 25, "desc": "25% кэшбэк при проигрыше", "pack": "Черный рынок"},
    "goat_pep": {"id": "goat_pep", "role": "COACH", "tier": 4, "ovr": 99, "nation": "🇪🇸", "name": "🐐 Пеп Гвардиола (GOAT)", "val": 0.45, "desc": "+0.45 к кэфу Экспресса", "pack": "Черный рынок"}
})

FUT_ROLES = ["FW", "MID", "DEF", "GK", "COACH"]

def parse_user_fut_state(user: dict) -> dict:
    try:
        u_d = dict(user) if user else {}
        raw = json.loads(u_d.get("fut_cards") or "{}")
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        u_d = {}
        raw = {}

    owned = [c for c in (raw.get("_owned") or []) if c in FUT_CARDS]
    squad = {}
    for role in FUT_ROLES:
        cid = raw.get(role, "")
        if cid in FUT_CARDS:
            squad[role] = cid
            if cid not in owned:
                owned.append(cid)
        else:
            squad[role] = ""

    captain = str(raw.get("_captain") or "FW")
    if captain not in FUT_ROLES:
        captain = "FW"

    has_bets_before = (int(u_d.get("wins") or 0) + int(u_d.get("losses") or 0)) > 0
    has_spun_before = bool(u_d.get("last_spin"))

    return {
        "squad": squad,
        "owned": owned,
        "captain": captain,
        "login_streak": int(raw.get("_login_streak") or 0),
        "last_streak_date": str(raw.get("_last_streak_date") or ""),
        "ticket_mode": str(raw.get("_ticket_mode") or "optimal"),
        "sponsor_id": str(raw.get("_sponsor_id") or "sp_1"),
        "sponsor_paid_date": str(raw.get("_sponsor_paid_date") or ""),
        "startup_storage": list(raw.get("_startup_storage") or []),
        "startup_showroom": list(raw.get("_startup_showroom") or []),
        "startup_profit": int(raw.get("_startup_profit") or 0),
        "rookie_bet": 1 if (int(raw.get("_rk_bet") or 0) == 1 or has_bets_before) else 0,
        "rookie_box": int(raw.get("_rk_box") or 0),
        "rookie_spin": 1 if (int(raw.get("_rk_spin") or 0) == 1 or has_spun_before) else 0,
        "rookie_claimed": int(raw.get("_rk_claimed") or 0),
        "vip_until_ts": int(raw.get("_vip_until_ts") or 0),
        "ref_bonus_paid": int(raw.get("_ref_paid") or 0)
    }

def is_user_vip_active(user: dict, st: dict = None) -> bool:
    try:
        u_d = dict(user) if user else {}
        if int(u_d.get("is_vip") or 0) == 1:
            return True
        if st is None:
            st = parse_user_fut_state(u_d)
        return int(st.get("vip_until_ts") or 0) > int(now_msk().timestamp())
    except Exception:
        return False

def dump_user_fut_state(st: dict, is_vip_flag: bool = False) -> str:
    max_stor = 12 if is_vip_flag else 8
    max_show = 4 if is_vip_flag else 3
    payload = {
        **st["squad"],
        "_owned": st["owned"],
        "_captain": st["captain"],
        "_login_streak": st.get("login_streak", 0),
        "_last_streak_date": st.get("last_streak_date", ""),
        "_ticket_mode": st.get("ticket_mode", "optimal"),
        "_sponsor_id": st.get("sponsor_id", "sp_1"),
        "_sponsor_paid_date": st.get("sponsor_paid_date", ""),
        "_startup_storage": st.get("startup_storage", [])[:max_stor],
        "_startup_showroom": st.get("startup_showroom", [])[:max_show],
        "_startup_profit": st.get("startup_profit", 0),
        "_rk_bet": st.get("rookie_bet", 0),
        "_rk_box": st.get("rookie_box", 0),
        "_rk_spin": st.get("rookie_spin", 0),
        "_rk_claimed": st.get("rookie_claimed", 0),
        "_vip_until_ts": st.get("vip_until_ts", 0),
        "_ref_paid": st.get("ref_bonus_paid", 0)
    }
    return json.dumps(payload, ensure_ascii=False)

def calculate_forbes_net_worth(user: dict, st: dict = None) -> int:
    try:
        u_d = dict(user) if user else {}
        if st is None:
            st = parse_user_fut_state(u_d)
        bal = float(u_d.get("balance") or 0)
        stor_val = sum(int(x.get("value") or 0) for x in st.get("startup_storage", []))
        show_val = sum(int(x.get("value") or 0) for x in st.get("startup_showroom", []))
        st_lvl = int(u_d.get("stadium_level") or 1)
        arena_val = sum(int(STADIUM_LEVELS.get(l, {}).get("price", 0)) for l in range(1, st_lvl + 1))
        return int(round(bal + stor_val + show_val + arena_val * 0.5))
    except Exception:
        return int(float(dict(user).get("balance") or 0)) if user else 0

def get_user_fut_buffs_v2(user: dict) -> dict:
    u_d = dict(user) if user else {}
    st = parse_user_fut_state(u_d)
    squad = st["squad"]
    cap_role = st["captain"]
    vip_active = is_user_vip_active(u_d, st)

    filled_slots = sum(1 for r in FUT_ROLES if squad.get(r))
    chemistry_pct = filled_slots * 20
    chem_mult = 1.15 if chemistry_pct == 100 else (1.0 + filled_slots * 0.02)

    def _slot_val(role_key: str) -> float:
        cid = squad.get(role_key, "")
        if cid not in FUT_CARDS:
            return 0.0
        base_v = float(FUT_CARDS[cid]["val"])
        cap_mult = 1.25 if cap_role == role_key else 1.0
        return round(base_v * cap_mult * chem_mult, 2)

    lab_lvl = int(u_d.get("lab_level") or 1)
    lab_bonus = LAB_LEVELS.get(lab_lvl, LAB_LEVELS[1])["odd_bonus"]

    showroom_items = st.get("startup_showroom") or []
    showroom_daily_fc = sum(int(it.get("show_inc") or 0) for it in showroom_items)
    showroom_odd_boost = round(sum(float(it.get("show_odd") or 0.0) for it in showroom_items), 2)
    vip_odd_boost = 0.15 if vip_active else 0.0

    active_ids = set(v for v in squad.values() if v)
    reserve_ids = [cid for cid in st["owned"] if cid not in active_ids]

    return {
        "fw_card": FUT_CARDS.get(squad.get("FW", "")),
        "mid_card": FUT_CARDS.get(squad.get("MID", "")),
        "def_card": FUT_CARDS.get(squad.get("DEF", "")),
        "gk_card": FUT_CARDS.get(squad.get("GK", "")),
        "co_card": FUT_CARDS.get(squad.get("COACH", "")),
        "totals_profit_pct": round(_slot_val("FW"), 1),
        "outcomes_profit_pct": round(_slot_val("MID"), 1),
        "handicap_profit_pct": round(_slot_val("DEF"), 1),
        "loss_cashback_pct": min(35.0, round(_slot_val("GK"), 1)),
        "express_odd_boost": round(_slot_val("COACH"), 2),
        "lab_odd_boost": round(lab_bonus + showroom_odd_boost + vip_odd_boost + (0.04 if chemistry_pct == 100 else 0.0), 2),
        "showroom_daily_fc": showroom_daily_fc,
        "showroom_odd_boost": showroom_odd_boost,
        "vip_odd_boost": vip_odd_boost,
        "is_vip_active": vip_active,
        "chemistry": chemistry_pct,
        "captain": cap_role,
        "owned_ids": st["owned"],
        "reserve_ids": reserve_ids,
        "squad_ids": squad,
        "full_state": st
    }

globals()["get_user_fut_buffs"] = get_user_fut_buffs_v2

async def open_fut_pack_v2(user_id: int, cost: int, card_id: str) -> dict:
    user = await db_manager.get_user(user_id)
    if user["balance"] < cost:
        return {"ok": False, "error": f"Недостаточно средств! Нужно {cost} FC."}

    card = FUT_CARDS[card_id]
    role = card["role"]
    st = parse_user_fut_state(user)
    vip_act = is_user_vip_active(user, st)

    cashback = 0
    if card_id in st["owned"]:
        cashback = int(cost * 0.45) if cost > 0 else 750
        status_note = f"♻️ Дубликат! Карточка уже в коллекции — начислен бонус +{cashback} FC!"
    else:
        st["owned"].append(card_id)
        cur_id = st["squad"].get(role, "")
        cur_card = FUT_CARDS.get(cur_id)
        if not cur_card or card["val"] > cur_card["val"]:
            st["squad"][role] = card_id
            status_note = "✅ Новая карточка добавлена в коллекцию и сразу вышла в стартовый состав!"
        else:
            status_note = "📚 Новая карточка добавлена в коллекцию! (Резервные карты можно обменять в СПК)."

    new_bal = round(user["balance"] - cost + cashback, 1)
    await db_manager.exec(
        "UPDATE users SET balance = $1, fut_cards = $2 WHERE user_id = $3",
        new_bal, dump_user_fut_state(st, vip_act), user_id
    )
    return {"ok": True, "card": card, "new_balance": new_bal, "status_note": status_note, "st": st}

db_manager.open_fut_pack_db = open_fut_pack_v2

def get_express_boost_multiplier(num_legs: int) -> tuple[float, int]:
    if num_legs >= 6:
        return 1.25, 25
    elif num_legs == 5:
        return 1.15, 15
    elif num_legs == 4:
        return 1.10, 10
    elif num_legs == 3:
        return 1.05, 5
    return 1.0, 0

async def fast_create_pending_bet(
    user_id: int, username: str, match_title: str, pick: str,
    amount: int, odds: float, win_prob: float, settle_ts: int,
    bet_type: str = "single", legs_json: str = "[]", insure_paid: bool = False
) -> dict:
    user = await db_manager.get_user(user_id, username)
    if amount < 10:
        return {"ok": False, "error": "Минимальная сумма ставки — 10 FC!"}

    ins_fee = int(round(amount * 0.10)) if insure_paid else 0
    total_deduct = amount + ins_fee
    if user["balance"] < total_deduct:
        return {"ok": False, "error": f"Недостаточно средств! С учетом страховки нужно {total_deduct} FC."}

    is_all_in = 1 if (user["balance"] - total_deduct < 10.0) else 0
    fav_club = user.get("favorite_club") or ""
    is_fav_club = 1 if (fav_club and (fav_club in match_title or fav_club in pick)) else 0

    try:
        parsed_legs = json.loads(legs_json or "[]")
    except Exception:
        parsed_legs = []

    buffs = get_user_fut_buffs_v2(user)
    st = buffs["full_state"]
    vip_act = buffs["is_vip_active"]
    st["rookie_bet"] = 1

    # ЗАЩИТА ОТ МУЛЬТИАККАУНТОВ: реферальный бонус начисляется пригласившему только при первой ставке друга
    ref_inviter = int(user.get("referred_by") or 0)
    if ref_inviter > 0 and st.get("ref_bonus_paid", 0) == 0:
        st["ref_bonus_paid"] = 1
        try:
            await db_manager.exec("UPDATE users SET balance = balance + 500 WHERE user_id = $1", ref_inviter)
            await bot.send_message(
                ref_inviter,
                f"🤝 <b>РЕФЕРАЛЬНЫЙ БОНУС АКТИВИРОВАН!</b>\n\n"
                f"<blockquote>Твой друг <b>{username}</b> сделал свою первую ставку в игре! Тебе начислено <b><code>+500 FC</code></b>!</blockquote>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    exp_mult, exp_pct = get_express_boost_multiplier(len(parsed_legs) if bet_type == "express" else 1)

    boosted_base = round(odds * exp_mult, 2)
    final_odds = round(boosted_base + buffs["lab_odd_boost"], 2)
    if bet_type == "express" and buffs["express_odd_boost"] > 0:
        final_odds = round(final_odds + buffs["express_odd_boost"], 2)

    active_booster = user.get("active_booster") or ""
    booster_used = ""
    if active_booster == "boost035":
        final_odds = round(final_odds + 0.35, 2)
        booster_used = "boost035"
    elif active_booster == "insure50" or insure_paid:
        booster_used = "insure50"

    new_balance = round(user["balance"] - total_deduct, 1)
    created_str = now_msk().strftime("%d.%m %H:%M")
    next_booster_val = "" if (active_booster and not insure_paid) else active_booster

    await db_manager.exec(
        "UPDATE users SET balance = $1, active_booster = $2, fut_cards = $3 WHERE user_id = $4",
        new_balance, next_booster_val, dump_user_fut_state(st, vip_act), user_id
    )

    if db_manager.use_pg:
        bet_id = await db_manager.fetchval("""
            INSERT INTO bets (
                user_id, match_title, pick, amount, odds, status, bet_type,
                win_prob, settle_ts, created_at, legs_json, booster_used, is_all_in, is_fav_club
            ) VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8, $9, $10, $11, $12, $13) RETURNING bet_id
        """, user_id, match_title, pick, amount, final_odds, bet_type, win_prob, settle_ts, created_str, legs_json, booster_used, is_all_in, is_fav_club)
    else:
        async with aiosqlite.connect(db_manager.sqlite_path) as db:
            cur = await db.execute("""
                INSERT INTO bets (
                    user_id, match_title, pick, amount, odds, status, bet_type,
                    win_prob, settle_ts, created_at, legs_json, booster_used, is_all_in, is_fav_club
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, match_title, pick, amount, final_odds, bet_type, win_prob, settle_ts, created_str, legs_json, booster_used, is_all_in, is_fav_club))
            bet_id = cur.lastrowid
            await db.commit()

    asyncio.create_task(db_manager.unlock_achievement(user_id, "first_bet"))
    if bet_type == "express":
        asyncio.create_task(db_manager.unlock_achievement(user_id, "first_express"))
        push_live_ticker(f"⚡ Каппер {username} зарядил Экспресс с кэфом {final_odds} на выплату {round(amount * final_odds)} FC!")

    return {
        "ok": True, "bet_id": bet_id, "final_odds": final_odds, "exp_boost_pct": exp_pct,
        "booster_used": booster_used, "is_fav_club": is_fav_club, "total_deduct": total_deduct,
        "new_balance": new_balance, "potential_win": round(amount * final_odds, 1)
    }

db_manager.create_pending_bet = fast_create_pending_bet
ACHIEVEMENTS_CONFIG.update({
    "winter_2027": {"title": "🎄 Зимний Чемпион", "desc": "Сделать ставку в новогоднем обновлении бота", "reward": 400},
    "exact_score": {"title": "🎯 Снайпер точного счета", "desc": "Угадать точный счет футбольного матча", "reward": 3500},
    "first_half_win": {"title": "⏱ Доминатор 1-го тайма", "desc": "Выиграть ставку на исход или тотал 1-го тайма", "reward": 600},
    "secret_agent": {"title": "🕵️‍♂️ Секретный агент ИИ", "desc": "Заключить пари по Секретной ставке дня", "reward": 450},
    "fut_full_squad": {"title": "👕 Полная сыгранность (100%)", "desc": "Заполнить все 5 позиций в составе FUT", "reward": 1500},
    "sbc_master": {"title": "🔄 Мастер СПК (Крафт)", "desc": "Обменять 3 резервные карточки на Золотой пак", "reward": 750},
    "container_hunter": {"title": "📦 Портовый Охотник", "desc": "Вскрыть свой первый контейнер в Порту", "reward": 500},
    "ark_billionaire": {"title": "🌌 Властелин Ковчега", "desc": "Вскрыть Орбитальный Ковчег за 300 000 FC", "reward": 10000},
    "vip_club_member": {"title": "👑 Член VIP-Клуба", "desc": "Приобрести VIP-статус за FC", "reward": 1500},
    "p2p_merchant": {"title": "🌐 Купец P2P-Биржи", "desc": "Выставить или купить находку на P2P-рынке", "reward": 800},
    "stadium_lvl_5": {"title": "🏟 Архитектор Колизея", "desc": "Построить стадион 5-го уровня", "reward": 2500},
    "stadium_lvl_10": {"title": "👑 Император Арен", "desc": "Возвести Мега-Арену Легенд (10 уровень)", "reward": 15000},
    "pvp_gladiator": {"title": "⚔️ Гладиатор пенальти", "desc": "Одержать 5 побед в PvP-дуэлях", "reward": 1500},
    "bm_tycoon": {"title": "🔨 Теневой магнат", "desc": "Сделать ставку на аукционе Черного рынка", "reward": 500},
    "matchday_vip": {"title": "🎟 Аншлаг в VIP-ложе", "desc": "Провести домашний Матчдэй с VIP-тарифом билетов", "reward": 650}
})

ACTIVE_LIVE_WIDGETS = {}
LAST_PVP_MATCH = {}

# ================= СБОРКА ПУБЛИЧНОГО ПРОФИЛЯ ЛЮБОГО ИГРОКА ДЛЯ ОБЗОРА =================
def build_public_player_profile(target_user: dict) -> dict:
    u_d = dict(target_user)
    buffs = get_user_fut_buffs_v2(u_d)
    st = buffs["full_state"]
    vip_act = buffs["is_vip_active"]
    incog = int(u_d.get("is_incognito") or 0) == 1
    st_lvl = int(u_d.get("stadium_level") or 1)
    lab_lvl = int(u_d.get("lab_level") or 1)
    rank_name, _ = get_user_rank_info(u_d["balance"], 1 if vip_act else 0)

    total_bets = int(u_d.get("wins") or 0) + int(u_d.get("losses") or 0)
    winrate = round((int(u_d.get("wins") or 0) / total_bets) * 100) if total_bets > 0 else 0

    try:
        ach_list = json.loads(u_d.get("achievements") or "[]")
    except Exception:
        ach_list = []

    squad_cards = {}
    for r_key in FUT_ROLES:
        cid = buffs["squad_ids"].get(r_key, "")
        squad_cards[r_key] = FUT_CARDS.get(cid) if cid in FUT_CARDS else None

    display_name = f"🕶 Скрытый каппер #{str(u_d['user_id'])[-4:]}" if incog else u_d["username"]

    return {
        "user_id": u_d["user_id"],
        "username": display_name,
        "raw_username": u_d["username"],
        "is_incognito": incog,
        "is_vip": 1 if vip_act else 0,
        "rank": rank_name,
        "favorite_club": "" if incog else (u_d.get("favorite_club") or ""),
        "balance": round(u_d["balance"], 1),
        "forbes_capital": calculate_forbes_net_worth(u_d, st),
        "wins": int(u_d.get("wins") or 0),
        "losses": int(u_d.get("losses") or 0),
        "winrate": winrate,
        "streak": int(u_d.get("streak") or 0),
        "profit": round(u_d.get("profit") or 0, 1),
        "pvp_wins": int(u_d.get("pvp_wins") or 0),
        "stadium_level": st_lvl,
        "stadium_name": STADIUM_LEVELS.get(st_lvl, STADIUM_LEVELS[1])["name"],
        "lab_level": lab_lvl,
        "lab_name": LAB_LEVELS.get(lab_lvl, LAB_LEVELS[1])["name"],
        "chemistry": buffs["chemistry"],
        "captain_role": buffs["captain"],
        "squad_cards": squad_cards,
        "owned_cards_count": len(buffs["owned_ids"]),
        "showroom": st.get("startup_showroom", []),
        "showroom_daily_fc": buffs["showroom_daily_fc"],
        "showroom_odd_boost": buffs["showroom_odd_boost"],
        "trophies_count": len(ach_list)
    }

# ================= КАЛЬКУЛЯТОР 45+ РЫНКОВ =================
_orig_evaluate_custom_market = evaluate_custom_market
_orig_evaluate_leg_result = evaluate_leg_result

def evaluate_custom_market(match: dict, pick_code: str) -> dict | None:
    code = pick_code.lower()
    t1, t2 = translate_team_ru(match["home_team"]), translate_team_ru(match["away_team"])
    lam_h = match.get("lam_h", 1.45)
    lam_a = match.get("lam_a", 1.20)
    lam_total = match.get("exp_goals", 2.65)
    odds = match["odds"]

    if code.startswith("cs_"):
        parts = code.split("_")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            gh, ga = int(parts[1]), int(parts[2])
            p_score = poisson_pmf(gh, lam_h) * poisson_pmf(ga, lam_a)
            p_clean = max(0.035, min(0.22, p_score))
            odd_cs = round(max(5.20, min(29.0, 1.0 / (p_clean * 1.08))), 2)
            return {"pick_code": code, "label": f"Точный счёт {gh}:{ga}", "odds": odd_cs, "prob": round(p_clean * 100, 1)}

    if code.startswith("h1_"):
        lam_h1 = lam_total * 0.44
        p_0 = math.exp(-lam_h1)
        p_1 = lam_h1 * math.exp(-lam_h1)
        p_tb05 = max(0.52, min(0.84, 1.0 - p_0))
        p_tb15 = max(0.22, min(0.58, 1.0 - (p_0 + p_1)))

        if code == "h1_p1":
            odd_v = round(max(1.65, odds["p1"] * 1.32), 2)
            return {"pick_code": code, "label": f"1-й тайм: П1 ({t1})", "odds": odd_v, "prob": round(100 / odd_v, 1)}
        elif code == "h1_x":
            odd_v = round(max(1.90, min(2.65, odds["x"] * 0.64)), 2)
            return {"pick_code": code, "label": "1-й тайм: Ничья (Х)", "odds": odd_v, "prob": round(100 / odd_v, 1)}
        elif code == "h1_p2":
            odd_v = round(max(1.75, odds["p2"] * 1.34), 2)
            return {"pick_code": code, "label": f"1-й тайм: П2 ({t2})", "odds": odd_v, "prob": round(100 / odd_v, 1)}
        elif code == "h1_tb_0.5":
            odd_v = round(max(1.22, 1.0 / (p_tb05 * 1.05)), 2)
            return {"pick_code": code, "label": "1-й тайм: ТБ 0.5", "odds": odd_v, "prob": round(p_tb05 * 100, 1)}
        elif code == "h1_tb_1.5":
            odd_v = round(max(2.15, 1.0 / (p_tb15 * 1.06)), 2)
            return {"pick_code": code, "label": "1-й тайм: ТБ 1.5", "odds": odd_v, "prob": round(p_tb15 * 100, 1)}
        elif code == "h1_tm_1.5":
            odd_v = round(max(1.28, 1.0 / ((1.0 - p_tb15) * 1.05)), 2)
            return {"pick_code": code, "label": "1-й тайм: ТМ 1.5", "odds": odd_v, "prob": round((1.0 - p_tb15) * 100, 1)}

    if code in ("bh_yes", "bh_no"):
        lam_h1 = lam_total * 0.44
        lam_h2 = lam_total * 0.56
        p_yes = max(0.38, min(0.74, (1.0 - math.exp(-lam_h1)) * (1.0 - math.exp(-lam_h2))))
        if code == "bh_yes":
            odd_v = round(max(1.48, 1.0 / (p_yes * 1.05)), 2)
            return {"pick_code": code, "label": "Гол в обоих таймах: Да", "odds": odd_v, "prob": round(p_yes * 100, 1)}
        else:
            odd_v = round(max(1.85, 1.0 / ((1.0 - p_yes) * 1.05)), 2)
            return {"pick_code": code, "label": "Гол в обоих таймах: Нет", "odds": odd_v, "prob": round((1.0 - p_yes) * 100, 1)}

    return _orig_evaluate_custom_market(match, pick_code)

def evaluate_leg_result(pick_code: str, home_score: int, away_score: int) -> str:
    code = pick_code.lower()
    total = home_score + away_score
    if code.startswith("cs_"):
        parts = code.split("_")
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            return "win" if (home_score == int(parts[1]) and away_score == int(parts[2])) else "loss"
    if code == "h1_tb_0.5":
        return "win" if total >= 1 else "loss"
    elif code == "h1_tb_1.5":
        return "win" if total >= 2 else "loss"
    elif code == "h1_tm_1.5":
        return "win" if total <= 2 else "loss"
    elif code == "h1_p1":
        return "win" if home_score > away_score else "loss"
    elif code == "h1_x":
        return "win" if home_score == away_score else "loss"
    elif code == "h1_p2":
        return "win" if away_score > home_score else "loss"
    elif code == "bh_yes":
        return "win" if total >= 2 else "loss"
    elif code == "bh_no":
        return "win" if total <= 1 else "loss"
    return _orig_evaluate_leg_result(pick_code, home_score, away_score)

def build_ai_battle_and_radar(m: dict) -> tuple[dict, dict]:
    o = m["odds"]
    probs = calculate_ai_probabilities(o)
    t1, t2 = translate_team_ru(m["home_team"]), translate_team_ru(m["away_team"])
    exp_g = m["exp_goals"]

    if probs["p1"] >= 56:
        prag_mkt = evaluate_custom_market(m, "f10") or {"pick_code": "1x", "label": f"1Х ({t1})", "odds": o["1x"]}
        prag_text = f"Домашний xG {t1} составляет {m.get('lam_h', 1.5)}. Подстраховка нулевой форой исключает риск ничьей."
    elif probs["p2"] >= 54:
        prag_mkt = evaluate_custom_market(m, "f20") or {"pick_code": "x2", "label": f"Х2 ({t2})", "odds": o["x2"]}
        prag_text = f"{t2} стабильнее по очкам на дистанции. Берем надежный исход с возвратом при ничьей."
    else:
        prag_mkt = evaluate_custom_market(m, "tb_1.5") or {"pick_code": "tb_1.5", "label": "ТБ 1.5", "odds": o["tb15"]}
        prag_text = f"Суммарный потенциал атаки {exp_g} xG дает 82% вероятности минимум на 2 забитых мяча."

    cs_code = "cs_" + m.get("best_score", "2:1").replace(":", "_")
    if exp_g >= 2.75:
        rom_mkt = evaluate_custom_market(m, "bh_yes") or {"pick_code": "btts", "label": "Обе забьют: Да", "odds": o["btts"]}
        rom_text = "Оборона обеих команд оставляет свободные зоны! Жду открытый футбол и голы в обоих таймах."
    elif abs(probs["p1"] - probs["p2"]) <= 12:
        rom_mkt = evaluate_custom_market(m, cs_code) or {"pick_code": "x", "label": "Ничья (Х)", "odds": o["x"]}
        rom_text = f"Равные соперники ({probs['p1']}% vs {probs['p2']}%). Идеальный сценарий для охоты за большим кэфом!"
    else:
        rom_mkt = evaluate_custom_market(m, "h1_tb_1.5") or {"pick_code": "tb_2.5", "label": "ТБ 2.5", "odds": o["tb25"]}
        rom_text = "Фаворит пойдет в агрессивный прессинг с первых минут — ждем быстрые голы уже до перерыва!"

    ai_battle = {
        "pragmatist": {
            "name": "📊 Алгоритм xG (Прагматик)", "text": prag_text,
            "pick_code": prag_mkt["pick_code"], "pick_label": prag_mkt["label"], "odds": prag_mkt["odds"]
        },
        "romantic": {
            "name": "🔥 Кураж-Скаут (Романтик)", "text": rom_text,
            "pick_code": rom_mkt["pick_code"], "pick_label": rom_mkt["label"], "odds": rom_mkt["odds"]
        }
    }

    seed_val = sum(ord(c) for c in str(m["event_id"]))
    crowd_p1 = min(82, max(14, int(probs["p1"] + (seed_val % 9) - 4)))
    crowd_x = min(35, max(10, int(probs["x"])))
    crowd_p2 = max(8, 100 - crowd_p1 - crowd_x)

    smart_mkt = evaluate_custom_market(m, "tb_2.5" if exp_g >= 2.65 else ("itb1_1.5" if probs["p1"] >= probs["p2"] else "itb2_1.5"))
    if not smart_mkt:
        smart_mkt = {"pick_code": "btts", "label": "Обе забьют: Да", "odds": o["btts"]}

    radar = {
        "crowd_p1": crowd_p1, "crowd_x": crowd_x, "crowd_p2": crowd_p2,
        "smart_money": {
            "title": "👑 Выбор Топ-10 капперов",
            "pick_code": smart_mkt["pick_code"], "pick_label": smart_mkt["label"],
            "odds": smart_mkt["odds"], "share_pct": 68 + (seed_val % 19)
        }
    }
    return ai_battle, radar

def build_full_match_payload(m: dict, l_key: str, l_title: str) -> dict:
    m["home_team"] = translate_team_ru(m["home_team"])
    m["away_team"] = translate_team_ru(m["away_team"])
    m["teams"] = f"{m['home_team']} — {m['away_team']}"

    odds = m["odds"]
    probs = calculate_ai_probabilities(odds)

    totals_list = []
    for line_val in ["1.5", "2.0", "2.5", "3.0", "3.5"]:
        tb_m = evaluate_custom_market(m, f"tb_{line_val}")
        tm_m = evaluate_custom_market(m, f"tm_{line_val}")
        if tb_m and tm_m:
            totals_list.append({
                "line": line_val,
                "tb_code": tb_m["pick_code"], "tb_odd": tb_m["odds"], "tb_label": tb_m["label"],
                "tm_code": tm_m["pick_code"], "tm_odd": tm_m["odds"], "tm_label": tm_m["label"]
            })

    itb_list = []
    for line_val in ["0.5", "1.5", "2.5"]:
        i1 = evaluate_custom_market(m, f"itb1_{line_val}")
        i2 = evaluate_custom_market(m, f"itb2_{line_val}")
        if i1 and i2:
            itb_list.append({
                "line": line_val,
                "itb1_code": i1["pick_code"], "itb1_odd": i1["odds"], "itb1_label": i1["label"],
                "itb2_code": i2["pick_code"], "itb2_odd": i2["odds"], "itb2_label": i2["label"]
            })

    half_markets = []
    for h_code in ["h1_p1", "h1_x", "h1_p2", "h1_tb_0.5", "h1_tb_1.5", "h1_tm_1.5", "bh_yes", "bh_no"]:
        hm = evaluate_custom_market(m, h_code)
        if hm:
            half_markets.append(hm)

    exact_scores = []
    for sc_pair in ["1_0", "2_0", "2_1", "3_0", "3_1", "0_0", "1_1", "2_2", "0_1", "0_2", "1_2", "0_3"]:
        c_mkt = evaluate_custom_market(m, f"cs_{sc_pair}")
        if c_mkt:
            exact_scores.append({
                "score": sc_pair.replace("_", ":"),
                "pick_code": c_mkt["pick_code"],
                "label": c_mkt["label"],
                "odds": c_mkt["odds"]
            })

    ai_battle, radar = build_ai_battle_and_radar(m)
    elite_score = (get_elite_bonus(m["home_team"]) + get_elite_bonus(m["away_team"])) * 100
    is_top_banner = (elite_score >= 30 or l_key in ("ucl", "epl", "laliga", "rpl") or bool(m.get("is_live")))
    today_dm = now_msk().strftime("%d.%m")
    is_today = bool(m.get("is_live")) or str(m.get("short_date", "")).startswith(today_dm)

    return {
        "event_id": m["event_id"], "league_key": l_key, "league_title": l_title,
        "teams": m["teams"], "home_team": m["home_team"], "away_team": m["away_team"],
        "venue": m.get("venue", "Центральная арена"),
        "is_live": bool(m.get("is_live")), "is_today": is_today,
        "live_score": m.get("live_score", "0:0"), "live_detail": m.get("live_detail", ""),
        "date": m["date"], "short_date": m["short_date"], "start_ts": m["start_ts"],
        "exp_goals": m["exp_goals"], "lam_h": m.get("lam_h", 1.4), "lam_a": m.get("lam_a", 1.2),
        "best_score": m["best_score"], "h_stats": m.get("h_stats", {}), "a_stats": m.get("a_stats", {}),
        "odds": odds, "probs": probs, "totals_markets": totals_list, "itb_markets": itb_list,
        "half_markets": half_markets, "exact_scores": exact_scores,
        "ai_battle": ai_battle, "radar": radar, "is_top": is_top_banner
    }

# ================= СВЕРХБЫСТРЫЙ ПРЕДВАРИТЕЛЬНЫЙ КЭШ РОСПИСИ =================
_IS_REFRESHING_SCHEDULE = False
PRECOMPUTED_WEBAPP_CACHE = {
    "built_at": 0, "source_updated_at": 0, "filtered_db": {},
    "leagues_nav": [], "matches": [], "daily_express": None, "secret_offer": None
}
SHARED_DB_CACHE = {
    "leaderboard_ts": 0, "leaderboard_raw": [],
    "bm_ts": 0, "bm_lot": None,
    "se_round_key": "", "se_matches": [], "se_ts": 0
}

async def _trigger_background_schedule_refresh():
    global _IS_REFRESHING_SCHEDULE
    if _IS_REFRESHING_SCHEDULE:
        return
    _IS_REFRESHING_SCHEDULE = True
    try:
        await get_real_matches(force_refresh=True)
    except Exception as e:
        logging.warning(f"Фоновое обновление расписания: {e}")
    finally:
        _IS_REFRESHING_SCHEDULE = False

async def get_matches_instant() -> dict:
    now_ts = int(now_msk().timestamp())
    if SCHEDULE_CACHE["data"]:
        if (now_ts - SCHEDULE_CACHE["updated_at"] > CACHE_TTL) and not _IS_REFRESHING_SCHEDULE:
            SCHEDULE_CACHE["updated_at"] = now_ts
            asyncio.create_task(_trigger_background_schedule_refresh())
        return SCHEDULE_CACHE["data"]
    return await get_real_matches()

async def get_precomputed_webapp_line() -> dict:
    raw_db = await get_matches_instant()
    now_ts = int(now_msk().timestamp())
    src_ts = SCHEDULE_CACHE.get("updated_at", 0)

    if (
        PRECOMPUTED_WEBAPP_CACHE["matches"]
        and PRECOMPUTED_WEBAPP_CACHE["source_updated_at"] == src_ts
        and (now_ts - PRECOMPUTED_WEBAPP_CACHE["built_at"] < 45)
    ):
        return PRECOMPUTED_WEBAPP_CACHE

    filtered_db = {}
    leagues_nav = []
    all_matches = []
    two_weeks_limit = now_ts + (14 * 86400)

    for l_key, cfg in LEAGUES_CONFIG.items():
        l_data = raw_db.get(l_key, {})
        raw_m_dict = l_data.get("matches", {})
        active_m_dict = {
            m_id: m for m_id, m in raw_m_dict.items()
            if m.get("is_live") or m["start_ts"] > now_ts
        }
        has_2w = any(m.get("is_live") or m["start_ts"] <= two_weeks_limit for m in active_m_dict.values())

        filtered_db[l_key] = {
            "title": cfg["title"], "slug": cfg["slug"],
            "matches": active_m_dict, "has_2w_matches": has_2w
        }

        if l_key in OTHER_LEAGUES and not has_2w:
            continue
        if not active_m_dict:
            continue

        sliced_items = list(active_m_dict.values())[:15]
        league_payloads = [build_full_match_payload(m, l_key, cfg["title"]) for m in sliced_items]

        if league_payloads:
            all_matches.extend(league_payloads)
            leagues_nav.append({
                "key": l_key,
                "title": cfg["title"],
                "count": len(league_payloads),
                "live_count": sum(1 for x in league_payloads if x["is_live"])
            })

    chronological_matches = sorted(
        all_matches,
        key=lambda x: (0 if x["is_live"] else 1, x["start_ts"])
    )

    daily_exp = build_daily_express_data(filtered_db)
    if daily_exp and daily_exp.get("legs"):
        for lg in daily_exp["legs"]:
            if " — " in lg.get("teams", ""):
                pa, pb = lg["teams"].split(" — ", 1)
                lg["teams"] = f"{translate_team_ru(pa)} — {translate_team_ru(pb)}"

    secret_bet_offer = None
    top_6_up = get_top_6_upcoming_matches(filtered_db)
    if top_6_up:
        best_v = max(top_6_up, key=lambda x: x["exp_goals"])
        v_mkt = evaluate_custom_market(best_v, "tb_2.0")
        if v_mkt:
            secret_bet_offer = {
                "league_key": best_v["league_key"],
                "event_id": best_v["event_id"],
                "teams": f"{translate_team_ru(best_v['home_team'])} — {translate_team_ru(best_v['away_team'])}",
                "date": best_v["short_date"],
                "exp_goals": best_v["exp_goals"],
                "pick_code": "tb_2.0",
                "pick_label": v_mkt["label"],
                "odds": v_mkt["odds"],
                "prob": v_mkt["prob"]
            }

    PRECOMPUTED_WEBAPP_CACHE.update({
        "built_at": now_ts, "source_updated_at": src_ts,
        "filtered_db": filtered_db, "leagues_nav": leagues_nav,
        "matches": chronological_matches,
        "daily_express": {"total_odd": daily_exp["total_odd"], "legs": daily_exp["legs"]} if daily_exp else None,
        "secret_offer": secret_bet_offer
    })
    return PRECOMPUTED_WEBAPP_CACHE

# ================= ПРОВЕРКА УСЛОВИЙ СПОНСОРА И СТРИКА ВХОДОВ =================
def compute_login_streak_info(st: dict) -> tuple[int, bool]:
    today_dt = now_msk().date()
    today_str = today_dt.strftime("%Y-%m-%d")
    yesterday_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    last_d = st.get("last_streak_date", "")
    cur_s = int(st.get("login_streak") or 0)

    if last_d == today_str:
        return max(1, min(7, cur_s)), False
    elif last_d == yesterday_str:
        next_s = (cur_s % 7) + 1
        return next_s, True
    else:
        return 1, True

def check_sponsor_quest_done(sp_id: str, user: dict, st: dict, active_bets: list) -> bool:
    sp = next((s for s in STADIUM_SPONSORS if s["id"] == sp_id), STADIUM_SPONSORS[0])
    code = sp["task_code"]
    if code == "any_bet":
        return len(active_bets) > 0 or int(user.get("wins") or 0) + int(user.get("losses") or 0) > 0
    elif code == "bet_500_or_pvp":
        return any(b["amount"] >= 500 for b in active_bets) or int(user.get("pvp_wins") or 0) > 0
    elif code == "express_bet":
        return any(b.get("bet_type") == "express" for b in active_bets)
    elif code == "streak_or_fut":
        filled = sum(1 for r in FUT_ROLES if st["squad"].get(r))
        return int(user.get("streak") or 0) >= 1 or filled >= 3
    elif code == "showroom_and_bet":
        return len(active_bets) > 0 and len(st.get("startup_showroom") or []) >= 1
    return True

# ================= REST API HANDLERS ДЛЯ WEBAPP =================
_WEBAPP_HTML_MEMO = None

async def handle_options(request):
    return web.Response(status=200, headers=CORS_HEADERS)

async def handle_ping(request):
    return web.Response(text="AI_BET_BOT Ultra-Fast Engine is running 24/7!", headers=CORS_HEADERS)

async def serve_webapp_html(request):
    """Отдает webapp.html напрямую из оперативной памяти (0 обращений к диску при наплыве трафика)"""
    global _WEBAPP_HTML_MEMO
    if _WEBAPP_HTML_MEMO is None:
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp.html")
        if not os.path.exists(html_path):
            return web.Response(text="<h2>Файл webapp.html еще не загружен.</h2>", content_type="text/html", headers=CORS_HEADERS)
        with open(html_path, "r", encoding="utf-8") as f:
            _WEBAPP_HTML_MEMO = f.read()
    return web.Response(text=_WEBAPP_HTML_MEMO, content_type="text/html", headers=CORS_HEADERS)

async def api_get_match_ai(request):
    l_key = request.match_info.get("league_key", "")
    m_id = request.match_info.get("event_id", "")
    db = await get_matches_instant()
    l_data = db.get(l_key, {})
    match = l_data.get("matches", {}).get(m_id)
    if not match:
        return web.json_response({"ok": False, "error": "Матч не найден"}, headers=CORS_HEADERS)

    is_live = bool(match.get("is_live"))
    if is_live:
        async with aiohttp.ClientSession() as session:
            fresh = await fetch_real_match_result(session, match["league_slug"], str(match["event_id"]))
            if fresh.get("ok"):
                match["live_score"] = fresh["score_str"]
                match["live_detail"] = fresh["detail"] or "LIVE"

    odds = match["odds"]
    probs = calculate_ai_probabilities(odds)
    league_title = l_data.get("title", "Турнир")
    t1, t2 = translate_team_ru(match["home_team"]), translate_team_ru(match["away_team"])
    cache_k = f"live_{match['event_id']}_{match.get('live_score', '')}" if is_live else match["event_id"]

    if is_live:
        prompt = (
            f"Матч идет в ПРЯМОМ ЭФИРЕ (LIVE). Турнир: {league_title}.\n"
            f"Матч: {t1} — {t2}. Текущий счет: {match['live_score']} ({match['live_detail']}).\n"
            f"Потенциал xG: {match['exp_goals']}.\n"
            f"Дай краткий живой комментарий на русском языке (до 45 слов) в 2 пункта:\n"
            f"1. 🔴 Оценка хода игры по текущему счету.\n2. 📊 Ожидания на остаток матча."
        )
        ai_text = await ask_ai_cached(cache_k, prompt, ttl=300) or smart_local_match_analysis(match, probs)
    else:
        prompt = (
            f"Предстоящий матч. Турнир: {league_title}. Дата: {match['date']}.\n"
            f"Хозяева: {t1}. Гости: {t2}.\n"
            f"Ожидаемые голы xG: {match['exp_goals']}. Линия: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}, ТБ 2.5={odds['tb25']}, ОЗ={odds['btts']}.\n"
            f"Дай краткий разбор строго на русском языке (до 50 слов) в 2 пункта:\n1. ⚔️ Тактика и форма команд.\n2. 🎯 Главный аргумент по тоталу или исходу."
        )
        ai_text = await ask_ai_cached(cache_k, prompt) or smart_local_match_analysis(match, probs)

    return web.json_response({
        "ok": True,
        "ai_analysis": ai_text,
        "live_score": match.get("live_score", "0:0"),
        "live_detail": match.get("live_detail", "")
    }, headers=CORS_HEADERS)

def format_archive_bet_legs(b: dict) -> list[dict]:
    st_overall = b.get("status", "loss")
    try:
        legs = json.loads(b.get("legs_json") or "[]")
    except Exception:
        legs = []

    result_legs = []
    if legs:
        for lg in legs:
            raw_teams = str(lg.get("teams") or b.get("match_title") or "Матч")
            if " — " in raw_teams:
                p_a, p_b = raw_teams.split(" — ", 1)
                ru_teams = f"{translate_team_ru(p_a)} — {translate_team_ru(p_b)}"
            else:
                ru_teams = raw_teams

            leg_st = lg.get("final_status") or (st_overall if len(legs) == 1 else "loss")
            f_sc = lg.get("final_score") or (b.get("score_result", "") if len(legs) == 1 else "")
            if leg_st == "win":
                badge_txt = "✅ Зашёл" + (" ⚡Досрочно" if lg.get("early_win") else "")
            elif leg_st == "push":
                badge_txt = "🔄 Возврат"
            elif st_overall == "cashout":
                badge_txt = "💸 Выкуплен"
            else:
                badge_txt = "❌ Не зашёл"

            result_legs.append({
                "teams": ru_teams,
                "pick_label": lg.get("pick_label") or lg.get("pick_code") or b.get("pick", ""),
                "odds": lg.get("odds") or b.get("odds", 1.0),
                "score": f_sc,
                "status": leg_st,
                "badge": badge_txt
            })
    else:
        badge_txt = "✅ Зашёл" if st_overall == "win" else ("🔄 Возврат" if st_overall == "push" else ("💸 Выкуплен" if st_overall == "cashout" else "❌ Не зашёл"))
        result_legs.append({
            "teams": b.get("match_title", "Матч"),
            "pick_label": b.get("pick", ""),
            "odds": b.get("odds", 1.0),
            "score": b.get("score_result", ""),
            "status": st_overall,
            "badge": badge_txt
        })
    return result_legs

def build_fast_user_dict(user: dict, active_bets: list = None) -> dict:
    buffs = get_user_fut_buffs_v2(user)
    st = buffs["full_state"]
    vip_act = buffs["is_vip_active"]
    st_lvl = int(user.get("stadium_level") or 1)
    lab_lvl = int(user.get("lab_level") or 1)
    rank_name, daily_bonus_amt = get_user_rank_info(user["balance"], 1 if vip_act else 0)
    today_str = now_msk().strftime("%Y-%m-%d")

    streak_day, can_claim_streak = compute_login_streak_info(st)
    can_claim_bonus = can_claim_streak and (user.get("last_bonus") != today_str)

    try:
        achievements_unlocked = json.loads(user.get("achievements") or "[]")
    except Exception:
        achievements_unlocked = []

    sp_id = st.get("sponsor_id", "sp_1")
    quest_ok = check_sponsor_quest_done(sp_id, user, st, active_bets or [])

    rk_bet = 1 if (st.get("rookie_bet") or len(active_bets or []) > 0) else 0
    rk_box = 1 if (st.get("rookie_box") or len(st.get("startup_storage", [])) > 0 or len(st.get("startup_showroom", [])) > 0) else 0
    rk_spin = 1 if (st.get("rookie_spin") or user.get("last_spin") == today_str) else 0
    rk_done_count = rk_bet + rk_box + rk_spin

    demand = get_daily_port_demand()
    storage_enriched = []
    for it in st.get("startup_storage", []):
        it_copy = dict(it)
        it_copy["is_in_demand"] = (it_copy.get("cat") == demand["key"])
        it_copy["expected_restore"] = int(round(it_copy.get("value", 1000) * 2.0, -1))
        storage_enriched.append(it_copy)

    vip_until_ts = int(st.get("vip_until_ts") or 0)
    now_ts = int(now_msk().timestamp())
    vip_days_left = max(0, math.ceil((vip_until_ts - now_ts) / 86400)) if vip_until_ts > now_ts else (999 if int(user.get("is_vip") or 0) == 1 else 0)

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "is_vip": 1 if vip_act else 0,
        "vip_days_left": vip_days_left,
        "forbes_capital": calculate_forbes_net_worth(user, st),
        "rank": rank_name,
        "daily_bonus_amt": daily_bonus_amt,
        "can_claim_bonus": can_claim_bonus,
        "streak_day": streak_day,
        "balance": round(user["balance"], 1),
        "wins": user["wins"],
        "losses": user["losses"],
        "profit": round(user["profit"], 1),
        "streak": int(user.get("streak") or 0),
        "favorite_club": user.get("favorite_club", ""),
        "is_incognito": int(user.get("is_incognito") or 0),
        "referrals_count": int(user.get("referrals_count") or 0),
        "pvp_wins": int(user.get("pvp_wins") or 0),
        "last_pvp": LAST_PVP_MATCH.get(user["user_id"]),
        "achievements_unlocked": achievements_unlocked,
        "equipped_cards": buffs["squad_ids"],
        "owned_cards": buffs["owned_ids"],
        "reserve_cards": buffs["reserve_ids"],
        "captain_role": buffs["captain"],
        "chemistry": buffs["chemistry"],
        "stadium_level": st_lvl,
        "stadium_info": STADIUM_LEVELS.get(st_lvl, STADIUM_LEVELS[1]),
        "can_claim_stadium": user.get("last_stadium_claim") != today_str,
        "stadium_prefs": {
            "ticket": st.get("ticket_mode", "optimal"),
            "sponsor": sp_id,
            "deposit_paid": st.get("sponsor_paid_date") == today_str or vip_act,
            "quest_done": quest_ok
        },
        "startup": {
            "storage": storage_enriched,
            "max_storage": 12 if vip_act else 8,
            "showroom": st.get("startup_showroom", []),
            "max_showroom": 4 if vip_act else 3,
            "profit": st.get("startup_profit", 0),
            "showroom_daily_fc": buffs["showroom_daily_fc"],
            "showroom_odd_boost": buffs["showroom_odd_boost"],
            "restore_chance_pct": 84 if vip_act else 72
        },
        "rookie_quest": {
            "bet": rk_bet,
            "box": rk_box,
            "spin": rk_spin,
            "done_count": rk_done_count,
            "claimed": int(st.get("rookie_claimed") or 0)
        },
        "lab_level": lab_lvl,
        "lab_info": LAB_LEVELS.get(lab_lvl, LAB_LEVELS[1]),
        "next_lab": LAB_LEVELS.get(lab_lvl + 1) if lab_lvl < 5 else None,
        "can_spin_roulette": user.get("last_spin") != today_str,
        "active_booster": user.get("active_booster", ""),
        "active_booster_name": BOOSTER_NAMES.get(user.get("active_booster", ""), ""),
        "fut_buffs": {k: v for k, v in buffs.items() if k != "full_state"}
    }

async def build_user_state_payload(uid: int) -> dict:
    now_ts = int(now_msk().timestamp())
    line_cache = await get_precomputed_webapp_line()
    user = await db_manager.get_user(uid)
    active_bets_raw = await db_manager.get_user_bets(uid, active_only=True)
    archive_bets_raw = await db_manager.get_user_bets(uid, active_only=False)
    open_duels = await db_manager.get_open_pvp_duels(uid)

    if now_ts - SHARED_DB_CACHE["bm_ts"] > 15 or not SHARED_DB_CACHE["bm_lot"]:
        SHARED_DB_CACHE["bm_lot"] = await db_manager.get_or_rotate_black_market()
        SHARED_DB_CACHE["bm_ts"] = now_ts
    lot = SHARED_DB_CACHE["bm_lot"]
    lot_card = FUT_CARDS.get(lot["lot_id"], {"name": "Секретный лот", "desc": "", "role": "FW", "val": 24, "ovr": 99})

    if now_ts - SHARED_DB_CACHE["leaderboard_ts"] > 15 or not SHARED_DB_CACHE["leaderboard_raw"]:
        SHARED_DB_CACHE["leaderboard_raw"] = await db_manager.get_leaderboard()
        SHARED_DB_CACHE["leaderboard_ts"] = now_ts

    leaderboard = []
    for idx, u in enumerate(SHARED_DB_CACHE["leaderboard_raw"], 1):
        incog = int(u.get("is_incognito") or 0) == 1
        u_vip = is_user_vip_active(u)
        leaderboard.append({
            "place": idx,
            "user_id": u["user_id"],
            "name": f"🕶 Скрытый #{str(u['user_id'])[-4:]}" if incog else (f"👑 {u['username']}" if u_vip else u["username"]),
            "club": "" if incog else (u.get("favorite_club") or ""),
            "balance": round(u["balance"], 1),
            "forbes": calculate_forbes_net_worth(u),
            "wins": u["wins"],
            "is_me": u["user_id"] == uid
        })

    if now_ts - SHARED_DB_CACHE["se_ts"] > 60 or not SHARED_DB_CACHE["se_matches"]:
        rk, sm_list = await db_manager.get_or_create_weekly_superexpress(line_cache["filtered_db"])
        for sm in sm_list:
            if " — " in sm.get("teams", ""):
                pa, pb = sm["teams"].split(" — ", 1)
                sm["teams"] = f"{translate_team_ru(pa)} — {translate_team_ru(pb)}"
        SHARED_DB_CACHE["se_round_key"] = rk
        SHARED_DB_CACHE["se_matches"] = sm_list
        SHARED_DB_CACHE["se_ts"] = now_ts

    se_round_key = SHARED_DB_CACHE["se_round_key"]
    se_matches = SHARED_DB_CACHE["se_matches"]
    se_entry = await db_manager.get_superexpress_entry(uid, se_round_key)
    se_user_picks = json.loads(se_entry["picks_json"]) if se_entry else None

    fast_u = build_fast_user_dict(user, active_bets_raw)

    global BOT_USERNAME
    if not BOT_USERNAME:
        try:
            me = await bot.get_me()
            BOT_USERNAME = me.username
        except Exception:
            pass

    return {
        "ok": True,
        "bot_username": BOT_USERNAME,
        "user": fast_u,
        "vip_plans": VIP_PLANS_FC,
        "vip_benefits": VIP_BENEFITS_LIST,
        "daily_demand": get_daily_port_demand(),
        "live_ticker": LIVE_TICKER_FEED[:8],
        "streak_calendar": STREAK_CALENDAR,
        "containers_catalog": CONTAINERS_CATALOG,
        "p2p_market": P2P_CONTAINER_MARKET[:30],
        "fut_catalog": FUT_CARDS,
        "stadium_sponsors": STADIUM_SPONSORS,
        "popular_clubs": POPULAR_CLUBS,
        "all_achievements": ACHIEVEMENTS_CONFIG,
        "stadiums_catalog": STADIUM_LEVELS,
        "secret_bet_offer": line_cache["secret_offer"] if fast_u["lab_level"] >= 2 else None,
        "daily_express": line_cache["daily_express"],
        "superexpress": {
            "round_key": se_round_key,
            "matches": se_matches,
            "entry": {
                "status": se_entry["status"],
                "guessed": se_entry["guessed"],
                "payout": se_entry["payout"],
                "picks": se_user_picks
            } if se_entry else None
        },
        "pvp_duels": [
            {
                "duel_id": d["duel_id"],
                "creator_id": d["creator_id"],
                "creator_name": d["creator_name"],
                "target_id": int(d.get("target_id") or 0),
                "stake": d["stake"],
                "is_mine": d["creator_id"] == uid,
                "is_for_me": int(d.get("target_id") or 0) == uid
            }
            for d in open_duels
        ],
        "black_market": {
            "card": lot_card,
            "highest_bid": lot["highest_bid"],
            "leader_id": int(lot["leader_id"]),
            "leader_name": lot["leader_name"],
            "min_next_bid": int(lot["highest_bid"]) + 500 if int(lot["leader_id"]) != 0 else int(lot["highest_bid"])
        },
        "active_bets": [
            {
                "bet_id": b["bet_id"],
                "match_title": b["match_title"],
                "pick": b["pick"],
                "amount": b["amount"],
                "odds": b["odds"],
                "potential_win": round(b["amount"] * b["odds"], 1),
                "bet_type": b.get("bet_type", "single"),
                "legs_detailed": format_archive_bet_legs(b)
            }
            for b in active_bets_raw
        ],
        "archive_bets": [
            {
                "bet_id": b["bet_id"],
                "match_title": b["match_title"],
                "pick": b["pick"],
                "amount": b["amount"],
                "odds": b["odds"],
                "status": b["status"],
                "score_result": b.get("score_result", ""),
                "payout": round(b["amount"] * b["odds"], 1) if b["status"] == "win" else (b["amount"] if b["status"] == "push" else 0),
                "legs_detailed": format_archive_bet_legs(b)
            }
            for b in archive_bets_raw
        ],
        "leaderboard": leaderboard,
        "leagues": line_cache["leagues_nav"],
        "matches": line_cache["matches"]
    }

async def api_get_state(request):
    uid_str = request.match_info.get("user_id", "0")
    if not uid_str.isdigit():
        return web.json_response({"ok": False, "error": "Некорректный ID"}, status=400, headers=CORS_HEADERS)
    payload = await build_user_state_payload(int(uid_str))
    return web.json_response(payload, headers=CORS_HEADERS)

async def _fast_delta_response(uid: int, extra: dict = None, include_bets: bool = False, include_pvp: bool = False):
    u = await db_manager.get_user(uid)
    act_raw = await db_manager.get_user_bets(uid, active_only=True) if include_bets else []
    fast_u = build_fast_user_dict(u, act_raw)
    resp = {
        "ok": True,
        "user": fast_u,
        "daily_demand": get_daily_port_demand(),
        "live_ticker": LIVE_TICKER_FEED[:8],
        "p2p_market": P2P_CONTAINER_MARKET[:30],
        **(extra or {})
    }
    if include_bets:
        arch_raw = await db_manager.get_user_bets(uid, active_only=False)
        resp["active_bets"] = [
            {
                "bet_id": b["bet_id"], "match_title": b["match_title"], "pick": b["pick"],
                "amount": b["amount"], "odds": b["odds"], "potential_win": round(b["amount"] * b["odds"], 1),
                "bet_type": b.get("bet_type", "single"), "legs_detailed": format_archive_bet_legs(b)
            }
            for b in act_raw
        ]
        resp["archive_bets"] = [
            {
                "bet_id": b["bet_id"], "match_title": b["match_title"], "pick": b["pick"],
                "amount": b["amount"], "odds": b["odds"], "status": b["status"],
                "score_result": b.get("score_result", ""),
                "payout": round(b["amount"] * b["odds"], 1) if b["status"] == "win" else (b["amount"] if b["status"] == "push" else 0),
                "legs_detailed": format_archive_bet_legs(b)
            }
            for b in arch_raw
        ]
    if include_pvp:
        open_duels = await db_manager.get_open_pvp_duels(uid)
        resp["pvp_duels"] = [
            {
                "duel_id": d["duel_id"], "creator_id": d["creator_id"], "creator_name": d["creator_name"],
                "target_id": int(d.get("target_id") or 0), "stake": d["stake"],
                "is_mine": d["creator_id"] == uid, "is_for_me": int(d.get("target_id") or 0) == uid
            }
            for d in open_duels
        ]
    return web.json_response(resp, headers=CORS_HEADERS)

async def api_handle_action(request):
    global _P2P_LOT_SEQ
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400, headers=CORS_HEADERS)

    uid = int(body.get("user_id") or 0)
    action = str(body.get("action") or "")
    if not uid:
        return web.json_response({"ok": False, "error": "Не указан ID игрока"}, status=400, headers=CORS_HEADERS)

    # ОБЗОР ЧУЖОГО ПРОФИЛЯ ИГРОКА (БЕЗ БЛОКИРОВКИ ОЧЕРЕДИ)
    if action == "inspect_player":
        query_val = str(body.get("query") or body.get("target_id") or "").strip()
        if not query_val:
            return web.json_response({"ok": False, "error": "Укажи Никнейм или ID игрока для поиска!"}, headers=CORS_HEADERS)
        target_u = await db_manager.find_user_by_query(query_val)
        if not target_u:
            return web.json_response({"ok": False, "error": f"Игрок «{query_val}» не найден в базе!"}, headers=CORS_HEADERS)
        pub_prof = build_public_player_profile(target_u)
        return web.json_response({"ok": True, "profile": pub_prof}, headers=CORS_HEADERS)

    # СТРОГАЯ АНТИ-ДЮП БЛОКИРОВКА НА ВСЕ ДЕЙСТВИЯ С БАЛАНСОМ И ПРЕДМЕТАМИ
    async with USER_ACTION_LOCKS[uid]:
        user = await db_manager.get_user(uid)
        st = parse_user_fut_state(user)
        vip_act = is_user_vip_active(user, st)
        today_str = now_msk().strftime("%Y-%m-%d")

        # 1. ПОКУПКА VIP-СТАТУСА ЗА FC (ОТ 20 000 FC)
        if action == "buy_vip_fc":
            plan_id = str(body.get("plan_id") or "vip_3d")
            plan = VIP_PLANS_FC.get(plan_id)
            if not plan:
                return web.json_response({"ok": False, "error": "Тариф VIP не найден"}, headers=CORS_HEADERS)
            cost = plan["price"]
            if user["balance"] < cost:
                return web.json_response({"ok": False, "error": f"Недостаточно средств! Для «{plan['title']}» нужно {cost} FC."}, headers=CORS_HEADERS)

            now_ts = int(now_msk().timestamp())
            base_ts = max(now_ts, int(st.get("vip_until_ts") or 0))
            st["vip_until_ts"] = base_ts + (plan["days"] * 86400)
            new_bal = round(user["balance"] - cost, 1)

            await db_manager.exec(
                "UPDATE users SET balance = $1, is_vip = 1, fut_cards = $2 WHERE user_id = $3",
                new_bal, dump_user_fut_state(st, True), uid
            )
            SHARED_DB_CACHE["leaderboard_ts"] = 0
            asyncio.create_task(db_manager.unlock_achievement(uid, "vip_club_member"))
            push_live_ticker(f"👑 Каппер {user['username']} вступил в VIP-Клуб ({plan['title']})!")
            return await _fast_delta_response(uid, {
                "message": f"👑 Поздравляем! Активирован «{plan['title']}» со всеми привилегиями!",
                "coin_delta": -cost
            })

        # 2. ЕЖЕДНЕВНЫЙ КАЛЕНДАРЬ БОНУСОВ (ОТ 200 ДО 3 500 FC)
        elif action == "claim_bonus":
            streak_day, can_claim = compute_login_streak_info(st)
            if not can_claim or user.get("last_bonus") == today_str:
                return web.json_response({"ok": False, "error": "Бонус сегодня уже получен! Заходи завтра для продолжения серии."}, headers=CORS_HEADERS)

            cal_item = STREAK_CALENDAR[streak_day - 1]
            _, rank_bonus = get_user_rank_info(user["balance"], 1 if vip_act else 0)
            total_reward = cal_item["coins"] + int(rank_bonus * 0.5)

            st["login_streak"] = streak_day
            st["last_streak_date"] = today_str
            new_booster = cal_item["booster"] or user.get("active_booster") or ""

            await db_manager.exec(
                "UPDATE users SET balance = balance + $1, last_bonus = $2, active_booster = $3, fut_cards = $4 WHERE user_id = $5",
                float(total_reward), today_str, new_booster, dump_user_fut_state(st, vip_act), uid
            )
            b_note = " + Бустер!" if cal_item["booster"] else ""
            return await _fast_delta_response(uid, {
                "message": f"🔥 День {streak_day}/7! Получено +{total_reward} FC{b_note}",
                "coin_delta": total_reward
            })

        # 3. СТАРТОВЫЙ КВЕСТ НОВИЧКА (3 ШАГА ➔ +1 000 FC + КАРТОЧКА FUT)
        elif action == "claim_rookie_quest":
            if st.get("rookie_claimed") == 1:
                return web.json_response({"ok": False, "error": "Награда стартового квеста уже получена!"}, headers=CORS_HEADERS)
            act_bets = await db_manager.get_user_bets(uid, active_only=True)
            rk_bet = 1 if (st.get("rookie_bet") or len(act_bets) > 0) else 0
            rk_box = 1 if (st.get("rookie_box") or len(st.get("startup_storage", [])) > 0 or len(st.get("startup_showroom", [])) > 0) else 0
            rk_spin = 1 if (st.get("rookie_spin") or user.get("last_spin") == today_str) else 0

            if (rk_bet + rk_box + rk_spin) < 3:
                return web.json_response({"ok": False, "error": "Выполни все 3 простых шага (1 ставка, 1 контейнер и 1 спин рулетки)!"}, headers=CORS_HEADERS)

            st["rookie_claimed"] = 1
            st["rookie_bet"] = 1
            st["rookie_box"] = 1
            st["rookie_spin"] = 1

            tier2_pool = [k for k, v in FUT_CARDS.items() if v["tier"] == 2]
            bonus_card_id = random.choice(tier2_pool)
            bonus_card = FUT_CARDS[bonus_card_id]
            if bonus_card_id not in st["owned"]:
                st["owned"].append(bonus_card_id)
                role = bonus_card["role"]
                if not st["squad"].get(role):
                    st["squad"][role] = bonus_card_id

            await db_manager.exec(
                "UPDATE users SET balance = balance + 1000, fut_cards = $1 WHERE user_id = $2",
                dump_user_fut_state(st, vip_act), uid
            )
            push_live_ticker(f"🎁 Игрок {user['username']} выполнил Квест Новичка и получил +1 000 FC + карту {bonus_card['name']}!")
            return await _fast_delta_response(uid, {
                "message": f"🎉 Квест выполнен! Получено +1 000 FC и карточка «{bonus_card['name']}»!",
                "card": bonus_card,
                "coin_delta": 1000
            })

        # 4. КОНТЕЙНЕРЫ: ПОКУПКА И ВСКРЫТИЕ (12 КОНТЕЙНЕРОВ, СКИДКА 10% ДЛЯ VIP, СПРОС ДНЯ +15%)
        elif action == "startup_open_container":
            cid = str(body.get("container_id") or "c_1")
            box = CONTAINERS_CATALOG.get(cid)
            if not box:
                return web.json_response({"ok": False, "error": "Контейнер не найден"}, headers=CORS_HEADERS)
            max_stor = 12 if vip_act else 8
            if len(st["startup_storage"]) >= max_stor:
                return web.json_response({"ok": False, "error": f"Склад переполнен (макс. {max_stor} находок)! Продай или выстави предмет на биржу."}, headers=CORS_HEADERS)

            raw_price = box["price"]
            price = int(round(raw_price * 0.90)) if vip_act else raw_price
            if user["balance"] < price:
                return web.json_response({"ok": False, "error": f"Недостаточно средств! Нужно {price} FC."}, headers=CORS_HEADERS)

            pool = box["items"]
            weights = [26, 22, 18, 14, 10, 6, 4][:len(pool)]
            chosen_tpl = random.choices(pool, weights=weights, k=1)[0]

            demand = get_daily_port_demand()
            is_hot = (chosen_tpl.get("cat") == demand["key"])
            demand_mult = 1.15 if is_hot else 1.0

            condition = random.randint(44, 88)
            cond_mult = round(0.65 + (condition / 100.0) * 0.65, 2)
            market_val = int(round(chosen_tpl["base"] * cond_mult * demand_mult, -1))

            uid_item = f"lot_{int(now_msk().timestamp()*1000)}_{random.randint(100,999)}"
            found_item = {
                "uid": uid_item,
                "tpl_id": chosen_tpl["id"],
                "name": chosen_tpl["name"],
                "ico": chosen_tpl["ico"],
                "cat": chosen_tpl.get("cat", "tech"),
                "is_in_demand": is_hot,
                "rarity": chosen_tpl["rarity"],
                "condition": condition,
                "restored_count": 0,
                "value": market_val,
                "expected_restore": int(round(market_val * 2.0, -1)),
                "restore_cost": max(150, int(round(market_val * 0.22, -1))),
                "show_inc": chosen_tpl["show_inc"],
                "show_odd": chosen_tpl["show_odd"],
                "container_price": price
            }
            st["startup_storage"].insert(0, found_item)
            st["rookie_box"] = 1
            new_bal = round(user["balance"] - price, 1)

            await db_manager.exec(
                "UPDATE users SET balance = $1, fut_cards = $2 WHERE user_id = $3",
                new_bal, dump_user_fut_state(st, vip_act), uid
            )
            asyncio.create_task(db_manager.unlock_achievement(uid, "container_hunter"))
            if cid == "c_12":
                asyncio.create_task(db_manager.unlock_achievement(uid, "ark_billionaire"))

            if market_val >= 8000 or chosen_tpl["rarity"] >= 3:
                push_live_ticker(f"📦 {user['username']} вскрыл «{box['name']}» и нашёл {found_item['name']} ({market_val} FC)!")

            hot_tag = " 🔥[Спрос дня +15%!]" if is_hot else ""
            return await _fast_delta_response(uid, {
                "message": f"📦 Вскрыт «{box['name']}»! Найдено: {found_item['name']} (Оценка: {found_item['value']} FC){hot_tag}",
                "found_item": found_item,
                "coin_delta": -price
            })

        # 5. КОНТЕЙНЕРЫ: РЕСТАВРАЦИЯ (ШАНС 84% ДЛЯ VIP И 72% ОБЫЧНЫЙ)
        elif action == "startup_restore_item":
            item_uid = str(body.get("item_uid") or "")
            idx = next((i for i, x in enumerate(st["startup_storage"]) if x["uid"] == item_uid), -1)
            if idx == -1:
                return web.json_response({"ok": False, "error": "Предмет не найден на складе"}, headers=CORS_HEADERS)

            it = st["startup_storage"][idx]
            if it.get("restored_count", 0) >= 2 or it["condition"] >= 100:
                return web.json_response({"ok": False, "error": "Этот предмет уже отреставрирован до максимума!"}, headers=CORS_HEADERS)

            r_cost = int(it.get("restore_cost") or 200)
            if user["balance"] < r_cost:
                return web.json_response({"ok": False, "error": f"Для реставрации нужно {r_cost} FC!"}, headers=CORS_HEADERS)

            it["restored_count"] = int(it.get("restored_count") or 0) + 1
            win_chance = 0.84 if vip_act else 0.72
            success = random.random() < win_chance
            if success:
                boost_mult = random.uniform(1.70, 2.38)
                it["value"] = int(round(it["value"] * boost_mult, -1))
                it["condition"] = min(100, it["condition"] + random.randint(25, 45))
                it["restore_cost"] = int(round(it["value"] * 0.25, -1))
                msg = f"✨ Успешная реставрация! Ценность «{it['name']}» выросла до {it['value']} FC!"
                if it["value"] >= 20000:
                    push_live_ticker(f"🔧 {user['username']} отреставрировал «{it['name']}» до {it['value']} FC!")
            else:
                it["value"] = max(100, int(round(it["value"] * 0.76, -1)))
                it["condition"] = max(20, it["condition"] - 12)
                msg = f"⚠️ Вскрылся скрытый дефект при разборке! Оценка снизилась до {it['value']} FC."

            new_bal = round(user["balance"] - r_cost, 1)
            await db_manager.exec(
                "UPDATE users SET balance = $1, fut_cards = $2 WHERE user_id = $3",
                new_bal, dump_user_fut_state(st, vip_act), uid
            )
            return await _fast_delta_response(uid, {"message": msg, "coin_delta": -r_cost})

        # 6. КОНТЕЙНЕРЫ: ЖИВОЙ ТОРГ СО СКУПЩИКОМ (3 ТАКТИКИ)
        elif action == "startup_sell_npc":
            item_uid = str(body.get("item_uid") or "")
            tactic = str(body.get("tactic") or "base")
            idx = next((i for i, x in enumerate(st["startup_storage"]) if x["uid"] == item_uid), -1)
            if idx == -1:
                return web.json_response({"ok": False, "error": "Предмет не найден"}, headers=CORS_HEADERS)

            it = st["startup_storage"].pop(idx)
            base_val = int(it["value"])

            if tactic == "base":
                final_price = base_val
                msg = f"🤝 Сделка закрыта по оценке! Продано «{it['name']}» за +{final_price} FC."
            elif tactic == "push25":
                if random.random() < 0.65:
                    final_price = int(round(base_val * 1.25, -1))
                    msg = f"🔥 Скупщик согласился на наценку +25%! Продано за +{final_price} FC!"
                else:
                    final_price = int(round(base_val * 0.90, -1))
                    msg = f"😤 Скупщик заметил царапины и сбил цену на 10%. Продано за +{final_price} FC."
            else:
                if random.random() < 0.38:
                    final_price = int(round(base_val * 1.65, -1))
                    msg = f"💎 ДЖЕКПОТ ТОРГА (+65%)! Коллекционер забрал «{it['name']}» за +{final_price} FC!"
                    push_live_ticker(f"💎 {user['username']} выторговал +65% и продал «{it['name']}» за {final_price} FC!")
                else:
                    final_price = int(round(base_val * 0.78, -1))
                    msg = f"📉 Блеф не прошел! Пришлось отдать перекупщикам за +{final_price} FC."

            net_diff = final_price - int(it.get("container_price") or base_val)
            st["startup_profit"] = int(st.get("startup_profit") or 0) + net_diff
            new_bal = round(user["balance"] + final_price, 1)

            await db_manager.exec(
                "UPDATE users SET balance = $1, fut_cards = $2 WHERE user_id = $3",
                new_bal, dump_user_fut_state(st, vip_act), uid
            )
            return await _fast_delta_response(uid, {"message": msg, "coin_delta": final_price})

        # 7. КОНТЕЙНЕРЫ: ЛИЧНЫЙ ШОУРУМ (ДО 4 ВИТРИН ДЛЯ VIP)
        elif action == "startup_to_showroom":
            item_uid = str(body.get("item_uid") or "")
            idx = next((i for i, x in enumerate(st["startup_storage"]) if x["uid"] == item_uid), -1)
            if idx == -1:
                return web.json_response({"ok": False, "error": "Предмет не найден"}, headers=CORS_HEADERS)
            max_show = 4 if vip_act else 3
            if len(st["startup_showroom"]) >= max_show:
                return web.json_response({"ok": False, "error": f"В Шоуруме заняты все витрины ({max_show} шт.)! Сними один экспонат."}, headers=CORS_HEADERS)

            it = st["startup_storage"].pop(idx)
            st["startup_showroom"].append(it)
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            return await _fast_delta_response(uid, {
                "message": f"🏛 «{it['name']}» выставлен в Шоурум (+{it['show_inc']} FC/день и +{it['show_odd']} к кэфам)!"
            })

        elif action == "startup_from_showroom":
            item_uid = str(body.get("item_uid") or "")
            idx = next((i for i, x in enumerate(st["startup_showroom"]) if x["uid"] == item_uid), -1)
            if idx == -1:
                return web.json_response({"ok": False, "error": "Экспонат не найден"}, headers=CORS_HEADERS)
            max_stor = 12 if vip_act else 8
            if len(st["startup_storage"]) >= max_stor:
                return web.json_response({"ok": False, "error": "На складе нет свободного места!"}, headers=CORS_HEADERS)

            it = st["startup_showroom"].pop(idx)
            st["startup_storage"].append(it)
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            return await _fast_delta_response(uid, {"message": f"📦 «{it['name']}» возвращен на склад."})

        # 8. P2P-БИРЖА МЕЖДУ ИГРОКАМИ (С СОХРАНЕНИЕМ В POSTGRESQL)
        elif action == "p2p_list_item":
            item_uid = str(body.get("item_uid") or "")
            ask_price = int(body.get("price") or 0)
            idx = next((i for i, x in enumerate(st["startup_storage"]) if x["uid"] == item_uid), -1)
            if idx == -1:
                return web.json_response({"ok": False, "error": "Предмет не найден на складе"}, headers=CORS_HEADERS)
            if ask_price < 300 or ask_price > 1500000:
                return web.json_response({"ok": False, "error": "Цена на P2P-бирже должна быть от 300 до 1 500 000 FC!"}, headers=CORS_HEADERS)

            it = st["startup_storage"].pop(idx)
            _P2P_LOT_SEQ += 1
            lot_obj = {
                "lot_id": _P2P_LOT_SEQ,
                "seller_id": uid,
                "seller_name": user["username"],
                "seller_vip": vip_act,
                "item": it,
                "price": ask_price
            }
            P2P_CONTAINER_MARKET.insert(0, lot_obj)
            await db_insert_p2p_lot(lot_obj)
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            asyncio.create_task(db_manager.unlock_achievement(uid, "p2p_merchant"))
            push_live_ticker(f"🌐 {user['username']} выставил на P2P-Биржу «{it['name']}» за {ask_price} FC!")
            return await _fast_delta_response(uid, {
                "message": f"🌐 Лот #{lot_obj['lot_id']} «{it['name']}» выставлен на P2P-Биржу за {ask_price} FC!"
            })

        elif action == "p2p_cancel_lot":
            lot_id = int(body.get("lot_id") or 0)
            l_idx = next((i for i, x in enumerate(P2P_CONTAINER_MARKET) if x["lot_id"] == lot_id and x["seller_id"] == uid), -1)
            if l_idx == -1:
                return web.json_response({"ok": False, "error": "Лот уже куплен или не найден"}, headers=CORS_HEADERS)
            max_stor = 12 if vip_act else 8
            if len(st["startup_storage"]) >= max_stor:
                return web.json_response({"ok": False, "error": "Склад переполнен! Освободи место."}, headers=CORS_HEADERS)

            lot_obj = P2P_CONTAINER_MARKET.pop(l_idx)
            await db_delete_p2p_lot(lot_id)
            st["startup_storage"].append(lot_obj["item"])
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            return await _fast_delta_response(uid, {"message": "✅ Лот снят с P2P-Биржи и возвращен на склад."})

        elif action == "p2p_buy_lot":
            lot_id = int(body.get("lot_id") or 0)
            l_idx = next((i for i, x in enumerate(P2P_CONTAINER_MARKET) if x["lot_id"] == lot_id), -1)
            if l_idx == -1:
                return web.json_response({"ok": False, "error": "Этот лот уже выкуплен другим игроком!"}, headers=CORS_HEADERS)
            lot_obj = P2P_CONTAINER_MARKET[l_idx]
            if lot_obj["seller_id"] == uid:
                return web.json_response({"ok": False, "error": "Это твой собственный лот!"}, headers=CORS_HEADERS)
            max_stor = 12 if vip_act else 8
            if len(st["startup_storage"]) >= max_stor:
                return web.json_response({"ok": False, "error": f"Твой склад переполнен (макс. {max_stor} предметов)!"}, headers=CORS_HEADERS)

            price = int(lot_obj["price"])
            if user["balance"] < price:
                return web.json_response({"ok": False, "error": f"Недостаточно средств ({price} FC)!"}, headers=CORS_HEADERS)

            P2P_CONTAINER_MARKET.pop(l_idx)
            await db_delete_p2p_lot(lot_id)
            bought_item = lot_obj["item"]
            bought_item["container_price"] = price
            st["startup_storage"].insert(0, bought_item)

            tax_mult = 1.0 if lot_obj.get("seller_vip") else 0.95
            seller_payout = int(round(price * tax_mult))
            await db_manager.exec(
                "UPDATE users SET balance = balance - $1, fut_cards = $2 WHERE user_id = $3",
                float(price), dump_user_fut_state(st, vip_act), uid
            )
            await db_manager.exec(
                "UPDATE users SET balance = balance + $1, profit = profit + $1 WHERE user_id = $2",
                float(seller_payout), lot_obj["seller_id"]
            )
            asyncio.create_task(db_manager.unlock_achievement(uid, "p2p_merchant"))
            push_live_ticker(f"🛍 {user['username']} купил «{bought_item['name']}» у игрока {lot_obj['seller_name']} за {price} FC!")

            try:
                tax_note = "0% (VIP-привилегия)" if lot_obj.get("seller_vip") else "5%"
                await bot.send_message(
                    lot_obj["seller_id"],
                    f"🌐 <b>ТВОЙ ЛОТ НА P2P-БИРЖЕ КУПЛЕН!</b>\n\n"
                    f"<blockquote>📦 Предмет: <b>{bought_item['name']}</b>\n"
                    f"👤 Покупатель: <b>{user['username']}</b>\n"
                    f"💰 Зачислено (комиссия {tax_note}): <b><code>+{seller_payout} FC</code></b></blockquote>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            return await _fast_delta_response(uid, {
                "message": f"🛍 Куплено «{bought_item['name']}» у игрока {lot_obj['seller_name']}!",
                "coin_delta": -price
            })

        # 9. FUT: СМЕНА СОСТАВА, КАПИТАН И СПК
        elif action == "equip_fut_card":
            card_id = str(body.get("card_id") or "")
            if card_id not in FUT_CARDS or card_id not in st["owned"]:
                return web.json_response({"ok": False, "error": "Карточка не найдена в коллекции"}, headers=CORS_HEADERS)
            c = FUT_CARDS[card_id]
            st["squad"][c["role"]] = card_id
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            return await _fast_delta_response(uid, {"message": f"👕 {c['name']} вышел в стартовый состав ({c['role']})!"})

        elif action == "set_fut_captain":
            role = str(body.get("role") or "FW")
            if role not in FUT_ROLES:
                return web.json_response({"ok": False, "error": "Неверная позиция"}, headers=CORS_HEADERS)
            st["captain"] = role
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            return await _fast_delta_response(uid, {"message": f"© Капитанская повязка передана позиции {role} (+25% к баффу)!"})

        elif action == "craft_fut_pack":
            active_set = set(v for v in st["squad"].values() if v)
            reserves = [cid for cid in st["owned"] if cid not in active_set]
            if len(reserves) < 3:
                return web.json_response({"ok": False, "error": f"Для СПК нужно 3 резервные карты (сейчас: {len(reserves)})."}, headers=CORS_HEADERS)

            reserves.sort(key=lambda x: FUT_CARDS.get(x, {}).get("ovr", 80))
            for sc_id in reserves[:3]:
                if sc_id in st["owned"]:
                    st["owned"].remove(sc_id)

            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            pool_t2 = [k for k, v in FUT_CARDS.items() if v["tier"] == 2]
            pool_t3 = [k for k, v in FUT_CARDS.items() if v["tier"] == 3]
            won_card_id = random.choices(pool_t2 + pool_t3, weights=[14]*len(pool_t2) + [5]*len(pool_t3), k=1)[0]

            res = await open_fut_pack_v2(uid, 0, won_card_id)
            asyncio.create_task(db_manager.unlock_achievement(uid, "sbc_master"))
            return await _fast_delta_response(uid, {
                "card": res["card"],
                "status_note": f"🔄 СПК выполнен! Обменено 3 резервные карты. {res['status_note']}"
            })

        # 10. АРЕНА И УРОВНЕВЫЕ КОНТРАКТЫ СПОНСОРОВ (ДЛЯ VIP — БЕЗ ЗАЛОГА)
        elif action == "set_stadium_prefs":
            ticket = str(body.get("ticket") or st.get("ticket_mode", "optimal"))
            sponsor_id = str(body.get("sponsor") or st.get("sponsor_id", "sp_1"))
            st_lvl = int(user.get("stadium_level") or 1)

            sp_obj = next((s for s in STADIUM_SPONSORS if s["id"] == sponsor_id), STADIUM_SPONSORS[0])
            if st_lvl < sp_obj["min_lvl"]:
                return web.json_response({
                    "ok": False,
                    "error": f"🔒 Контракт «{sp_obj['name']}» требует Стадион {sp_obj['min_lvl']}-го уровня!"
                }, headers=CORS_HEADERS)

            coin_delta = 0
            if not vip_act and sponsor_id != st.get("sponsor_id") and sp_obj["deposit"] > 0 and st.get("sponsor_paid_date") != today_str:
                dep = sp_obj["deposit"]
                if user["balance"] < dep:
                    return web.json_response({"ok": False, "error": f"Для подписания контракта нужен страховой залог {dep} FC (или VIP-статус)!"}, headers=CORS_HEADERS)
                st["sponsor_paid_date"] = today_str
                coin_delta = -dep
                await db_manager.exec("UPDATE users SET balance = balance - $1 WHERE user_id = $2", float(dep), uid)

            st["ticket_mode"] = ticket
            st["sponsor_id"] = sponsor_id
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            if ticket == "vip":
                asyncio.create_task(db_manager.unlock_achievement(uid, "matchday_vip"))

            dep_msg = f" (Внесен залог -{abs(coin_delta)} FC)" if coin_delta < 0 else (" (👑 VIP: без залога)" if vip_act and sp_obj["deposit"] > 0 else "")
            return await _fast_delta_response(uid, {
                "message": f"🏟 Контракт и тариф арены сохранены!{dep_msg}",
                "coin_delta": coin_delta
            })

        elif action == "claim_stadium":
            if user.get("last_stadium_claim") == today_str:
                return web.json_response({"ok": False, "error": "Касса арены сегодня уже собрана! Заходи завтра."}, headers=CORS_HEADERS)

            lvl = int(user.get("stadium_level") or 1)
            st_cfg = STADIUM_LEVELS.get(lvl, STADIUM_LEVELS[1])
            base_inc = st_cfg["income"]
            t_mode = st.get("ticket_mode", "optimal")
            sp_id = st.get("sponsor_id", "sp_1")
            sp_obj = next((s for s in STADIUM_SPONSORS if s["id"] == sp_id), STADIUM_SPONSORS[0])

            active_bets = await db_manager.get_user_bets(uid, active_only=True)
            has_activity = len(active_bets) > 0 or int(user.get("streak") or 0) > 0

            if t_mode == "social":
                mult, t_note = 1.0, "Социальный (100%)"
            elif t_mode == "optimal":
                mult = 1.30 if has_activity else 1.0
                t_note = "Оптимальный (+30%)" if has_activity else "Оптимальный (база)"
            else:
                mult = 1.65 if has_activity else 0.80
                t_note = "VIP-Аншлаг (+65%!)" if has_activity else "VIP (80% без ставок)"

            quest_ok = check_sponsor_quest_done(sp_id, user, st, active_bets)
            dep_returned = sp_obj["deposit"] if (not vip_act and st.get("sponsor_paid_date") == today_str and quest_ok) else 0
            sp_bonus = (sp_obj["bonus"] + dep_returned) if quest_ok else 0

            showroom_inc = sum(int(x.get("show_inc") or 0) for x in st.get("startup_showroom", []))
            total_inc = int(round(base_inc * mult)) + sp_bonus + showroom_inc

            await db_manager.exec(
                "UPDATE users SET balance = balance + $1, last_stadium_claim = $2 WHERE user_id = $3",
                float(total_inc), today_str, uid
            )
            sp_txt = f" + Спонсор +{sp_bonus} FC" if quest_ok else " (Условие спонсора не выполнено: 0 FC)"
            sh_txt = f" + Шоурум +{showroom_inc} FC" if showroom_inc > 0 else ""
            return await _fast_delta_response(uid, {
                "message": f"🏟 Касса «{st_cfg['name']}»: +{total_inc} FC ({t_note}{sp_txt}{sh_txt})!",
                "coin_delta": total_inc
            })

        elif action == "upgrade_building":
            b_type = str(body.get("b_type") or "stadium")
            res = await db_manager.upgrade_empire_building(uid, b_type)
            if not res["ok"]:
                return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)
            if b_type == "stadium":
                if res["new_lvl"] >= 5:
                    asyncio.create_task(db_manager.unlock_achievement(uid, "stadium_lvl_5"))
                if res["new_lvl"] >= 10:
                    asyncio.create_task(db_manager.unlock_achievement(uid, "stadium_lvl_10"))
            return await _fast_delta_response(uid, {"message": f"✅ Построено: {res['name']} (Ур. {res['new_lvl']})!"})

        elif action == "buy_pack":
            p_type = str(body.get("pack_type") or "basic")
            tier1_keys = [k for k, v in FUT_CARDS.items() if v["tier"] == 1]
            tier2_keys = [k for k, v in FUT_CARDS.items() if v["tier"] == 2]
            tier3_keys = [k for k, v in FUT_CARDS.items() if v["tier"] == 3]

            if p_type == "basic":
                cost, pool, weights = 1500, tier1_keys + tier2_keys, [12]*len(tier1_keys) + [3]*len(tier2_keys)
            elif p_type == "gold":
                cost, pool, weights = 5000, tier1_keys + tier2_keys + tier3_keys, [4]*len(tier1_keys) + [14]*len(tier2_keys) + [3]*len(tier3_keys)
            else:
                cost, pool, weights = 15000, tier2_keys + tier3_keys, [6]*len(tier2_keys) + [16]*len(tier3_keys)

            card_id = random.choices(pool, weights=weights, k=1)[0]
            res = await open_fut_pack_v2(uid, cost, card_id)
            if not res["ok"]:
                return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)

            if all(res["st"]["squad"].get(r) for r in FUT_ROLES):
                asyncio.create_task(db_manager.unlock_achievement(uid, "fut_full_squad"))

            return await _fast_delta_response(uid, {
                "card": res["card"],
                "status_note": re.sub(r"<.*?>", "", res["status_note"]),
                "coin_delta": -cost
            })

        # 11. РУЛЕТКА (ПРЕЖНИЕ ПАРАМЕТРЫ + ТОЧНАЯ КАЛИБРОВКА СЕКТОРА)
        elif action == "spin_roulette":
            if user.get("last_spin") == today_str:
                return web.json_response({"ok": False, "error": "Ты уже крутил рулетку сегодня!"}, headers=CORS_HEADERS)

            sectors = [
                {"idx": 0, "name": "💰 +150 FC", "coins": 150, "booster": "", "respin": False, "weight": 28},
                {"idx": 1, "name": "💰 +300 FC", "coins": 300, "booster": "", "respin": False, "weight": 22},
                {"idx": 2, "name": "🛡 Страховка 50%", "coins": 0, "booster": "insure50", "respin": False, "weight": 15},
                {"idx": 3, "name": "⚡ Буст +0.35", "coins": 0, "booster": "boost035", "respin": False, "weight": 15},
                {"idx": 4, "name": "🎟 Билет (+100 + Спин)", "coins": 100, "booster": "", "respin": True, "weight": 10},
                {"idx": 5, "name": "💎 +750 FC!", "coins": 750, "booster": "", "respin": False, "weight": 7},
                {"idx": 6, "name": "🔥 ДЖЕКПОТ +2000 FC!", "coins": 2000, "booster": "", "respin": False, "weight": 3},
            ]
            chosen = random.choices(sectors, weights=[s["weight"] for s in sectors], k=1)[0]
            await db_manager.spin_roulette_db(uid, chosen["coins"], chosen["booster"], chosen["respin"])

            st["rookie_spin"] = 1
            await db_manager.exec("UPDATE users SET fut_cards = $1 WHERE user_id = $2", dump_user_fut_state(st, vip_act), uid)
            if chosen["coins"] >= 750:
                push_live_ticker(f"🎰 {user['username']} выбил {chosen['name']} в ежедневной рулетке!")

            return await _fast_delta_response(uid, {
                "sector": chosen,
                "coin_delta": chosen["coins"]
            })

        elif action == "bm_bid":
            amount = int(body.get("amount") or 0)
            res = await db_manager.place_black_market_bid(uid, amount)
            if not res["ok"]:
                return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)
            SHARED_DB_CACHE["bm_lot"] = await db_manager.get_or_rotate_black_market()
            SHARED_DB_CACHE["bm_ts"] = int(now_msk().timestamp())
            lot = SHARED_DB_CACHE["bm_lot"]
            lot_card = FUT_CARDS.get(lot["lot_id"], {"name": "Секретный лот", "desc": "", "role": "FW", "val": 24, "ovr": 99})
            asyncio.create_task(db_manager.unlock_achievement(uid, "bm_tycoon"))
            return await _fast_delta_response(uid, {
                "message": f"🔨 Ставка {amount} FC принята! Ты лидер торгов!",
                "black_market": {
                    "card": lot_card, "highest_bid": lot["highest_bid"],
                    "leader_id": int(lot["leader_id"]), "leader_name": lot["leader_name"],
                    "min_next_bid": int(lot["highest_bid"]) + 500
                },
                "coin_delta": -amount
            })

        # 12. ПРИЕМ КУПОНА (С ОПЦИЕЙ ПЛАТНОЙ СТРАХОВКИ +10% К СУММЕ)
        elif action == "submit_slip":
            items = body.get("items") or []
            stake_amount = int(body.get("stake") or 0)
            is_secret = bool(body.get("is_secret"))
            insure_paid = bool(body.get("insure_paid"))

            if not items:
                return web.json_response({"ok": False, "error": "Купон пуст! Выбери хотя бы один исход."}, headers=CORS_HEADERS)
            if len(items) > 6:
                return web.json_response({"ok": False, "error": "Максимум 6 событий в одном экспрессе!"}, headers=CORS_HEADERS)
            if stake_amount < 10:
                return web.json_response({"ok": False, "error": "Минимальная сумма ставки — 10 FC!"}, headers=CORS_HEADERS)

            db_schedule = await get_matches_instant()
            now_ts = int(now_msk().timestamp())

            if len(items) == 1:
                it = items[0]
                m = db_schedule.get(it["league_key"], {}).get("matches", {}).get(str(it["event_id"]))
                if not m or m.get("is_live") or m["start_ts"] <= now_ts:
                    return web.json_response({"ok": False, "error": f"Прием ставок на матч {it.get('teamsTitle', '')} уже закрыт!"}, headers=CORS_HEADERS)
                mkt = evaluate_custom_market(m, it["pick_code"])
                if not mkt:
                    return web.json_response({"ok": False, "error": "Некорректный исход!"}, headers=CORS_HEADERS)

                ru_teams = f"{translate_team_ru(m['home_team'])} — {translate_team_ru(m['away_team'])}"
                legs = [{"league_slug": m["league_slug"], "event_id": m["event_id"], "teams": ru_teams, "pick_code": mkt["pick_code"], "pick_label": mkt["label"], "odds": mkt["odds"]}]
                res = await fast_create_pending_bet(
                    uid, user["username"], f"{ru_teams} ({m['short_date']})", mkt["label"],
                    stake_amount, mkt["odds"], mkt["prob"], m["end_ts"],
                    bet_type="single", legs_json=json.dumps(legs, ensure_ascii=False), insure_paid=insure_paid
                )
                if not res["ok"]:
                    return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)

                asyncio.create_task(db_manager.unlock_achievement(uid, "winter_2027"))
                if is_secret:
                    asyncio.create_task(db_manager.unlock_achievement(uid, "secret_agent"))

                ins_note = " 🛡[Застрахован 50%]" if res.get("booster_used") == "insure50" else ""
                return await _fast_delta_response(uid, {
                    "message": f"✅ Ординар #{res['bet_id']}{ins_note} принят (Кэф {res['final_odds']})! Выплата: {res['potential_win']} FC",
                    "coin_delta": -res["total_deduct"]
                }, include_bets=True)

            total_odd, comb_prob, max_end = 1.0, 1.0, 0
            legs, titles = [], []
            for idx, it in enumerate(items, 1):
                m = db_schedule.get(it["league_key"], {}).get("matches", {}).get(str(it["event_id"]))
                if not m or m.get("is_live") or m["start_ts"] <= now_ts:
                    return web.json_response({"ok": False, "error": f"Матч {it.get('teamsTitle', '')} уже начался!"}, headers=CORS_HEADERS)
                mkt = evaluate_custom_market(m, it["pick_code"])
                if not mkt:
                    return web.json_response({"ok": False, "error": "Ошибка расчета котировки"}, headers=CORS_HEADERS)
                total_odd *= mkt["odds"]
                comb_prob *= (mkt["prob"] / 100.0)
                if m["end_ts"] > max_end:
                    max_end = m["end_ts"]
                ru_teams = f"{translate_team_ru(m['home_team'])} — {translate_team_ru(m['away_team'])}"
                titles.append(f"{idx}. {ru_teams} — {mkt['label']} ({mkt['odds']})")
                legs.append({"league_slug": m["league_slug"], "event_id": m["event_id"], "teams": ru_teams, "pick_code": mkt["pick_code"], "pick_label": mkt["label"], "odds": mkt["odds"]})

            final_exp_odd = round(total_odd, 2)
            res = await fast_create_pending_bet(
                uid, user["username"], f"Экспресс ({len(legs)} матчей)", "\n".join(titles),
                stake_amount, final_exp_odd, round(comb_prob * 100, 1), max_end,
                bet_type="express", legs_json=json.dumps(legs, ensure_ascii=False), insure_paid=insure_paid
            )
            if not res["ok"]:
                return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)

            asyncio.create_task(db_manager.unlock_achievement(uid, "winter_2027"))
            boost_tag = f" [Буст +{res['exp_boost_pct']}%]" if res.get("exp_boost_pct", 0) > 0 else ""
            ins_note = " 🛡[Страховка 50%]" if res.get("booster_used") == "insure50" else ""
            return await _fast_delta_response(uid, {
                "message": f"⚡ Экспресс #{res['bet_id']}{boost_tag}{ins_note} принят (Кэф {res['final_odds']})! Выплата: {res['potential_win']} FC",
                "coin_delta": -res["total_deduct"]
            }, include_bets=True)

        elif action == "cashout_bet":
            bet_id = int(body.get("bet_id") or 0)
            bet = await db_manager.get_bet_by_id(bet_id, uid)
            if not bet or bet["status"] != "pending":
                return web.json_response({"ok": False, "error": "Купон уже рассчитан!"}, headers=CORS_HEADERS)
            async with aiohttp.ClientSession() as session:
                offer = await calculate_cashout_offer(session, bet)
            if offer <= 0:
                return web.json_response({"ok": False, "error": "CashOut недоступен: одно из событий уже проиграло."}, headers=CORS_HEADERS)
            res = await db_manager.settle_bet_in_db(bet, "cashout", offer, f"CashOut ({offer} FC)")
            return await _fast_delta_response(uid, {
                "message": f"💸 Купон #{bet_id} выкуплен! На баланс зачислено +{res['payout']} FC!",
                "coin_delta": res["payout"]
            }, include_bets=True)

        elif action == "se_submit":
            picks_map = body.get("picks") or {}
            line_cache = await get_precomputed_webapp_line()
            round_key, weekly_matches = await db_manager.get_or_create_weekly_superexpress(line_cache["filtered_db"])
            if len(weekly_matches) < 6:
                return web.json_response({"ok": False, "error": "Тираж недели еще формируется."}, headers=CORS_HEADERS)
            if await db_manager.get_superexpress_entry(uid, round_key):
                return web.json_response({"ok": False, "error": "Ты уже участвуешь в тираже этой недели!"}, headers=CORS_HEADERS)

            lbl_map = {"p1": "П1", "x": "Х", "p2": "П2"}
            picks_list = []
            for idx, m in enumerate(weekly_matches):
                c = str(picks_map.get(str(idx)) or "")
                if c not in ("p1", "x", "p2"):
                    return web.json_response({"ok": False, "error": f"Выбери исход для матча #{idx+1}!"}, headers=CORS_HEADERS)
                picks_list.append({"event_id": m["event_id"], "league_slug": m["league_slug"], "teams": m["teams"], "pick_code": c, "pick_label": lbl_map[c]})
            await db_manager.create_superexpress_entry(uid, round_key, picks_list)
            return await _fast_delta_response(uid, {
                "message": "🎯 Прогноз на Суперэкспресс недели зафиксирован!",
                "se_entry": {"status": "pending", "guessed": 0, "payout": 0, "picks": picks_list}
            })

        elif action == "pvp_create":
            mode = str(body.get("mode") or "bot")
            stake = int(body.get("stake") or 0)
            kick_dir = str(body.get("kick") or "C")
            save_dir = str(body.get("save") or "C")
            target_query = str(body.get("target") or "").strip()

            if stake < 50:
                return web.json_response({"ok": False, "error": "Минимальная ставка в PvP — 50 FC!"}, headers=CORS_HEADERS)
            if user["balance"] < stake:
                return web.json_response({"ok": False, "error": "Недостаточно FC на балансе!"}, headers=CORS_HEADERS)

            if mode == "bot":
                bot_kick, bot_save = random.choice(["L", "C", "R"]), random.choice(["L", "C", "R"])
                g1, g2, log_txt = resolve_penalty_shootout(kick_dir, save_dir, bot_kick, bot_save)
                clean_log = re.sub(r"<.*?>", "", log_txt)
                LAST_PVP_MATCH[uid] = {"mode": "bot", "target": "", "opponent_name": "🤖 Кипер Лиги", "stake": stake}
                c_delta = 0
                if g1 > g2:
                    win_profit = round(stake * 0.95, 1)
                    c_delta = win_profit
                    await db_manager.exec("UPDATE users SET balance = balance + $1, pvp_wins = pvp_wins + 1, profit = profit + $1 WHERE user_id = $2", win_profit, uid)
                    if int(user.get("pvp_wins") or 0) + 1 >= 5:
                        asyncio.create_task(db_manager.unlock_achievement(uid, "pvp_gladiator"))
                    res_msg = f"🎉 ПОБЕДА ({g1}:{g2})! Выигрыш: +{win_profit} FC!"
                    if stake >= 500:
                        push_live_ticker(f"⚽ {user['username']} обыграл Кипера Лиги в пенальти и забрал +{win_profit} FC!")
                elif g2 > g1:
                    c_delta = -stake
                    await db_manager.exec("UPDATE users SET balance = balance - $1, profit = profit - $1 WHERE user_id = $2", float(stake), uid)
                    res_msg = f"❌ ПОРАЖЕНИЕ ({g1}:{g2})! Потеряно: -{stake} FC."
                else:
                    res_msg = f"🤝 НИЧЬЯ ({g1}:{g2})! Ставка {stake} FC возвращена."
                return await _fast_delta_response(uid, {"message": res_msg, "detail": clean_log, "coin_delta": c_delta})

            elif mode == "lobby":
                res = await db_manager.create_pvp_duel(uid, stake, kick_dir, save_dir, target_id=0)
                if not res["ok"]:
                    return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)
                return await _fast_delta_response(uid, {"message": f"🌐 Вызов #{res['duel_id']} ({stake} FC) опубликован в лобби!", "coin_delta": -stake}, include_pvp=True)

            elif mode == "direct":
                target_user = await db_manager.find_user_by_query(target_query)
                if not target_user:
                    return web.json_response({"ok": False, "error": "Игрок с таким Ником или ID не найден!"}, headers=CORS_HEADERS)
                if target_user["user_id"] == uid:
                    return web.json_response({"ok": False, "error": "Нельзя вызвать самого себя!"}, headers=CORS_HEADERS)
                res = await db_manager.create_pvp_duel(uid, stake, kick_dir, save_dir, target_id=target_user["user_id"])
                if not res["ok"]:
                    return web.json_response({"ok": False, "error": res["error"]}, headers=CORS_HEADERS)
                duel_id = res["duel_id"]
                LAST_PVP_MATCH[uid] = {"mode": "direct", "target": str(target_user["user_id"]), "opponent_name": target_user["username"], "stake": stake}
                try:
                    t_kb = InlineKeyboardBuilder()
                    if WEBAPP_BASE_URL.startswith("https://"):
                        t_kb.button(text=f"⚔️ Принять вызов в Web-App ({stake} FC)", web_app=WebAppInfo(url=f"{WEBAPP_BASE_URL}/app?uid={target_user['user_id']}"))
                    await bot.send_message(
                        target_user["user_id"],
                        f"🔥 <b>ЛИЧНЫЙ ВЫЗОВ В ПЕНАЛЬТИ!</b>\n\n<blockquote>👤 Соперник: <b>{user['username']}</b>\n💵 Ставка: <b><code>{stake} FC</code></b></blockquote>",
                        reply_markup=t_kb.as_markup(), parse_mode="HTML"
                    )
                except Exception:
                    pass
                return await _fast_delta_response(uid, {"message": f"🎯 Вызов #{duel_id} отправлен игроку {target_user['username']}!", "coin_delta": -stake}, include_pvp=True)

        elif action == "pvp_accept":
            duel_id = int(body.get("duel_id") or 0)
            kick_dir = str(body.get("kick") or "C")
            save_dir = str(body.get("save") or "C")
            d = await db_manager.get_pvp_duel(duel_id)
            if not d or d["status"] != "open":
                return web.json_response({"ok": False, "error": "Этот вызов уже закрыт!"}, headers=CORS_HEADERS)
            stake = int(d["stake"])
            if user["balance"] < stake:
                return web.json_response({"ok": False, "error": f"Недостаточно средств ({stake} FC)!"}, headers=CORS_HEADERS)

            await db_manager.exec("UPDATE pvp_duels SET status = 'closed' WHERE duel_id = $1", duel_id)
            await db_manager.exec("UPDATE users SET balance = balance - $1 WHERE user_id = $2", float(stake), uid)

            LAST_PVP_MATCH[uid] = {"mode": "direct", "target": str(d["creator_id"]), "opponent_name": d["creator_name"], "stake": stake}
            LAST_PVP_MATCH[d["creator_id"]] = {"mode": "direct", "target": str(uid), "opponent_name": user["username"], "stake": stake}

            g1, g2, log_txt = resolve_penalty_shootout(d["kick_dir"], d["save_dir"], kick_dir, save_dir)
            bank = round(stake * 2 * 0.95, 1)
            c_delta = 0

            if g1 > g2:
                c_delta = -stake
                await db_manager.exec("UPDATE users SET balance = balance + $1, pvp_wins = pvp_wins + 1, profit = profit + $2 WHERE user_id = $3", bank, bank - stake, d["creator_id"])
                res_headline = f"🏆 Победил {d['creator_name']} (+{bank} FC)!"
                push_live_ticker(f"⚔️ {d['creator_name']} победил в PvP-дуэли и забрал банк {bank} FC!")
            elif g2 > g1:
                c_delta = round(bank - stake, 1)
                await db_manager.exec("UPDATE users SET balance = balance + $1, pvp_wins = pvp_wins + 1, profit = profit + $2 WHERE user_id = $3", bank, bank - stake, uid)
                res_headline = f"🏆 Ты победил (+{bank} FC)!"
                push_live_ticker(f"⚔️ {user['username']} победил в PvP-дуэли и забрал банк {bank} FC!")
            else:
                await db_manager.exec("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(stake), d["creator_id"])
                await db_manager.exec("UPDATE users SET balance = balance + $1 WHERE user_id = $2", float(stake), uid)
                res_headline = f"🤝 Ничья ({g1}:{g2})! Ставки возвращены."

            try:
                await bot.send_message(
                    d["creator_id"],
                    f"⚔️ <b>ИТОГ PVP-ДУЭЛИ #{duel_id}</b>\n<b>{d['creator_name']}</b> vs <b>{user['username']}</b>\n\n<blockquote>{log_txt}</blockquote>\n{res_headline}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return await _fast_delta_response(uid, {"message": res_headline, "detail": re.sub(r"<.*?>", "", log_txt), "coin_delta": c_delta}, include_pvp=True)

        elif action == "pvp_cancel":
            duel_id = int(body.get("duel_id") or 0)
            cancelled = await db_manager.cancel_pvp_duel(duel_id, uid)
            if not cancelled:
                return web.json_response({"ok": False, "error": "Не удалось отменить вызов"}, headers=CORS_HEADERS)
            return await _fast_delta_response(uid, {"message": "✅ Вызов отменен, средства возвращены!"}, include_pvp=True)

        elif action == "set_club":
            club = str(body.get("club") or "")
            if club in POPULAR_CLUBS:
                await db_manager.set_favorite_club(uid, club)
                return await _fast_delta_response(uid, {"message": f"⭐ Любимый клуб: {club} (+10% к прибыли)!"})
            return web.json_response({"ok": False, "error": "Клуб не найден"}, headers=CORS_HEADERS)

        elif action == "set_nickname":
            mode = str(body.get("mode") or "custom")
            if mode == "random":
                new_nick = generate_football_nickname()
            else:
                ok, val = validate_custom_nickname(str(body.get("nickname") or ""))
                if not ok:
                    return web.json_response({"ok": False, "error": val}, headers=CORS_HEADERS)
                new_nick = val
            await db_manager.update_nickname(uid, new_nick)
            return await _fast_delta_response(uid, {"message": f"✏️ Твой новый никнейм: {new_nick}"})

        elif action == "toggle_incognito":
            inc_st = await db_manager.toggle_user_incognito(uid)
            msg = "🕶 Инкогнито ВКЛЮЧЕН (ник скрыт в Топ-10)" if inc_st == 1 else "👀 Инкогнито ВЫКЛЮЧЕН"
            return await _fast_delta_response(uid, {"message": msg})

    return web.json_response({"ok": False, "error": "Unknown action"}, status=400, headers=CORS_HEADERS)

async def handle_db_status(request):
    """Живая диагностика БД, кэша и P2P-лотов по адресу /db_status"""
    t0 = now_msk().timestamp()
    try:
        users_cnt = await db_manager.fetchval("SELECT COUNT(*) FROM users")
        pending_bets = await db_manager.fetchval("SELECT COUNT(*) FROM bets WHERE status = 'pending'")
        total_bets = await db_manager.fetchval("SELECT COUNT(*) FROM bets")
        ping_ms = round((now_msk().timestamp() - t0) * 1000, 1)
        engine_name = "PostgreSQL (Внешняя облачная БД — НАДЕЖНО ✅)" if db_manager.use_pg else "SQLite (Локальный файл — РИСК СБРОСА НА RENDER ⚠️)"

        return web.json_response({
            "ok": True,
            "db_engine": engine_name,
            "db_ping_ms": f"{ping_ms} мс",
            "total_users": users_cnt,
            "active_bets": pending_bets,
            "total_bets": total_bets,
            "p2p_active_lots": len(P2P_CONTAINER_MARKET),
            "ram_cached_users": len(RAM_USER_CACHE),
            "precomputed_matches": len(PRECOMPUTED_WEBAPP_CACHE.get("matches", []))
        }, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500, headers=CORS_HEADERS)

async def ensure_high_load_indexes():
    """Создает скоростные индексы БД для мгновенной работы при тысячах ставок"""
    queries = [
        "CREATE INDEX IF NOT EXISTS idx_bets_user_status ON bets (user_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_bets_status ON bets (status);",
        "CREATE INDEX IF NOT EXISTS idx_users_balance ON users (balance DESC);",
        "CREATE INDEX IF NOT EXISTS idx_pvp_status ON pvp_duels (status);"
    ]
    for q in queries:
        try:
            await db_manager.exec(q)
        except Exception as e:
            logging.warning(f"Индекс БД: {e}")

# Фоновый пульс БД каждые 18 секунд + автоочистка RAM (защита от OOM 512MB) + авто-бэкап раз в 12 часов
async def db_keep_alive_worker():
    last_backup_ts = now_msk().timestamp()
    while True:
        await asyncio.sleep(18)
        now_f = now_msk().timestamp()
        try:
            await db_manager.fetchval("SELECT 1")
        except Exception:
            pass
        # Очистка устаревших записей из RAM_USER_CACHE (старше 120 сек)
        try:
            stale_uids = [k for k, v in list(RAM_USER_CACHE.items()) if (now_f - v.get("ts", 0)) > 120.0]
            for k in stale_uids:
                RAM_USER_CACHE.pop(k, None)
            if len(USER_ACTION_LOCKS) > 1500:
                free_locks = [k for k, lck in list(USER_ACTION_LOCKS.items()) if not lck.locked()]
                for k in free_locks[:1000]:
                    USER_ACTION_LOCKS.pop(k, None)
        except Exception:
            pass
        # Автоматический бэкап базы админу в Telegram каждые 12 часов (43200 сек)
        if (now_f - last_backup_ts) >= 43200:
            last_backup_ts = now_f
            asyncio.create_task(send_database_backup_to_admin("Авто-бэкап (каждые 12ч)"))

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/db_status", handle_db_status)
    app.router.add_get("/app", serve_webapp_html)
    app.router.add_get("/api/state/{user_id}", api_get_state)
    app.router.add_get("/api/match_ai/{league_key}/{event_id}", api_get_match_ai)
    app.router.add_post("/api/action", api_handle_action)
    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def setup_bot_commands():
    try:
        if WEBAPP_BASE_URL.startswith("https://"):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🎄 Играть",
                    web_app=WebAppInfo(url=f"{WEBAPP_BASE_URL}/app")
                )
            )
        commands = [
            BotCommand(command="start", description="🎄 Открыть игру и Профиль"),
            BotCommand(command="profile", description="👤 Личный кабинет и мой ID"),
            BotCommand(command="backup", description="💾 Выгрузить бэкап БД (Админ)"),
            BotCommand(command="admin", description="⚙️ Панель управления (Админ)")
        ]
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception as e:
        logging.warning(f"Не удалось установить меню команд: {e}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await db_manager.init()
    await ensure_high_load_indexes()
    await init_and_load_p2p_market()
    if not db_manager.use_pg:
        try:
            await db_manager.exec("PRAGMA journal_mode=WAL;")
            await db_manager.exec("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
    await get_real_matches(force_refresh=True)
    await get_precomputed_webapp_line()
    await start_web_server()
    await setup_bot_commands()
    asyncio.create_task(db_keep_alive_worker())
    asyncio.create_task(match_settlement_worker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
