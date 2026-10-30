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

# Каталог лавки придорожного торговца
SHOP_ITEMS = {
    "bread": {
        "name": "Хлеб и копченое сало",
        "cost": 5,
        "desc": "+25 к здоровью (сытный привал)",
        "heal_hp": 25,
        "heal_san": 0
    },
    "tincture": {
        "name": "Успокаивающая настойка полыни",
        "cost": 7,
        "desc": "+25 к рассудку (отгоняет дурные видения)",
        "heal_hp": 0,
        "heal_san": 25
    },
    "bandages": {
        "name": "Льняные бинты (x2)",
        "cost": 6,
        "desc": "Останавливают кровь и спасают от гангрены",
        "heal_hp": 15,
        "heal_san": 5
    },
    "lockpick": {
        "name": "Воровская отмычка",
        "cost": 8,
        "desc": "Позволяет взламывать замки сундуков и дверей",
        "heal_hp": 0,
        "heal_san": 0
    },
    "torch": {
        "name": "Смоляной факел",
        "cost": 4,
        "desc": "Освещает тьму и отпугивает диких тварей",
        "heal_hp": 0,
        "heal_san": 0
    },
    "elixir": {
        "name": "Эликсир алхимика",
        "cost": 15,
        "desc": "Полное восстановление: +40 HP и +40 Рассудка",
        "heal_hp": 40,
        "heal_san": 40
    }
}

def render_progress_bar(value: int, max_value: int, length: int = 5, filled_char: str = "🟩", empty_char: str = "⬜") -> str:
    """Генерация визуальной полоски прогресса"""
    if max_value <= 0:
        return empty_char * length
    val = max(0, min(value, max_value))
    filled = int(round((val / max_value) * length))
    return (filled_char * filled) + (empty_char * (length - filled))

def format_status_header(player: Dict[str, Any], items_count: int) -> str:
    """Форматирование верхней шапки состояния игрока с учетом уровня, XP и боя с боссом"""
    hp_bar = render_progress_bar(player["hp"], 100, length=5, filled_char="🟩", empty_char="⬜")
    sanity_bar = render_progress_bar(player["sanity"], 100, length=5, filled_char="🟦", empty_char="⬛")

    loc = player.get("location", "Вересковые пустоши")
    turn = player.get("turn_count", 1)
    lvl = player.get("level", 1)
    xp = player.get("xp", 0)
    needed_xp = lvl * 100

    header = (
        f"📍 <b>{loc}</b> • <i>Ход {turn}</i> (⭐ <b>Ур. {lvl}</b> [{xp}/{needed_xp} XP])\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 {hp_bar}\n"
        f"🧠 <b>Рассудок:</b> {player['sanity']}/100 {sanity_bar}\n"
        f"🪙 <b>Монеты:</b> {player['gold']}  |  🎒 <b>Предметы:</b> {items_count}/8\n"
    )

    # Если идёт бой с боссом или чудовищем
    enemy_name = player.get("enemy_name")
    enemy_hp = player.get("enemy_hp", 0)
    enemy_max = player.get("enemy_max_hp", 0)

    if enemy_name and enemy_hp > 0 and enemy_max > 0:
        enemy_bar = render_progress_bar(enemy_hp, enemy_max, length=6, filled_char="🟥", empty_char="⬛")
        header += f"⚔️ <b>ВРАГ: {enemy_name}</b> {enemy_bar} ({enemy_hp}/{enemy_max} HP)\n"

    header += "────────────────────\n"
    return header

def roll_dice_for_action(action_text: str, player: Dict[str, Any]) -> Tuple[int, int, str]:
    """
    Бросок кубика d20 с учетом характеристик персонажа.
    Возвращает (чистый_бросок, итоговый_результат, вердикт).
    """
    raw_roll = random.randint(1, 20)

    text_lower = action_text.lower()
    mod = 0
    stat_name = "Удача"

    if any(w in text_lower for w in ["удар", "меч", "выбить", "сила", "драка", "рубить", "сломать", "держать", "парир"]):
        mod = player.get("str_stat", 0)
        stat_name = "Сила"
    elif any(w in text_lower for w in ["тихо", "красться", "отмыч", "бег", "увернуться", "ловк", "прыгнуть", "спрятаться", "финт"]):
        mod = player.get("agi_stat", 0)
        stat_name = "Ловкость"
    elif any(w in text_lower for w in ["осмотр", "леч", "трав", "книга", "понять", "вспомнить", "зелье", "распознать", "оценить"]):
        mod = player.get("int_stat", 0)
        stat_name = "Интеллект"

    total = raw_roll + mod

    if raw_roll == 1:
        verdict = f"🎲 <b>Критический провал!</b> (выпало 1 на d20)"
    elif raw_roll == 20:
        verdict = f"🎲 <b>Критический триумф!</b> (чистая 20 на d20 + {stat_name}: {mod:+d})"
    elif total >= 15:
        verdict = f"🎲 <b>Полный успех!</b> (d20: {raw_roll} + {stat_name}: {mod:+d} = {total})"
    elif total >= 10:
        verdict = f"🎲 <b>Частичный успех с ценой</b> (d20: {raw_roll} + {stat_name}: {mod:+d} = {total})"
    else:
        verdict = f"🎲 <b>Неудача</b> (d20: {raw_roll} + {stat_name}: {mod:+d} = {total})"

    return raw_roll, total, verdict
