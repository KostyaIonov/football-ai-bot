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

    if slip_count > 0:
        builder.button(text=f"🧺 Купон экспресса ({slip_count})", callback_data="view_slip")
        builder.adjust(1, 2, 2, 2, 1, 2, 2, 1, 1)
    else:
        builder.adjust(1, 2, 2, 2, 1, 2, 2, 1)
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

# ================= ВЕБ-СЕРВЕР + REST API ШЛЮЗ ПОД WEBAPP (TELEGRAM MINI APP) =================
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
}

async def handle_ping(request):
    return web.Response(text="AI_BET_BOT Live Sports & WebApp Engine is running 24/7!", headers=CORS_HEADERS)

async def api_get_user(request):
    """Полный JSON-профиль игрока для синхронизации с Telegram WebApp"""
    uid_str = request.match_info.get("user_id", "0")
    if not uid_str.isdigit():
        return web.json_response({"ok": False, "error": "Invalid user_id"}, status=400, headers=CORS_HEADERS)
    uid = int(uid_str)
    user = await db_manager.get_user(uid)
    buffs = get_user_fut_buffs(user)
    st_lvl = int(user.get("stadium_level") or 1)
    active_bets = await db_manager.get_user_bets(uid, active_only=True)
    return web.json_response({
        "ok": True,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "balance": round(user["balance"], 1),
            "wins": user["wins"],
            "losses": user["losses"],
            "profit": round(user["profit"], 1),
            "streak": user.get("streak", 0),
            "favorite_club": user.get("favorite_club", ""),
            "stadium_level": st_lvl,
            "stadium_info": STADIUM_LEVELS.get(st_lvl, STADIUM_LEVELS[1]),
            "stadiums_catalog": STADIUM_LEVELS,
            "lab_level": user.get("lab_level", 1),
            "fut_buffs": buffs,
            "active_bets_count": len(active_bets)
        }
    }, headers=CORS_HEADERS)

async def api_get_matches(request):
    """Возвращает LIVE и предстоящие матчи всех лиг для WebApp"""
    db = await get_real_matches()
    return web.json_response({"ok": True, "leagues": db}, headers=CORS_HEADERS)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/api/user/{user_id}", api_get_user)
    app.router.add_get("/api/matches", api_get_matches)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def setup_bot_commands():
    """Автоматически добавляет кнопку Меню с командами /start и /profile в Telegram"""
    commands = [
        BotCommand(command="start", description="⚽ Главное меню"),
        BotCommand(command="profile", description="👤 Личный кабинет и мой ID"),
        BotCommand(command="admin", description="⚙️ Панель управления (Админ)")
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception as e:
        logging.warning(f"Не удалось установить меню команд: {e}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await db_manager.init()
    await get_real_matches(force_refresh=True)
    await start_web_server()
    await setup_bot_commands()
    asyncio.create_task(match_settlement_worker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
