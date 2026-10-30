import random
from typing import Dict, Any, Tuple

# Классы персонажей
CLASSES = {
    "swordsman": {
        "name": "Мечник",
        "title": "Ветеран-наёмник",
        "desc": "Закаленный в битвах солдат. Высокая стойкость и физическая мощь.",
        "hp": 100,
        "sanity": 65,
        "gold": 12,
        "str": 2,
        "agi": 0,
        "int": -1,
        "items": ["Стальной меч", "Кожаный доспех", "Фляга с элем", "Факел"]
    },
    "medicus": {
        "name": "Лекарь",
        "title": "Опальный алхимик",
        "desc": "Знаток трав, ядов и анатомии. Высокий рассудок и наблюдательность.",
        "hp": 75,
        "sanity": 90,
        "gold": 20,
        "str": -1,
        "agi": 0,
        "int": 2,
        "items": ["Чумная маска", "Острый скальпель", "Настойка мака", "Бинты (3 шт.)"]
    },
    "cutpurse": {
        "name": "Бродяга",
        "title": "Ночной вор",
        "desc": "Ловкий и скрытный выживальщик из трущоб. Умеет взламывать и прятаться.",
        "hp": 85,
        "sanity": 75,
        "gold": 25,
        "str": 0,
        "agi": 2,
        "int": 1,
        "items": ["Охотничий кинжал", "Набор отмычек", "Кости для игры", "Веревка с крюком"]
    }
}

def render_progress_bar(value: int, max_value: int, length: int = 5, filled_char: str = "🟩", empty_char: str = "⬜") -> str:
    """Генерация визуальной полоски прогресса"""
    val = max(0, min(value, max_value))
    filled = int(round((val / max_value) * length))
    return (filled_char * filled) + (empty_char * (length - filled))

def format_status_header(player: Dict[str, Any], items_count: int) -> str:
    """Форматирование верхней шапки состояния игрока"""
    hp_bar = render_progress_bar(player["hp"], 100, length=5, filled_char="🟩", empty_char="⬜")
    sanity_bar = render_progress_bar(player["sanity"], 100, length=5, filled_char="🟦", empty_char="⬛")

    loc = player.get("location", "Вересковые пустоши")
    turn = player.get("turn_count", 1)

    return (
        f"📍 <b>{loc}</b> • <i>Ход {turn}</i>\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 {hp_bar}\n"
        f"🧠 <b>Рассудок:</b> {player['sanity']}/100 {sanity_bar}\n"
        f"🪙 <b>Монеты:</b> {player['gold']}  |  🎒 <b>Предметы:</b> {items_count}/8\n"
        f"────────────────────\n"
    )

def roll_dice_for_action(action_text: str, player: Dict[str, Any]) -> Tuple[int, int, str]:
    """
    Бросок кубика d20 с учетом характеристик персонажа.
    Возвращает (чистый_бросок, итоговый_результат, вердикт).
    """
    raw_roll = random.randint(1, 20)

    # Определяем модификатор по ключевым словам
    text_lower = action_text.lower()
    mod = 0
    stat_name = "Удача"

    if any(w in text_lower for w in ["удар", "меч", "выбить", "сила", "драка", "рубить", "сломать", "держать"]):
        mod = player.get("str_stat", 0)
        stat_name = "Сила"
    elif any(w in text_lower for w in ["тихо", "красться", "отмыч", "бег", "увернуться", "ловк", "прыгнуть", "спрятаться"]):
        mod = player.get("agi_stat", 0)
        stat_name = "Ловкость"
    elif any(w in text_lower for w in ["осмотр", "леч", "трав", "книга", "понять", "вспомнить", "зелье", "распознать"]):
        mod = player.get("int_stat", 0)
        stat_name = "Интеллект"

    total = raw_roll + mod

    if raw_roll == 1:
        verdict = f"🎲 <b>Критический провал!</b> (выпало 1 на d20)"
    elif raw_roll == 20:
        verdict = f"🎲 <b>Критический успех!</b> (чистая 20 на d20 + {stat_name}: {mod:+d})"
    elif total >= 15:
        verdict = f"🎲 <b>Полный успех!</b> (d20: {raw_roll} + {stat_name}: {mod:+d} = {total})"
    elif total >= 10:
        verdict = f"🎲 <b>Частичный успех с ценой</b> (d20: {raw_roll} + {stat_name}: {mod:+d} = {total})"
    else:
        verdict = f"🎲 <b>Неудача</b> (d20: {raw_roll} + {stat_name}: {mod:+d} = {total})"

    return raw_roll, total, verdict
