from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_class_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора класса при старте игры"""
    keyboard = [
        [InlineKeyboardButton(text="⚔️ Ветеран-наёмник (Сила + Стойкость)", callback_data="class:swordsman")],
        [InlineKeyboardButton(text="🧪 Опальный лекарь (Рассудок + Знания)", callback_data="class:medicus")],
        [InlineKeyboardButton(text="🗡️ Ночной вор (Ловкость + Скрытность)", callback_data="class:cutpurse")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_game_turn_keyboard(choices: List[str]) -> InlineKeyboardMarkup:
    """Клавиатура вариантов действий в игровом раунде"""
    keyboard = []

    # Кнопки с готовыми вариантами от Gemini
    for i, choice in enumerate(choices):
        # Ограничиваем длину текста на кнопке Telegram
        button_text = choice if len(choice) <= 45 else choice[:42] + "..."
        keyboard.append([InlineKeyboardButton(text=f"👉 {button_text}", callback_data=f"choice:{i}")])

    # Своё действие
    keyboard.append([
        InlineKeyboardButton(text="✍️ Написать своё действие", callback_data="custom_action")
    ])

    # Панель инструментов
    keyboard.append([
        InlineKeyboardButton(text="🎒 Рюкзак", callback_data="show_inventory"),
        InlineKeyboardButton(text="📜 Летопись", callback_data="show_chronicle"),
        InlineKeyboardButton(text="👤 Герой", callback_data="show_profile")
    ])

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
        [InlineKeyboardButton(text="⚰️ Начать новую сагу (Создать героя)", callback_data="restart_game")]
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
