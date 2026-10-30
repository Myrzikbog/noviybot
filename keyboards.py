from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import game_logic as gl

def get_class_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора класса с прозрачной демонстрацией характеристик"""
    keyboard = [
        [InlineKeyboardButton(text="⚔️ Мечник (СИЛ +2 | HP 100 | 15 🪙)", callback_data="class:swordsman")],
        [InlineKeyboardButton(text="🧪 Лекарь (ИНТ +2, ЛОВ +1 | San 90 | 20 🪙)", callback_data="class:medicus")],
        [InlineKeyboardButton(text="🗡️ Бродяга (ЛОВ +2 | HP 85 | 20 🪙)", callback_data="class:cutpurse")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_game_turn_keyboard(choices: List[str], choice_stats: List[str] = None, is_in_combat: bool = False) -> InlineKeyboardMarkup:
    """Компактная клавиатура игрового хода: эргономично на мобильных экранах"""
    keyboard = []

    stat_icons = {
        "str": "⚔️ [Сила]",
        "agi": "🦶 [Ловкость]",
        "int": "🧠 [Интеллект]",
        "luck": "👉 [Удача]"
    }

    # Кнопки с готовыми вариантами от Gemini
    for i, choice in enumerate(choices):
        hint = choice_stats[i] if choice_stats and i < len(choice_stats) else "luck"
        prefix = stat_icons.get(hint, "👉")
        button_text = choice if len(choice) <= 35 else choice[:32] + "..."
        keyboard.append([InlineKeyboardButton(text=f"{prefix} {button_text}", callback_data=f"choice:{i}")])

    # Своё действие
    keyboard.append([
        InlineKeyboardButton(text="✍️ Написать своё действие текстом", callback_data="custom_action")
    ])

    # Компактная сервисная строка (всего 3 кнопки в 1 ряд!)
    if is_in_combat:
        management_row = [
            InlineKeyboardButton(text="🎒 Рюкзак", callback_data="show_inventory"),
            InlineKeyboardButton(text="🏃 Отступить", callback_data="choice:retreat"),
            InlineKeyboardButton(text="⚙️ Меню", callback_data="show_main_menu")
        ]
    else:
        management_row = [
            InlineKeyboardButton(text="🎒 Рюкзак", callback_data="show_inventory"),
            InlineKeyboardButton(text="🛒 Лавка", callback_data="show_shop"),
            InlineKeyboardButton(text="⚙️ Меню", callback_data="show_main_menu")
        ]
    keyboard.append(management_row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_inventory_keyboard(inventory_items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Интерактивная клавиатура инвентаря с кнопками применения расходников"""
    keyboard = []

    # Добавляем кнопки применения для каждого расходуемого предмета в сумке
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
    """Клавиатура лавки торговца"""
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
    """Клавиатура выбора характеристики при Level Up"""
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
    """Клавиатура подтверждения сброса прогресса"""
    keyboard = [
        [InlineKeyboardButton(text="💀 Да, начать сначала", callback_data="confirm_restart")],
        [InlineKeyboardButton(text="🛡️ Продолжить текущий путь", callback_data="back_to_game")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_cancel_custom_action_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены ввода кастомного действия"""
    keyboard = [
        [InlineKeyboardButton(text="❌ Отмена (вернуться к выбору)", callback_data="back_to_game")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
