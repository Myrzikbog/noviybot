import random
import html
from typing import Dict, Any, Tuple, Optional, List

# Сбалансированные классы персонажей
CLASSES = {
    "swordsman": {
        "name": "Мечник",
        "title": "Ветеран-наёмник",
        "desc": "Закаленный в битвах солдат. Высокая стойкость и физическая мощь.",
        "hp": 100,
        "sanity": 60,
        "gold": 15,
        "str": 2,
        "agi": 0,
        "int": 0,
        "items": ["Стальной меч", "Кожаный доспех", "Фляга с брагой", "Факел"]
    },
    "medicus": {
        "name": "Лекарь",
        "title": "Опальный алхимик",
        "desc": "Знаток трав, ядов и анатомии. Высокий рассудок и наблюдательность.",
        "hp": 75,
        "sanity": 90,
        "gold": 20,
        "str": -1,
        "agi": 1,
        "int": 2,
        "items": ["Чумная маска", "Острый скальпель", "Настойка мака", "Бинты (3 шт.)"]
    },
    "cutpurse": {
        "name": "Бродяга",
        "title": "Ночной вор",
        "desc": "Ловкий и скрытный выживальщик из трущоб. Умеет взламывать и прятаться.",
        "hp": 85,
        "sanity": 75,
        "gold": 20,
        "str": 0,
        "agi": 2,
        "int": 0,
        "items": ["Охотничий кинжал", "Набор отмычек", "Кости для игры", "Веревка с крюком"]
    }
}

# Предыстории героя (Грехи, тайны и сюжетная цель)
BACKGROUNDS = {
    "heretic": {
        "id": "heretic",
        "title": "🕯️ Беглый еретик",
        "subtitle": "Отвергнутый церковью",
        "desc": "Вы чудом вырвались из застенков Священного трибунала. За вами идут псы инквизиции.",
        "quest": "Найти убежище в вольных северных землях и очистить имя от клейма ереси.",
        "bonus_stat": "int",
        "bonus_item": "Тайный манускрипт"
    },
    "plague_marked": {
        "id": "plague_marked",
        "title": "🩸 Отмеченный мором",
        "subtitle": "Носитель древнего штамма",
        "desc": "Черные язвы покрыли вашу кожу, но вы не погибли. Моровая лихорадка дарует жуткие видения.",
        "quest": "Отыскать Обитель Святого Вольфганга и раскрыть секрет своего иммунитета до того, как болезнь победит разум.",
        "bonus_stat": "agi",
        "bonus_item": "Амулет из полыни"
    },
    "mercenary_revenge": {
        "id": "mercenary_revenge",
        "title": "⚔️ Месть «Черных Воронов»",
        "subtitle": "Последний из отряда",
        "desc": "Ваш отряд предали свои же и вырезали до единого. Вы выжили под грудой мертвых тел.",
        "quest": "Выследить предателя-капитана Вальтера и воздать ему кровью за павших братьев по оружию.",
        "bonus_stat": "str",
        "bonus_item": "Железный жетон наемника"
    },
    "disgraced_noble": {
        "id": "disgraced_noble",
        "title": "🗝️ Опальный дворянин",
        "subtitle": "Наследник пепелища",
        "desc": "Родовой замок сожжен жадными баронами, семья в земле. У вас остался лишь перстень и клятва чести.",
        "quest": "Собрать силу, верных соратников и вырвать родовой надел из лап узурпатора.",
        "bonus_stat": "int",
        "bonus_item": "Фамильный перстень с печатью"
    }
}

# Свойства экипировки
EQUIPMENT_DATA = {
    "Стальной меч": {"type": "weapon", "dmg_bonus": 8, "desc": "+8 к урону в ближнем бою"},
    "Охотничий кинжал": {"type": "weapon", "dmg_bonus": 6, "desc": "+6 к урону, скрытность"},
    "Острый скальпель": {"type": "weapon", "dmg_bonus": 5, "desc": "+5 к урону по уязвимым точкам"},
    "Кожаный доспех": {"type": "armor", "dmg_reduction": 4, "desc": "Снижает входящий физический урон на 4"},
    "Чумная маска": {"type": "trinket", "sanity_protection": 5, "desc": "Фильтрует тлетворный воздух, защищая рассудок"},
    "Тайный манускрипт": {"type": "trinket", "desc": "Древние знания трав, ядов и оккультных знаков"},
    "Амулет из полыни": {"type": "trinket", "desc": "Отгоняет морок и притупляет боль"},
    "Железный жетон наемника": {"type": "trinket", "desc": "Символ братства наемников, внушает уважение воинам"},
    "Фамильный перстень с печатью": {"type": "trinket", "desc": "Знак благородного происхождения в беседах с лордами"}
}

# Каталог лавки торговца
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
        "desc": "+25 к рассудку (отгоняет морок)",
        "heal_hp": 0,
        "heal_san": 25
    },
    "bandages": {
        "name": "Льняные бинты (x2)",
        "cost": 6,
        "desc": "Останавливают кровь (+15 HP, +5 Sanity)",
        "heal_hp": 15,
        "heal_san": 5
    },
    "lockpick": {
        "name": "Воровская отмычка",
        "cost": 8,
        "desc": "Позволяет открывать сундуки и тайники",
        "heal_hp": 0,
        "heal_san": 0
    },
    "torch": {
        "name": "Смоляной факел",
        "cost": 4,
        "desc": "Освещает катакомбы и отпугивает тварей",
        "heal_hp": 0,
        "heal_san": 0
    },
    "elixir": {
        "name": "Эликсир алхимика",
        "cost": 15,
        "desc": "Восстановление: +40 HP и +40 Рассудка",
        "heal_hp": 40,
        "heal_san": 40
    }
}

# Расходуемые предметы
CONSUMABLE_EFFECTS = {
    "Хлеб и копченое сало": {"heal_hp": 25, "heal_san": 0, "btn": "🍞 Съесть (+25 HP)"},
    "Успокаивающая настойка полыни": {"heal_hp": 0, "heal_san": 25, "btn": "🧪 Выпить (+25 Sanity)"},
    "Настойка мака": {"heal_hp": 10, "heal_san": 20, "btn": "🧪 Выпить (+10 HP, +20 Sanity)"},
    "Льняные бинты (x2)": {"heal_hp": 15, "heal_san": 5, "btn": "🩹 Перевязать (+15 HP)"},
    "Бинты (3 шт.)": {"heal_hp": 15, "heal_san": 5, "btn": "🩹 Перевязать (+15 HP)"},
    "Эликсир алхимика": {"heal_hp": 40, "heal_san": 40, "btn": "✨ Осушить эликсир (+40 HP & San)"},
    "Фляга с брагой": {"heal_hp": 5, "heal_san": 15, "btn": "🍺 Глотнуть браги (+15 Sanity)"}
}

def render_progress_bar(value: int, max_value: int, length: int = 5, filled_char: str = "🟩", empty_char: str = "░") -> str:
    """Генерация визуальной полоски прогресса с единообразным фоном ░"""
    if max_value <= 0:
        return empty_char * length
    val = max(0, min(value, max_value))
    filled = int(round((val / max_value) * length))
    return (filled_char * filled) + (empty_char * (length - filled))

def get_affinity_status(affinity: int) -> Tuple[str, str, str]:
    """Возвращает статус отношений, иконку и цветную полоску"""
    if affinity >= 85:
        return "❤️ Близкая душа (Любовь / Преданность)", "❤️", render_progress_bar(affinity, 100, length=5, filled_char="🟪")
    elif affinity >= 65:
        return "🛡️ Верный товарищ", "🛡️", render_progress_bar(affinity, 100, length=5, filled_char="🟩")
    elif affinity >= 45:
        return "🤝 Попутчик", "🤝", render_progress_bar(affinity, 100, length=5, filled_char="🟦")
    elif affinity >= 25:
        return "❄️ Недоверие", "❄️", render_progress_bar(affinity, 100, length=5, filled_char="🟨")
    else:
        return "💔 Вражда и презрение", "💔", render_progress_bar(affinity, 100, length=5, filled_char="🟥")

def format_status_header(player: Dict[str, Any], items_count: int, active_companion: Optional[Dict[str, Any]] = None) -> str:
    """Форматирование расширенной шапки со статусом героя, квестом и спутником"""
    hp_bar = render_progress_bar(player["hp"], 100, length=5, filled_char="🟩", empty_char="░")
    sanity_bar = render_progress_bar(player["sanity"], 100, length=5, filled_char="🟦", empty_char="░")

    loc = html.escape(str(player.get("location") or "Вересковые пустоши"))
    turn = player.get("turn_count", 1)
    lvl = player.get("level", 1)
    xp = player.get("xp", 0)
    needed_xp = lvl * 150 + 50

    stat_points = player.get("stat_points", 0)
    lvl_badge = f"⭐ <b>Ур. {lvl}</b> [{xp}/{needed_xp} XP]"
    if stat_points > 0:
        lvl_badge += f" (⚡ <b>+{stat_points} очко!</b>)"

    # Основная информация
    header = (
        f"📍 <b>{loc}</b> • <i>День {turn}</i> ({lvl_badge})\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 {hp_bar}\n"
        f"🧠 <b>Рассудок:</b> {player['sanity']}/100 {sanity_bar}\n"
        f"🪙 <b>Монеты:</b> {player['gold']}  |  🎒 <b>Сумка:</b> {items_count}/8\n"
    )

    # Отображение активного спутника
    if active_companion:
        comp_name = html.escape(active_companion["name"])
        comp_title = html.escape(active_companion.get("title", "Спутник"))
        status_text, icon, aff_bar = get_affinity_status(active_companion.get("affinity", 50))
        header += f"👥 <b>Спутник:</b> {comp_name} ({comp_title}) • {icon} <i>{status_text}</i> [{active_companion.get('affinity', 50)}%] {aff_bar}\n"

    # Главный квест (сюжетная цель)
    main_quest = player.get("main_quest")
    if main_quest:
        quest_short = html.escape(main_quest[:75] + ("..." if len(main_quest) > 75 else ""))
        header += f"🎯 <b>Цель:</b> <i>{quest_short}</i>\n"

    # Если идёт бой с врагом/боссом
    enemy_name = player.get("enemy_name")
    enemy_hp = player.get("enemy_hp", 0)
    enemy_max = player.get("enemy_max_hp", 0)

    if enemy_name and enemy_hp > 0 and enemy_max > 0:
        enemy_safe_name = html.escape(str(enemy_name))
        enemy_bar = render_progress_bar(enemy_hp, enemy_max, length=6, filled_char="🟥", empty_char="░")
        header += f"⚔️ <b>ВРАГ: {enemy_safe_name}</b> {enemy_bar} ({enemy_hp}/{enemy_max} HP)\n"

    header += "────────────────────\n"
    return header

def roll_dice_for_action(action_text: str, player: Dict[str, Any], stat_hint: Optional[str] = None) -> Tuple[int, int, str]:
    """
    Бросок кубика d20 с учетом стата (Сила, Ловкость, Интеллект, Красноречие или Удача).
    Решает проблему обнуления характеристик: stat_hint передается напрямую из выбора нейросети!
    """
    raw_roll = random.randint(1, 20)
    mod = 0
    stat_name = "Удача"

    # 1. Прямой учет характеристики от нейросети
    if stat_hint == "str":
        mod = player.get("str_stat", 0)
        stat_name = "Сила"
    elif stat_hint == "agi":
        mod = player.get("agi_stat", 0)
        stat_name = "Ловкость"
    elif stat_hint == "int":
        mod = player.get("int_stat", 0)
        stat_name = "Интеллект"
    elif stat_hint == "speech":
        # Красноречие базируется на интеллекте + харизме
        mod = player.get("int_stat", 0)
        stat_name = "Красноречие"
    elif stat_hint == "luck":
        mod = 0
        stat_name = "Удача"
    else:
        # Семантический поиск по ключевым словам (для рукописных действий)
        text_lower = action_text.lower()
        if any(w in text_lower for w in ["удар", "меч", "выбить", "сила", "драка", "рубить", "сломать", "парир", "атака", "щит", "кулак", "топор"]):
            mod = player.get("str_stat", 0)
            stat_name = "Сила"
        elif any(w in text_lower for w in ["тихо", "красться", "отмыч", "бег", "увернуться", "ловк", "прыгнуть", "спрятаться", "финт", "выстрел", "лук", "арбалет", "кинжал"]):
            mod = player.get("agi_stat", 0)
            stat_name = "Ловкость"
        elif any(w in text_lower for w in ["осмотр", "леч", "трав", "книга", "понять", "вспомнить", "зелье", "распознать", "оценить", "яд", "анатом", "магия", "руны"]):
            mod = player.get("int_stat", 0)
            stat_name = "Интеллект"
        elif any(w in text_lower for w in ["сказать", "спросить", "убедить", "предложить", "солгать", "договориться", "флирт", "речь", "голос", "шепнуть"]):
            mod = player.get("int_stat", 0)
            stat_name = "Красноречие"

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
