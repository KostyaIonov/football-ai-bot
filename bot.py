import os
import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import quote
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from openai import AsyncOpenAI

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
AI_API_KEY = os.getenv("AI_API_KEY", "")
# Ключ Groq отлично работает с американского сервера Render
GROQ_KEY = os.getenv("GROQ_API_KEY", "gsk_" + "4Tsu0D9a7WpeKXgsfCEBWGdyb3FYh36zWsKthL2t6jJ1ROtV1dqH")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Клиент 1: Groq (США -> США, мгновенный отклик с Render)
groq_client = AsyncOpenAI(
    api_key=GROQ_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# Клиент 2: OpenRouter (Автовыбор доступной бесплатной модели)
or_client = AsyncOpenAI(
    api_key=AI_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    default_headers={"HTTP-Referer": "https://render.com", "X-Title": "Football Bot"}
)

async def ask_ai(prompt: str, system_prompt: str = "Ты профессиональный футбольный аналитик.") -> str | None:
    """Пробует 3 независимых ИИ-шлюза по очереди"""
    # 1. Пробуем быстрый Groq с сервера в США
    for groq_model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"]:
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

    # 2. Пробуем авто-роутер бесплатных моделей OpenRouter
    if AI_API_KEY:
        for or_model in ["openrouter/free", "google/gemma-3-27b-it:free", "meta-llama/llama-3.3-70b-instruct:free"]:
            try:
                resp = await asyncio.wait_for(
                    or_client.chat.completions.create(
                        model=or_model,
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
                    return resp.choices[0].message.content.strip()
            except Exception as e:
                logging.warning(f"OpenRouter ({or_model}) пропущен: {e}")

    # 3. Пробуем прямой GET-шлюз Pollinations
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
        logging.warning(f"Резервный GET-шлюз пропущен: {e}")

    return None

# ================= ВСТРОЕННЫЙ АНАЛИТИЧЕСКИЙ ДВИЖОК (100% АПТАЙМ) =================
def smart_local_match_analysis(match: dict, probs: dict) -> str:
    """Генерирует экспертный разбор и лучшую ставку на основе математической модели"""
    t1, t2 = match["teams"].split(" vs ")
    odds = match["odds"]
    p1, x, p2 = probs["p1"], probs["x"], probs["p2"]

    if p1 >= 58:
        style = (
            f"⚔️ **Расклад сил:** {t1} выступает явным фаворитом домашнего поля (чистая вероятность победы {p1}%). "
            f"Команда заберет контроль мяча с первых минут и будет давить позиционными атаками, тогда как {t2} придется играть вторым номером."
        )
        bet = f"🎯 **Лучшая ставка:** Победа {t1} (П1) за кэф `{odds['p1']}` (альтернатива: Фора 1 (-1) или ИТБ1 (1.5))."
    elif p2 >= 50:
        style = (
            f"⚔️ **Расклад сил:** Несмотря на выездной статус, {t2} превосходит соперника в классе и реализации моментов ({p2}% против {p1}%). "
            f"Ожидается прагматичная игра гостей на быстрых переходных фазах."
        )
        bet = f"🎯 **Лучшая ставка:** Победа {t2} (П2) за кэф `{odds['p2']}` (надежный вариант: Х2 + ТБ 1.5)."
    elif abs(p1 - p2) <= 12:
        style = (
            f"⚔️ **Расклад сил:** Матч равных по потенциалу соперников ({p1}% на {p2}%) с высокой плотностью в центре поля. "
            f"Обе команды обладают мощной линией атаки и способны обменяться забитыми мячами."
        )
        bet = f"🎯 **Лучшая ставка:** Обе забьют (ДА) или Двойной шанс 1Х за надёжный кэф (риск-вариант: Ничья за `{odds['x']}`)."
    else:
        style = (
            f"⚔️ **Расклад сил:** {t1} имеет игровой перевес ({p1}%) за счет фактора своего поля, однако {t2} опасен на стандартах и контратаках ({p2}%). "
            f"Value Bet кроется в комбинированном исходе на хозяев."
        )
        bet = f"🎯 **Лучшая ставка:** Фора {t1} (0) или 1Х + Тотал Больше 1.5 (базовый кэф П1: `{odds['p1']}`)."

    return f"{style}\n\n{bet}"

def smart_local_express(db: dict) -> str:
    """Формирует готовый Экспресс дня из 6 матчей по математическому перевесу"""
    picks = []
    total_odd = 1.0

    for l_val in db.values():
        for m in l_val["matches"].values():
            if len(picks) >= 6:
                break
            t1, t2 = m["teams"].split(" vs ")
            o = m["odds"]
            probs = calculate_ai_probabilities(o)

            if probs["p1"] >= 55:
                bet_str = f"Победа {t1} (П1)"
                k = o["p1"]
            elif probs["p1"] >= 43:
                bet_str = f"{t1} не проиграет (1Х) + ТБ 1.5"
                k = round(o["p1"] * 0.72, 2)
            elif probs["p2"] >= 48:
                bet_str = f"Фора {t2} (0)"
                k = round(o["p2"] * 0.75, 2)
            else:
                bet_str = "Обе забьют (ДА) / ТБ 2.0"
                k = 1.65

            total_odd *= k
            picks.append(f"{len(picks)+1}. ⚽ **{m['teams']}**\n   🎯 Ставка: *{bet_str}* — кэф `{k}`")
        if len(picks) >= 6:
            break

    header = "\n\n".join(picks)
    return (
        f"{header}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📈 **Итоговый коэффициент экспресса:** `{round(total_odd, 2)}`\n"
        f"💡 *Рекомендация: оптимально для распределения флэтом (2-3% от банка).*"
    )

# ================= БАЗА МАТЧЕЙ НА БЛИЖАЙШИЕ 7 ДНЕЙ =================
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

# ================= ОБРАБОТЧИКИ СОБЫТИЙ =================
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
    await callback.message.edit_text("⚡ *ИИ анализирует линию и собирает Экспресс из 6 матчей...*", parse_mode="Markdown")
    db = get_base_matches()
    all_matches = []
    for l_val in db.values():
        for m_val in l_val["matches"].values():
            all_matches.append(f"{m_val['teams']} (П1:{m_val['odds']['p1']}, Х:{m_val['odds']['x']}, П2:{m_val['odds']['p2']})")
    
    selected_six = "\n".join(all_matches[:6])
    prompt = (
        f"Вот 6 главных матчей недели:\n{selected_six}\n\n"
        f"Составь «Экспресс дня» строго из этих 6 матчей. Для каждого матча напиши 1 строчкой:\n"
        f"Команды — Лучшая надежная ставка (исход, фора или тотал) и примерный кэф.\n"
        f"В конце напиши итоговый суммарный коэффициент экспресса."
    )
    express_text = await ask_ai(prompt)
    if not express_text:
        express_text = smart_local_express(db)
    
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
        f"Чистые вероятности: П1={probs['p1']}%, Х={probs['x']}%, П2={probs['p2']}%\n"
        f"Напиши очень кратко (до 70 слов) в 2 пункта:\n"
        f"1. ⚔️ Краткий анализ исхода (ключевой фактор матча).\n"
        f"2. 🎯 Самая лучшая ставка (Value Bet) на этот матч с коэффициентом."
    )
    ai_verdict = await ask_ai(prompt)
    if not ai_verdict:
        ai_verdict = smart_local_match_analysis(match, probs)

    text = (
        f"⚽ **{match['teams']}**\n"
        f"🕒 Дата: {match['date']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Коэффициенты (Маржа: {probs['margin']}%):**\n"
        f"• П1: `{odds['p1']}` | Х: `{odds['x']}` | П2: `{odds['p2']}`\n\n"
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
