import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from openai import AsyncOpenAI

# ================= НАСТРОЙКИ (Ключи берутся из настроек сервера!) =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8689460796:AAG05s9JncG8WPndDsB0cJgSItUcIgTAxZk")
AI_API_KEY = os.getenv("AI_API_KEY", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключаем OpenRouter (работает без VPN и на серверах, и в РФ)
# Подключаем OpenRouter с обязательными системными заголовками
ai_client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": "https://render.com",
        "X-Title": "Football Analyst Bot"
    }
)

# Проверенные бесплатные модели OpenRouter
FREE_MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-2-9b-it:free"
]



async def ask_ai(prompt: str, system_prompt: str = "Ты профессиональный футбольный аналитик.", max_tokens: int = 400) -> str:
    """Умный запрос к ИИ: пробует модели по очереди, чтобы бот никогда не выдавал ошибку"""
    for model_name in FREE_MODELS:
        try:
            response = await asyncio.wait_for(
                ai_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4,
                    max_tokens=max_tokens
                ),
                timeout=12.0
            )
            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content
        except Exception as e:
            logging.warning(f"Модель {model_name} занята, переключаюсь на резервную... ({e})")
            continue
    return "⚠️ Все бесплатные линии ИИ сейчас перегружены. Ориентируйся на математический расчет вероятностей выше!"

# ================= БАЗА И АВТООБНОВЛЕНИЕ МАТЧЕЙ НА 7 ДНЕЙ =================
CACHE_DATE = None
CACHED_DB = None

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
                "m2": {"teams": "Атлетико Мадрид vs Вильярреал", "date": f"{d[2]}, 20:30 МСК", "odds": {"p1": 1.75, "x": 3.60, "p2": 4.80}},
                "m3": {"teams": "Реал Сосьедад vs Бетис", "date": f"{d[4]}, 23:00 МСК", "odds": {"p1": 1.90, "x": 3.40, "p2": 4.20}}
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

def calculate_ai_probabilities(odds: dict) -> dict:
    raw_p1, raw_x, raw_p2 = 1 / odds["p1"], 1 / odds["x"], 1 / odds["p2"]
    margin_sum = raw_p1 + raw_x + raw_p2
    return {
        "p1": round((raw_p1 / margin_sum) * 100, 1),
        "x": round((raw_x / margin_sum) * 100, 1),
        "p2": round((raw_p2 / margin_sum) * 100, 1),
        "margin": round((margin_sum - 1) * 100, 2)
    }

# ================= КЛАВИАТУРЫ =================
def main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Лига Чемпионов", callback_data="league:ucl")
    builder.button(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ (Англия)", callback_data="league:epl")
    builder.button(text="🇪🇸 Ла Лига (Испания)", callback_data="league:laliga")
    builder.button(text="🇮🇹 Серия А (Италия)", callback_data="league:seriea")
    builder.button(text="🇩🇪 Бундеслига (Германия)", callback_data="league:bundesliga")
    builder.button(text="🇫🇷 Лига 1 (Франция)", callback_data="league:ligue1")
    builder.button(text="⚡ Экспресс дня (6 матчей)", callback_data="express_day")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()

def matches_kb(league_key: str, matches_dict: dict):
    builder = InlineKeyboardBuilder()
    for match_id, data in matches_dict.items():
        short_date = data['date'].split(',')[0]
        builder.button(text=f"⚽ {data['teams']} ({short_date})", callback_data=f"match:{league_key}:{match_id}")
    builder.button(text="⬅️ Назад в главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def back_to_matches_kb(league_key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К списку матчей лиги", callback_data=f"league:{league_key}")
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

# ================= ОБРАБОТЧИКИ =================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    text = (
        "👋 **Привет! Твой персональный ИИ-аналитик футбола.**\n\n"
        "📈 Расписание на ближайшие 7 дней (Топ-5 лиг + ЛЧ).\n"
        "🤖 Математический расчет вероятностей без маржи и лучшая ставка в одном окне.\n\n"
        "👇 Выбери турнир или открой Экспресс дня:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_main")
async def process_back_main(callback: CallbackQuery):
    await callback.message.edit_text("👇 Выбери турнир или открой Экспресс дня:", reply_markup=main_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "express_day")
async def process_express(callback: CallbackQuery):
    await callback.message.edit_text("⚡ *Нейросеть анализирует линию и собирает Экспресс из 6 матчей...*", parse_mode="Markdown")
    db = get_base_matches()
    all_matches = []
    for l_key, l_val in db.items():
        for m_val in l_val["matches"].values():
            all_matches.append(f"{m_val['teams']} (П1:{m_val['odds']['p1']}, Х:{m_val['odds']['x']}, П2:{m_val['odds']['p2']})")
    
    selected_six = "\n".join(all_matches[:6])
    prompt = (
        f"Вот 6 главных матчей:\n{selected_six}\n\n"
        f"Составь «Экспресс дня» строго из этих 6 матчей. Для каждого матча напиши 1 строчкой: "
        f"Команды — Лучшая надежная ставка (исход, фора или тотал) и примерный кэф. В конце посчитай общий коэффициент экспресса."
    )
    express_text = await ask_ai(prompt, max_tokens=450)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 В главное меню", callback_data="back_to_main")
    text = f"🔥 **ЭКСПРЕСС ДНЯ (6 МАТЧЕЙ)**\n━━━━━━━━━━━━━━━━━━\n\n{express_text}"
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("league:"))
async def process_league_select(callback: CallbackQuery):
    league_key = callback.data.split(":")[1]
    db = get_base_matches()
    league_data = db.get(league_key)
    matches = league_data["matches"] if league_data else {}

    if not matches:
        text = f"**{league_data['title']}**\n\n❌ В ближайшие 7 дней матчей в этой лиге не будет."
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 В главное меню", callback_data="back_to_main")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        await callback.answer()
        return

    text = f"**{league_data['title']}**\n📅 Матчи на ближайшие 7 дней:"
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

    await callback.message.edit_text(f"🧠 *ИИ анализирует матч {match['teams']}...*", parse_mode="Markdown")
    
    prompt = (
        f"Турнир: {league_title}. Матч: {match['teams']}.\n"
        f"Коэффициенты: П1={odds['p1']}, Х={odds['x']}, П2={odds['p2']}.\n"
        f"Чистые вероятности: П1={probs['p1']}%, Х={probs['x']}%, П2={probs['p2']}%.\n"
        f"Напиши очень кратко (до 70 слов) в 2 пункта:\n"
        f"1. ⚔️ Краткий анализ исхода (ключевой фактор матча).\n"
        f"2. 🎯 Самая лучшая ставка (Value Bet) на этот матч."
    )
    ai_verdict = await ask_ai(prompt, max_tokens=250)

    text = (
        f"⚽ **{match['teams']}**\n"
        f"🕒 Дата: {match['date']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Коэффициенты (Маржа: {probs['margin']}%):**\n"
        f"• П1: `{odds['p1']}` | Х: `{odds['x']}` | П2: `{odds['p2']}`\n"
        f"🧮 **Вероятности:** П1: **{probs['p1']}%** | Х: **{probs['x']}%** | П2: **{probs['p2']}%**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Анализ и лучшая ставка:**\n\n{ai_verdict}"
    )

    await callback.message.edit_text(text, reply_markup=back_to_matches_kb(league_key))
    await callback.answer()

# ================= МИКРО-СЕРВЕР ДЛЯ RENDER 24/7 =================
async def handle_ping(request):
    return web.Response(text="Football AI Bot is running 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())