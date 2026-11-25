# card_renderer.py — Генератор спортивной инфографики для канала и чатов (Pillow)
import io
import os
import re
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675

# Палитра «Ночной Стадион»
BG_TOP = (10, 18, 34)
BG_BOT = (19, 34, 62)
CARD_BG = (22, 36, 63)
CARD_DARK = (15, 25, 45)
BORDER_ICE = (56, 189, 248)
BORDER_SOFT = (58, 82, 118)
GOLD = (251, 191, 36)
GOLD_DARK = (180, 120, 15)
EMERALD = (52, 211, 153)
EMERALD_DARK = (16, 125, 88)
CRIMSON = (244, 63, 94)
TEXT_MAIN = (248, 250, 252)
TEXT_MUTED = (158, 176, 202)
TEXT_DARK = (10, 18, 34)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BOLD_FONT_CANDIDATES = [
    os.path.join(_BASE_DIR, "fonts", "Montserrat-Bold.ttf"),
    os.path.join(_BASE_DIR, "fonts", "Inter-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

REG_FONT_CANDIDATES = [
    os.path.join(_BASE_DIR, "fonts", "Montserrat-Regular.ttf"),
    os.path.join(_BASE_DIR, "fonts", "Inter-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

_FONT_CACHE = {}

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = BOLD_FONT_CANDIDATES if bold else REG_FONT_CANDIDATES
    for path in candidates:
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size=size)
                _FONT_CACHE[key] = f
                return f
            except Exception:
                continue
    f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f

def _clean_text(s: str) -> str:
    """Убирает эмодзи и спец-глифы, которые отсутствуют в стандартных TTF-шрифтах."""
    raw = str(s or "")
    cleaned = []
    for ch in raw:
        cp = ord(ch)
        if cp >= 0x10000:
            continue
        if 0x2600 <= cp <= 0x27BF or 0xFE00 <= cp <= 0xFE0F or cp in (0x200D, 0x23F3, 0x23F0, 0x2B50):
            continue
        cleaned.append(ch)
    res = "".join(cleaned)
    res = re.sub(r"\s+", " ", res).strip()
    return res

def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    t = _clean_text(text)
    if not t:
        return ""
    if draw.textlength(t, font=font) <= max_w:
        return t
    while len(t) > 1 and draw.textlength(t + "…", font=font) > max_w:
        t = t[:-1]
    return t.rstrip() + "…"

def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int = 3) -> list[str]:
    words = _clean_text(text).split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines - 1:
                break
    if cur:
        lines.append(_truncate(draw, cur, font, max_w))
    return lines[:max_lines]

def _create_base_canvas(accent_rgb: tuple = BORDER_ICE) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)

    # Плавный вертикальный градиент
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Декоративная неоновая полоса сверху и тонкая рамка
    draw.rectangle([(0, 0), (W, 7)], fill=accent_rgb)
    draw.rounded_rectangle([(24, 24), (W - 24, H - 24)], radius=24, outline=(36, 56, 88), width=2)
    return img, draw

def _draw_header(draw: ImageDraw.ImageDraw, badge_text: str, title_text: str, right_text: str, badge_color: tuple = BORDER_ICE):
    f_badge = _load_font(18, bold=True)
    f_title = _load_font(34, bold=True)
    f_right = _load_font(20, bold=True)

    b_clean = _clean_text(badge_text).upper()
    bw = int(draw.textlength(b_clean, font=f_badge)) + 34
    draw.rounded_rectangle([(52, 46), (52 + bw, 82)], radius=18, fill=badge_color)
    draw.text((69, 53), b_clean, font=f_badge, fill=TEXT_DARK)

    if right_text:
        rt = _clean_text(right_text)
        rw = int(draw.textlength(rt, font=f_right))
        draw.text((W - 52 - rw, 52), rt, font=f_right, fill=TEXT_MUTED)

    draw.text((52, 94), _truncate(draw, title_text, f_title, W - 104), font=f_title, fill=TEXT_MAIN)

def _draw_footer(draw: ImageDraw.ImageDraw, left_note: str = "AI_BET_BOT • WINTER SEASON 2027", right_note: str = "ЖМИ КНОПКУ НИЖЕ ЧТОБЫ ПОСТАВИТЬ"):
    f_foot = _load_font(17, bold=True)
    draw.line([(52, H - 68), (W - 52, H - 68)], fill=(40, 60, 92), width=2)
    draw.text((52, H - 54), _clean_text(left_note), font=f_foot, fill=TEXT_MUTED)
    rn = _clean_text(right_note)
    rw = int(draw.textlength(rn, font=f_foot))
    draw.text((W - 52 - rw, H - 54), rn, font=f_foot, fill=GOLD)

def _draw_odd_pill(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int, label: str, val: str, highlight: bool = False):
    bg = (22, 68, 60) if highlight else CARD_DARK
    outline = EMERALD if highlight else BORDER_SOFT
    draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=12, fill=bg, outline=outline, width=2)
    f_lbl = _load_font(15, bold=True)
    f_val = _load_font(22, bold=True)
    cx = (x1 + x2) // 2
    lw = draw.textlength(label, font=f_lbl)
    vw = draw.textlength(val, font=f_val)
    draw.text((cx - lw / 2, y1 + 8), label, font=f_lbl, fill=EMERALD if highlight else TEXT_MUTED)
    draw.text((cx - vw / 2, y1 + 28), val, font=f_val, fill=TEXT_MAIN)

def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def _fmt_fc(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ") + " FC"


# ==================== 1. УТРЕННЯЯ АФИША ДНЯ (ТОП-3 МАТЧА) ====================
def render_daily_poster(matches: list[dict], date_label: str = "") -> bytes:
    img, draw = _create_base_canvas(accent_rgb=BORDER_ICE)
    _draw_header(
        draw,
        badge_text="АФИША ДНЯ • 2D XG ЛИНИЯ",
        title_text="ГЛАВНЫЕ МАТЧИ СЕГОДНЯ",
        right_text=date_label or "AI_BET_BOT",
        badge_color=BORDER_ICE,
    )

    f_league = _load_font(17, bold=True)
    f_team = _load_font(25, bold=True)
    f_meta = _load_font(18, bold=False)
    f_score = _load_font(22, bold=True)

    top3 = (matches or [])[:3]
    y_start = 152
    row_h = 138
    gap = 16

    for idx, m in enumerate(top3):
        y1 = y_start + idx * (row_h + gap)
        y2 = y1 + row_h
        is_mod = bool(m.get("is_match_of_day"))
        border_c = GOLD if is_mod else BORDER_SOFT
        draw.rounded_rectangle([(52, y1), (W - 52, y2)], radius=18, fill=CARD_BG, outline=border_c, width=2)

        league_t = _clean_text(m.get("league_title", "Турнир"))
        time_t = _clean_text(m.get("short_date", ""))
        tag_mod = "  •  МАТЧ ДНЯ +8%" if is_mod else ""
        draw.text((76, y1 + 14), _truncate(draw, f"{league_t}  •  {time_t}{tag_mod}", f_league, 680), font=f_league, fill=GOLD if is_mod else BORDER_ICE)

        h_name = _truncate(draw, m.get("home_team", "Хозяева"), f_team, 310)
        a_name = _truncate(draw, m.get("away_team", "Гости"), f_team, 310)
        teams_line = f"{h_name}  —  {a_name}"
        draw.text((76, y1 + 46), _truncate(draw, teams_line, f_team, 690), font=f_team, fill=TEXT_MAIN)

        xg = m.get("exp_goals", 2.6)
        best_sc = _clean_text(m.get("best_score", "2:1"))
        draw.text((76, y1 + 88), f"Прогноз ИИ: {best_sc}   |   Ожидаемые голы: {xg} xG", font=f_meta, fill=TEXT_MUTED)

        odds = m.get("odds") or {}
        p1_s = f"{odds.get('p1', '-')}" if odds.get("p1") else "—"
        x_s = f"{odds.get('x', '-')}" if odds.get("x") else "—"
        p2_s = f"{odds.get('p2', '-')}" if odds.get("p2") else "—"

        pill_y1, pill_y2 = y1 + 36, y2 - 36
        _draw_odd_pill(draw, W - 404, pill_y1, W - 304, pill_y2, "П1", p1_s, highlight=(float(odds.get("p1") or 99) < float(odds.get("p2") or 99)))
        _draw_odd_pill(draw, W - 290, pill_y1, W - 190, pill_y2, "Х", x_s)
        _draw_odd_pill(draw, W - 176, pill_y1, W - 76, pill_y2, "П2", p2_s, highlight=(float(odds.get("p2") or 99) < float(odds.get("p1") or 99)))

    if not top3:
        draw.text((52, 260), "Ближайшие топ-матчи обновляются...", font=f_score, fill=TEXT_MUTED)

    _draw_footer(draw, right_note="ОТКРЫТЬ ВСЮ ЛИНИЮ В WEB-APP ->")
    return _to_png_bytes(img)


# ==================== 2. SMART MONEY INDEX / ИИ-ДУЭЛЬ ПЕРЕД МАТЧЕМ ====================
def render_smart_money_card(match: dict, sm_data: dict) -> bytes:
    has_real = bool(sm_data and sm_data.get("has_real_money"))
    img, draw = _create_base_canvas(accent_rgb=EMERALD if has_real else GOLD)

    badge = "SMART MONEY INDEX • КУДА СТАВЯТ ИГРОКИ" if has_real else "АНАЛИТИКА ИИ • ПРАГМАТИК VS РОМАНТИК"
    _draw_header(
        draw,
        badge_text=badge,
        title_text=f"{match.get('home_team', '')}  —  {match.get('away_team', '')}",
        right_text=f"{match.get('league_title', '')} • {match.get('short_date', '')}",
        badge_color=EMERALD if has_real else GOLD,
    )

    f_sub = _load_font(22, bold=True)
    f_body = _load_font(20, bold=False)
    f_big = _load_font(30, bold=True)
    f_small = _load_font(17, bold=True)

    # Блок коэффициентов
    odds = match.get("odds") or {}
    y_o1, y_o2 = 160, 228
    _draw_odd_pill(draw, 52, y_o1, 250, y_o2, "ПОБЕДА 1", str(odds.get("p1") or "—"))
    _draw_odd_pill(draw, 268, y_o1, 466, y_o2, "НИЧЬЯ (Х)", str(odds.get("x") or "—"))
    _draw_odd_pill(draw, 484, y_o1, 682, y_o2, "ПОБЕДА 2", str(odds.get("p2") or "—"))
    _draw_odd_pill(draw, 712, y_o1, 920, y_o2, "ТБ 2.5", str(odds.get("tb25") or "—"))
    _draw_odd_pill(draw, 938, y_o1, W - 52, y_o2, "ОБЕ ЗАБЬЮТ", str(odds.get("btts") or "—"))

    if has_real:
        # Главная карточка распределения банка игроков
        draw.rounded_rectangle([(52, 254), (W - 52, 578)], radius=20, fill=CARD_BG, outline=EMERALD, width=2)
        p1_pct = int(sm_data.get("p1_pct", 50))
        x_pct = int(sm_data.get("x_pct", 20))
        p2_pct = max(0, 100 - p1_pct - x_pct)
        total_bets = int(sm_data.get("bets_count", 0))
        total_vol = int(sm_data.get("total_volume", 0))
        top_pick = _clean_text(sm_data.get("top_pick_label", "П1"))

        draw.text((80, 278), f"ВЫБОР БОЛЬШИНСТВА:  {top_pick}", font=f_big, fill=EMERALD)
        draw.text((80, 326), f"Купонов в игре: {total_bets}   •   Общий банк на матч: {_fmt_fc(total_vol)}", font=f_body, fill=TEXT_MUTED)

        # Пропорциональная полоса 3 исходов
        bar_x1, bar_x2 = 80, W - 80
        bar_y1, bar_y2 = 384, 434
        bar_w = bar_x2 - bar_x1
        w1 = max(20, int(bar_w * p1_pct / 100))
        wx = max(20, int(bar_w * x_pct / 100))
        w2 = max(20, bar_w - w1 - wx)

        draw.rounded_rectangle([(bar_x1, bar_y1), (bar_x1 + w1, bar_y2)], radius=10, fill=EMERALD)
        draw.rectangle([(bar_x1 + w1 + 4, bar_y1), (bar_x1 + w1 + wx - 4, bar_y2)], fill=GOLD)
        draw.rounded_rectangle([(bar_x1 + w1 + wx, bar_y1), (bar_x2, bar_y2)], radius=10, fill=BORDER_ICE)

        draw.text((bar_x1, 452), f"П1 ({_truncate(draw, match.get('home_team', ''), f_small, 220)}): {p1_pct}%", font=f_small, fill=EMERALD)
        x_txt = f"Ничья: {x_pct}%"
        draw.text(((bar_x1 + bar_x2) // 2 - draw.textlength(x_txt, font=f_small) / 2, 452), x_txt, font=f_small, fill=GOLD)
        p2_txt = f"П2 ({_truncate(draw, match.get('away_team', ''), f_small, 220)}): {p2_pct}%"
        draw.text((bar_x2 - draw.textlength(p2_txt, font=f_small), 452), p2_txt, font=f_small, fill=BORDER_ICE)

        xg = match.get("exp_goals", 2.6)
        sc = _clean_text(match.get("best_score", "2:1"))
        draw.text((80, 514), f"Модель Пуассона: ожидаемый счёт {sc} ({xg} xG)", font=f_body, fill=TEXT_MAIN)
    else:
        # ИИ-дуэль: 2 аналитика бок о бок
        battle = match.get("ai_battle") or {}
        prag = battle.get("pragmatist") or {"name": "Алгоритм xG (Прагматик)", "text": "Ставка на контроль темпа и математическое ожидание.", "pick_label": "1Х", "odds": odds.get("p1", 1.85)}
        rom = battle.get("romantic") or {"name": "Кураж-Скаут (Романтик)", "text": "Ждём открытый футбол и голы в обоих таймах.", "pick_label": "ТБ 2.5", "odds": odds.get("tb25", 1.95)}

        mid_x = W // 2
        # Левая карточка (Прагматик)
        draw.rounded_rectangle([(52, 254), (mid_x - 14, 578)], radius=20, fill=CARD_BG, outline=BORDER_ICE, width=2)
        draw.text((78, 276), _truncate(draw, prag.get("name", "Прагматик"), f_sub, 480), font=f_sub, fill=BORDER_ICE)
        for i, ln in enumerate(_wrap_lines(draw, prag.get("text", ""), f_body, 480, 4)):
            draw.text((78, 322 + i * 32), ln, font=f_body, fill=TEXT_MAIN)
        draw.rounded_rectangle([(78, 492), (mid_x - 40, 554)], radius=14, fill=(14, 72, 60), outline=EMERALD, width=2)
        p_lbl = f"{_clean_text(prag.get('pick_label', ''))}   •   КЭФ {prag.get('odds', '')}"
        draw.text((78 + ((mid_x - 118) - draw.textlength(p_lbl, font=f_sub)) / 2, 510), p_lbl, font=f_sub, fill=EMERALD)

        # Правая карточка (Романтик)
        draw.rounded_rectangle([(mid_x + 14, 254), (W - 52, 578)], radius=20, fill=CARD_BG, outline=GOLD, width=2)
        draw.text((mid_x + 40, 276), _truncate(draw, rom.get("name", "Романтик"), f_sub, 480), font=f_sub, fill=GOLD)
        for i, ln in enumerate(_wrap_lines(draw, rom.get("text", ""), f_body, 480, 4)):
            draw.text((mid_x + 40, 322 + i * 32), ln, font=f_body, fill=TEXT_MAIN)
        draw.rounded_rectangle([(mid_x + 40, 492), (W - 78, 554)], radius=14, fill=(84, 54, 12), outline=GOLD, width=2)
        r_lbl = f"{_clean_text(rom.get('pick_label', ''))}   •   КЭФ {rom.get('odds', '')}"
        draw.text((mid_x + 40 + ((W - mid_x - 118) - draw.textlength(r_lbl, font=f_sub)) / 2, 510), r_lbl, font=f_sub, fill=GOLD)

    _draw_footer(draw, right_note="ЗАГРУЗИТЬ ПРОГНОЗ В КУПОН В 1 КЛИК ->")
    return _to_png_bytes(img)


# ==================== 3. АЛЕРТ ЧЁРНОГО РЫНКА (ЛЕГЕНДА 98–99 OVR) ====================
def render_black_market_card(bm_data: dict) -> bytes:
    img, draw = _create_base_canvas(accent_rgb=GOLD)
    card = bm_data.get("card") or {}
    ovr = int(card.get("ovr") or 99)
    role = _clean_text(card.get("role", "FW"))
    name = _clean_text(card.get("name", "Легенда GOAT"))
    club = _clean_text(card.get("club", "Легенда"))
    desc = _clean_text(card.get("desc", "+25% к прибыли"))
    bid = int(bm_data.get("highest_bid") or 25000)
    leader = _clean_text(bm_data.get("leader_name") or "Нет ставок")

    _draw_header(
        draw,
        badge_text="ЧЁРНЫЙ РЫНОК • ЭКСКЛЮЗИВНЫЙ АУКЦИОН",
        title_text="НОВЫЙ ЛОТ GOAT НА ТОРГАХ",
        right_text="АНТИ-СНАЙПИНГ +2 МИН",
        badge_color=GOLD,
    )

    # Левый щит карточки GOAT
    sx1, sy1, sx2, sy2 = 64, 168, 396, 566
    draw.rounded_rectangle([(sx1, sy1), (sx2, sy2)], radius=28, fill=(58, 28, 72), outline=GOLD, width=4)
    draw.rounded_rectangle([(sx1 + 10, sy1 + 10), (sx2 - 10, sy2 - 10)], radius=22, outline=(254, 240, 138), width=1)

    f_ovr = _load_font(78, bold=True)
    f_role = _load_font(28, bold=True)
    f_club = _load_font(22, bold=True)
    f_cname = _load_font(28, bold=True)
    f_big_title = _load_font(40, bold=True)
    f_val = _load_font(34, bold=True)
    f_lbl = _load_font(20, bold=False)

    draw.text((sx1 + 32, sy1 + 26), str(ovr), font=f_ovr, fill=GOLD)
    draw.text((sx1 + 38, sy1 + 112), role, font=f_role, fill=TEXT_MAIN)

    draw.rounded_rectangle([(sx1 + 170, sy1 + 38), (sx2 - 26, sy1 + 80)], radius=12, fill=GOLD)
    draw.text((sx1 + 194, sy1 + 46), "GOAT", font=_load_font(22, bold=True), fill=TEXT_DARK)

    # Имя и клуб внутри щита
    draw.rounded_rectangle([(sx1 + 24, sy1 + 204), (sx2 - 24, sy1 + 246)], radius=10, fill=(24, 16, 40))
    cl_tr = _truncate(draw, club.upper(), f_club, 260)
    draw.text((sx1 + (332 - draw.textlength(cl_tr, font=f_club)) / 2, sy1 + 212), cl_tr, font=f_club, fill=BORDER_ICE)

    for i, ln in enumerate(_wrap_lines(draw, name, f_cname, 280, 2)):
        draw.text((sx1 + (332 - draw.textlength(ln, font=f_cname)) / 2, sy1 + 268 + i * 36), ln, font=f_cname, fill=TEXT_MAIN)

    # Правая информационная панель
    px1, py1, px2, py2 = 434, 168, W - 52, 566
    draw.rounded_rectangle([(px1, py1), (px2, py2)], radius=22, fill=CARD_BG, outline=BORDER_SOFT, width=2)

    draw.text((px1 + 32, py1 + 28), _truncate(draw, name, f_big_title, px2 - px1 - 64), font=f_big_title, fill=TEXT_MAIN)
    draw.text((px1 + 32, py1 + 86), f"Позиция: {role}   •   Клуб: {club}   •   Рейтинг: {ovr} OVR", font=f_lbl, fill=TEXT_MUTED)

    draw.rounded_rectangle([(px1 + 32, py1 + 132), (px2 - 32, py1 + 196)], radius=14, fill=(14, 72, 60), outline=EMERALD, width=2)
    draw.text((px1 + 52, py1 + 150), _truncate(draw, f"БОНУС КАРТЫ: {desc}", _load_font(23, bold=True), px2 - px1 - 100), font=_load_font(23, bold=True), fill=EMERALD)

    draw.rounded_rectangle([(px1 + 32, py1 + 220), (px2 - 32, py1 + 356)], radius=16, fill=CARD_DARK, outline=GOLD, width=2)
    draw.text((px1 + 54, py1 + 236), "ТЕКУЩАЯ СТАВКА НА ЛОТ:", font=_load_font(18, bold=True), fill=TEXT_MUTED)
    draw.text((px1 + 54, py1 + 266), _fmt_fc(bid), font=f_val, fill=GOLD)
    draw.text((px1 + 54, py1 + 314), f"Лидер торгов: {_truncate(draw, leader, _load_font(20, bold=True), 460)}", font=_load_font(20, bold=True), fill=BORDER_ICE)

    _draw_footer(draw, right_note="ПЕРЕБИТЬ СТАВКУ НА ЧЁРНОМ РЫНКЕ ->")
    return _to_png_bytes(img)


# ==================== 4. ГЛАВНЫЙ ЗАНОС ДНЯ И ИТОГИ ТУРНИРА ====================
def render_big_win_card(win_data: dict) -> bytes:
    img, draw = _create_base_canvas(accent_rgb=EMERALD)
    _draw_header(
        draw,
        badge_text="ГЛАВНЫЙ ЗАНОС ДНЯ",
        title_text=f"ПОБЕДНЫЙ КУПОН #{win_data.get('bet_id', '')}",
        right_text=win_data.get("date_label", ""),
        badge_color=EMERALD,
    )

    f_user = _load_font(34, bold=True)
    f_big = _load_font(44, bold=True)
    f_lbl = _load_font(18, bold=True)
    f_leg = _load_font(20, bold=False)

    draw.rounded_rectangle([(52, 158), (W - 52, 332)], radius=20, fill=CARD_BG, outline=EMERALD, width=2)
    uname = _truncate(draw, win_data.get("username", "Каппер"), f_user, 560)
    draw.text((82, 182), f"КАППЕР: {uname}", font=f_user, fill=TEXT_MAIN)

    draw.text((82, 240), "СТАВКА", font=f_lbl, fill=TEXT_MUTED)
    draw.text((82, 266), _fmt_fc(win_data.get("amount", 0)), font=_load_font(30, bold=True), fill=TEXT_MAIN)

    draw.text((400, 240), "КОЭФФИЦИЕНТ", font=f_lbl, fill=TEXT_MUTED)
    draw.text((400, 266), f"x{win_data.get('odds', 1.0)}", font=_load_font(30, bold=True), fill=BORDER_ICE)

    draw.text((730, 232), "ВЫПЛАТА", font=f_lbl, fill=EMERALD)
    draw.text((730, 256), f"+{_fmt_fc(win_data.get('payout', 0))}", font=f_big, fill=GOLD)

    # Список исходов купона
    draw.rounded_rectangle([(52, 354), (W - 52, 578)], radius=18, fill=CARD_DARK, outline=BORDER_SOFT, width=2)
    draw.text((80, 372), "СОБЫТИЯ В КУПОНЕ:", font=f_lbl, fill=BORDER_ICE)
    legs = (win_data.get("legs") or [])[:5]
    if not legs:
        legs = [{"teams": win_data.get("match_title", "Матч"), "pick_label": win_data.get("pick", ""), "odds": win_data.get("odds", 1.0)}]
    for i, lg in enumerate(legs):
        line_txt = f"{i + 1}. {_clean_text(lg.get('teams', ''))}  —  {_clean_text(lg.get('pick_label', ''))} (кэф {lg.get('odds', '')})"
        draw.text((80, 408 + i * 32), _truncate(draw, line_txt, f_leg, W - 160), font=f_leg, fill=TEXT_MAIN)

    _draw_footer(draw, right_note="ПОПРОБУЙ ПОБИТЬ РЕКОРД В AI_BET_BOT ->")
    return _to_png_bytes(img)


def render_tourney_card(tourney_data: dict) -> bytes:
    img, draw = _create_base_canvas(accent_rgb=GOLD)
    pool = int(tourney_data.get("prize_pool") or 60000)
    _draw_header(
        draw,
        badge_text="ЕЖЕНЕДЕЛЬНЫЙ КУБОК КАППЕРОВ",
        title_text=f"ИТОГИ НЕДЕЛИ • ФОНД {_fmt_fc(pool)}",
        right_text=tourney_data.get("date_label", ""),
        badge_color=GOLD,
    )

    f_place = _load_font(30, bold=True)
    f_name = _load_font(28, bold=True)
    f_pts = _load_font(24, bold=True)
    f_sub = _load_font(18, bold=False)

    leaders = (tourney_data.get("leaders") or [])[:3]
    colors = [GOLD, (203, 213, 225), (217, 155, 82)]
    y_start = 166
    row_h = 122

    for idx, ld in enumerate(leaders):
        y1 = y_start + idx * (row_h + 18)
        y2 = y1 + row_h
        c = colors[idx]
        draw.rounded_rectangle([(52, y1), (W - 52, y2)], radius=18, fill=CARD_BG, outline=c, width=3 if idx == 0 else 2)
        draw.rounded_rectangle([(74, y1 + 26), (144, y2 - 26)], radius=14, fill=c)
        p_txt = f"#{idx + 1}"
        draw.text((109 - draw.textlength(p_txt, font=f_place) / 2, y1 + 42), p_txt, font=f_place, fill=TEXT_DARK)

        draw.text((170, y1 + 26), _truncate(draw, ld.get("name", "Каппер"), f_name, 520), font=f_name, fill=TEXT_MAIN)
        draw.text((170, y1 + 70), f"Очки турнира: {ld.get('pts', 0)} PTS   •   Побед: {ld.get('wins', 0)}", font=f_sub, fill=TEXT_MUTED)

        prize_txt = f"+{_fmt_fc(ld.get('prize', 0))}"
        pw = draw.textlength(prize_txt, font=f_pts)
        draw.text((W - 80 - pw, y1 + 44), prize_txt, font=f_pts, fill=EMERALD)

    _draw_footer(draw, right_note="НОВЫЙ ТУР И СУПЕРЭКСПРЕСС УЖЕ ОТКРЫТЫ ->")
    return _to_png_bytes(img)
