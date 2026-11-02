from typing import List, Dict, Any, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import game_logic as gl

def get_class_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора класса с характеристиками"""
    keyboard = [
        [InlineKeyboardButton(text="⚔️ Мечник (СИЛ +2 | HP 100 | 15 🪙)", callback_data="class:swordsman")],
        [InlineKeyboardButton(text="🧪 Лекарь (ИНТ +2, ЛОВ +1 | San 90 | 20 🪙)", callback_data="class:medicus")],
        [InlineKeyboardButton(text="🗡️ Бродяга (ЛОВ +2 | HP 85 | 20 🪙)", callback_data="class:cutpurse")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_background_selection_keyboard(class_key: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора предыстории и личной тайны персонажа"""
    keyboard = []
    for bg_id, bg_info in gl.BACKGROUNDS.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{bg_info['title']} ({bg_info['subtitle']})",
                callback_data=f"bg:{class_key}:{bg_id}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="◀️ Назад к выбору класса", callback_data="back_to_class_select")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_game_turn_keyboard(
    choices: List[str],
    choice_stats: List[str] = None,
    is_in_combat: bool = False,
    has_companion: bool = False
) -> InlineKeyboardMarkup:
    """Эргономичная клавиатура игрового хода с понятными метками характеристик"""
    keyboard = []

    stat_icons = {
        "str": "⚔️ [Сила]",
        "agi": "🦶 [Ловкость]",
        "int": "🧠 [Интеллект]",
        "speech": "💬 [Слово]",
        "insanity": "👁️ [Безумие]",
        "luck": "👉 [Удача]"
    }

    # Кнопки с готовыми вариантами от Gemini
    for i, choice in enumerate(choices):
        hint = choice_stats[i] if choice_stats and i < len(choice_stats) else "luck"
        prefix = stat_icons.get(hint, "👉")
        button_text = choice if len(choice) <= 34 else choice[:31] + "..."
        keyboard.append([InlineKeyboardButton(text=f"{prefix} {button_text}", callback_data=f"choice:{i}")])

    # Кнопка свободного действия или речи
    keyboard.append([
        InlineKeyboardButton(text="✍️ Своё действие / 🗣️ Сказать персонажу", callback_data="custom_action")
    ])

    # Компактная сервисная строка управления
    if is_in_combat:
        management_row = [
            InlineKeyboardButton(text="🎒 Рюкзак", callback_data="show_inventory"),
            InlineKeyboardButton(text="👥 Спутники", callback_data="show_companions"),
            InlineKeyboardButton(text="🏃 Отступить", callback_data="choice:retreat"),
            InlineKeyboardButton(text="⚙️ Меню", callback_data="show_main_menu")
        ]
    else:
        management_row = [
            InlineKeyboardButton(text="🎒 Рюкзак", callback_data="show_inventory"),
            InlineKeyboardButton(text="👥 Спутники", callback_data="show_companions"),
            InlineKeyboardButton(text="⛺ Привал", callback_data="show_camp"),
            InlineKeyboardButton(text="⚙️ Меню", callback_data="show_main_menu")
        ]
    keyboard.append(management_row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_companions_keyboard(companions: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список спутников героя"""
    keyboard = []
    for c in companions:
        name = c["name"]
        status_text, icon, _ = gl.get_affinity_status(c.get("affinity", 50))
        btn_text = f"{icon} {name} ({c.get('title', 'Спутник')}) — {c.get('affinity', 50)}%"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"companion:{c['id']}")])

    keyboard.append([
        InlineKeyboardButton(text="◀️ Вернуться к приключению", callback_data="back_to_game")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_companion_detail_keyboard(companion_id: int) -> InlineKeyboardMarkup:
    """Меню взаимодействия с конкретным спутником"""
    keyboard = [
        [InlineKeyboardButton(text="💬 Поговорить по душам", callback_data=f"comp_talk:{companion_id}")],
        [InlineKeyboardButton(text="🎁 Угостить пайком / припасами (+Симпатия)", callback_data=f"comp_gift:{companion_id}")],
        [InlineKeyboardButton(text="◀️ Назад к спутникам", callback_data="show_companions")],
        [InlineKeyboardButton(text="🛡️ Вернуться в игру", callback_data="back_to_game")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_camp_keyboard(has_companion: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура лагеря / привала"""
    keyboard = [
        [InlineKeyboardButton(text="🔥 Развести костер и перевязать раны (+20 HP, +15 Sanity)", callback_data="camp_rest")],
        [InlineKeyboardButton(text="🎒 Проверить рюкзак и припасы", callback_data="show_inventory")]
    ]
    if has_companion:
        keyboard.append([
            InlineKeyboardButton(text="💬 Побеседовать со спутником у огня", callback_data="show_companions")
        ])
    keyboard.append([
        InlineKeyboardButton(text="◀️ Снять лагерь и продолжить путь", callback_data="back_to_game")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_inventory_keyboard(inventory_items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Интерактивный инвентарь с применением расходников"""
    keyboard = []
    for item in inventory_items:
        name = item["item_name"]
        qty = item["quantity"]
        if name in gl.CONSUMABLE_EFFECTS:
            effect = gl.CONSUMABLE_EFFECTS[name]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{effect['btn']} (x{qty})",
                    callback_data=f"use_item:{item['id']}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton(text="◀️ Вернуться к приключению", callback_data="back_to_game")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_shop_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура придорожной торговли"""
    keyboard = []
    for item_key, info in gl.SHOP_ITEMS.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{info['name']} — {info['cost']} 🪙 ({info['desc']})",
                callback_data=f"buy:{item_key}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="◀️ Вернуться к приключению", callback_data="back_to_game")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_main_menu_keyboard(is_dead: bool = False) -> InlineKeyboardMarkup:
    """Системное меню (Досье, Летопись, Зал славы, Кладбище)"""
    keyboard = [
        [
            InlineKeyboardButton(text="👤 Досье героя", callback_data="show_profile"),
            InlineKeyboardButton(text="📜 Летопись", callback_data="show_chronicle")
        ],
        [
            InlineKeyboardButton(text="🏆 Зал славы", callback_data="show_hall_of_fame"),
            InlineKeyboardButton(text="⚰️ Кладбище", callback_data="show_graveyard")
        ]
    ]
    if not is_dead:
        keyboard.append([
            InlineKeyboardButton(text="⚠️ Начать сначала", callback_data="restart_game"),
            InlineKeyboardButton(text="◀️ Назад в игру", callback_data="back_to_game")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(text="⚔️ Начать новую сагу", callback_data="restart_game")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_level_up_keyboard(stat_points: int = 1) -> InlineKeyboardMarkup:
    """Выбор характеристики при повышении уровня"""
    keyboard = [
        [InlineKeyboardButton(text="💪 +1 к Силе (Урон и напор в бою)", callback_data="lvlup:str")],
        [InlineKeyboardButton(text="🦶 +1 к Ловкости (Уклонение, скрытность, стрельба)", callback_data="lvlup:agi")],
        [InlineKeyboardButton(text="🧠 +1 к Интеллекту (Рассудок, яды и знание мира)", callback_data="lvlup:int")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_death_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура при гибели персонажа"""
    keyboard = [
        [InlineKeyboardButton(text="⚰️ Посетить кладбище павших", callback_data="show_graveyard")],
        [InlineKeyboardButton(text="⚔️ Начать новую сагу (Создать героя)", callback_data="restart_game")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_restart_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение сброса прогресса"""
    keyboard = [
        [InlineKeyboardButton(text="💀 Да, начать сначала", callback_data="confirm_restart")],
        [InlineKeyboardButton(text="🛡️ Продолжить текущий путь", callback_data="back_to_game")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_cancel_custom_action_keyboard() -> InlineKeyboardMarkup:
    """Отмена ввода текста"""
    keyboard = [
        [InlineKeyboardButton(text="❌ Отмена (вернуться к выбору)", callback_data="back_to_game")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
