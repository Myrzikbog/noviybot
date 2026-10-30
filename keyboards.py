from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import game_logic as gl

def get_class_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора класса при старте игры"""
    keyboard = [
        [InlineKeyboardButton(text="⚔️ Ветеран-наёмник (Сила + Стойкость)", callback_data="class:swordsman")],
        [InlineKeyboardButton(text="🧪 Опальный лекарь (Рассудок + Знания)", callback_data="class:medicus")],
        [InlineKeyboardButton(text="🗡️ Ночной вор (Ловкость + Скрытность)", callback_data="class:cutpurse")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_game_turn_keyboard(choices: List[str], is_in_combat: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура вариантов действий в игровом раунде"""
    keyboard = []

    # Кнопки с готовыми вариантами от Gemini
    for i, choice in enumerate(choices):
        prefix = "⚔️" if is_in_combat else "👉"
        button_text = choice if len(choice) <= 45 else choice[:42] + "..."
        keyboard.append([InlineKeyboardButton(text=f"{prefix} {button_text}", callback_data=f"choice:{i}")])

    # Своё действие
    keyboard.append([
        InlineKeyboardButton(text="✍️ Написать своё действие", callback_data="custom_action")
    ])

    # Панель инструментов
    keyboard.append([
        InlineKeyboardButton(text="🎒 Рюкзак", callback_data="show_inventory"),
        InlineKeyboardButton(text="🛒 Лавка", callback_data="show_shop"),
        InlineKeyboardButton(text="📜 Летопись", callback_data="show_chronicle")
    ])
    keyboard.append([
        InlineKeyboardButton(text="👤 Досье", callback_data="show_profile"),
        InlineKeyboardButton(text="🏆 Зал славы", callback_data="show_hall_of_fame"),
        InlineKeyboardButton(text="⚰️ Кладбище", callback_data="show_graveyard")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_shop_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура лавки торговца"""
    keyboard = []
    for item_key, info in gl.SHOP_ITEMS.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"Купить {info['name']} — {info['cost']} 🪙",
                callback_data=f"buy:{item_key}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="◀️ Вернуться к приключению", callback_data="back_to_game")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_level_up_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора характеристики при Level Up"""
    keyboard = [
        [InlineKeyboardButton(text="💪 +1 к Силе (Урон и напор)", callback_data="lvlup:str")],
        [InlineKeyboardButton(text="🦶 +1 к Ловкости (Уклонение и скрытность)", callback_data="lvlup:agi")],
        [InlineKeyboardButton(text="🧠 +1 к Интеллекту (Рассудок и наблюдательность)", callback_data="lvlup:int")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_inventory_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура просмотра инвентаря"""
    keyboard = [
        [InlineKeyboardButton(text="◀️ Вернуться к приключению", callback_data="back_to_game")]
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
