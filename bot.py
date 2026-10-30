import asyncio
import logging
import html
from typing import Dict, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery

import config
import database as db
import game_logic as gl
import gemini_service as gs
import keyboards as kb

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# FSM Состояния
class GameStates(StatesGroup):
    waiting_for_custom_action = State()

# Кэш последних выборов для каждого игрока {user_id: [choice_text1, choice_text2, ...]}
last_user_choices: Dict[int, List[str]] = {}
last_user_narrative: Dict[int, str] = {}

def escape_text(text: str) -> str:
    """Безопасное экранирование текста для HTML режима Telegram"""
    return html.escape(text)

async def send_turn_message(bot: Bot, chat_id: int, user_id: int, turn_data: gs.GameTurnOutput, dice_verdict: str = ""):
    """Отправка сообщения игрового раунда с кнопками и статусом"""
    player = await db.get_player(user_id)
    if not player:
        return

    items = await db.get_inventory(user_id)
    status_header = gl.format_status_header(player, len(items))

    # Формируем тело сообщения
    dice_block = f"\n{dice_verdict}\n" if dice_verdict else ""
    
    # Блок изменений ресурсов
    changes = []
    if turn_data.hp_change != 0:
        changes.append(f"❤️ {'+' if turn_data.hp_change > 0 else ''}{turn_data.hp_change} HP")
    if turn_data.sanity_change != 0:
        changes.append(f"🧠 {'+' if turn_data.sanity_change > 0 else ''}{turn_data.sanity_change} Рассудок")
    if turn_data.gold_change != 0:
        changes.append(f"🪙 {'+' if turn_data.gold_change > 0 else ''}{turn_data.gold_change} монет")
    if turn_data.items_added:
        changes.append(f"🎁 Получено: {', '.join(turn_data.items_added)}")
    if turn_data.items_removed:
        changes.append(f"🔻 Потеряно: {', '.join(turn_data.items_removed)}")

    changes_block = ""
    if changes:
        changes_block = f"\n\n<i>[{' | '.join(changes)}]</i>"

    full_narrative = (
        f"{status_header}"
        f"{dice_block}"
        f"{escape_text(turn_data.narrative)}"
        f"{changes_block}"
    )

    # Сохраняем в кэш для возврата
    last_user_choices[user_id] = turn_data.choices
    last_user_narrative[user_id] = full_narrative

    # Проверка на гибель
    if player["is_dead"] or turn_data.is_dead:
        death_text = (
            f"\n\n💀 <b>СМЕРТЬ НАСТИГЛА ГЕРОЯ</b>\n"
            f"<i>{escape_text(turn_data.death_reason or player.get('death_reason') or 'Ваш путь оборвался во тьме.')}</i>\n"
            f"Прожито ходов: {player['turn_count']}. Ваше имя растворилось среди пепла веков."
        )
        await bot.send_message(
            chat_id=chat_id,
            text=full_narrative + death_text,
            reply_markup=kb.get_death_keyboard(),
            parse_mode="HTML"
        )
        return

    # Отправка живого хода
    reply_markup = kb.get_game_turn_keyboard(turn_data.choices)
    await bot.send_message(
        chat_id=chat_id,
        text=full_narrative,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# --- Хэндлеры ---

dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    player = await db.get_player(user_id)

    # Если уже есть живой персонаж
    if player and not player["is_dead"]:
        items = await db.get_inventory(user_id)
        choices = last_user_choices.get(user_id, ["Осмотреться вокруг", "Проверить снаряжение", "Двигаться вперед"])
        status = gl.format_status_header(player, len(items))
        last_text = last_user_narrative.get(user_id, "Вы продолжаете своё мрачное путешествие.")

        await message.answer(
            f"⚔️ <b>Хроники Вересковых Земель</b>\n"
            f"С возвращением, {escape_text(player['class_title'])}!\n\n"
            f"{status}\n"
            f"{last_text}",
            reply_markup=kb.get_game_turn_keyboard(choices),
            parse_mode="HTML"
        )
        return

    # Если персонажа нет или он мертв — экран создания
    welcome_text = (
        "⚔️ <b>ТЁМНЫЙ ВЕК: САГА О ВЫЖИВАНИИ</b>\n\n"
        "<i>На дворе 1349 год. Земли раздирает мор, страх и феодальный произвол. "
        "В дремучих лесах нечисть шепчет на забытых наречиях, а на дорогах правят мародеры. "
        "Здесь нет бессмертных избранных — каждый неверный шаг может стать последним.</i>\n\n"
        "Выберите происхождение вашего героя:"
    )
    await message.answer(welcome_text, reply_markup=kb.get_class_selection_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("class:"))
async def handle_class_selection(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    class_key = callback.data.split(":")[1]
    class_info = gl.CLASSES.get(class_key)
    if not class_info:
        await callback.answer("Неизвестный класс!", show_alert=True)
        return

    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name

    await callback.message.edit_text("⏳ <i>Гейм-Мастер открывает старинную книгу судеб...</i>", parse_mode="HTML")

    # Создаем персонажа в SQLite
    player = await db.create_player(
        user_id=user_id,
        username=username,
        class_name=class_info["name"],
        class_title=class_info["title"],
        hp=class_info["hp"],
        sanity=class_info["sanity"],
        gold=class_info["gold"],
        str_stat=class_info["str"],
        agi_stat=class_info["agi"],
        int_stat=class_info["int"],
        start_items=class_info["items"]
    )

    # Генерируем уникальный пролог через Gemini
    prologue = await gs.generate_prologue(
        class_title=class_info["title"],
        class_name=class_info["name"],
        start_items=class_info["items"]
    )

    # Сохраняем в историю и обновляем состояние
    await db.save_turn_history(user_id, "Начало пути", prologue.narrative, 1)
    if prologue.key_memory:
        await db.add_chronicle_entry(user_id, 1, prologue.key_memory)

    await send_turn_message(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=user_id,
        turn_data=prologue
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("choice:"))
async def handle_choice(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    choice_idx = int(callback.data.split(":")[1])

    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await callback.answer("Персонаж погиб или не создан. Начните с /start", show_alert=True)
        return

    choices = last_user_choices.get(user_id, [])
    if choice_idx >= len(choices):
        action_text = "Действовать осмотрительно"
    else:
        action_text = choices[choice_idx]

    await execute_game_turn(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=user_id,
        action_text=action_text,
        progress_message=callback.message
    )
    await callback.answer()

@dp.callback_query(F.data == "custom_action")
async def handle_custom_action_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.waiting_for_custom_action)
    await callback.message.reply(
        "✍️ <b>Ваше действие:</b>\n"
        "Напишите в ответ любое действие (например: <i>'Достаю кинжал, гашу факел и затаиваюсь за бочками'</i> или <i>'Пытаюсь подкупить стражника серебряной монетой'</i>).\n\n"
        "Помните: суровые законы средневековья и кубик решат, получится ли это!",
        reply_markup=kb.get_cancel_custom_action_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(GameStates.waiting_for_custom_action)
async def handle_custom_action_input(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    action_text = message.text.strip()

    if not action_text:
        return

    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await message.answer("Герой не найден или мертв. Нажмите /start")
        return

    wait_msg = await message.answer("🎲 <i>Бросаем кубик d20... Гейм-Мастер оценивает ситуацию...</i>", parse_mode="HTML")
    await execute_game_turn(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=user_id,
        action_text=action_text,
        progress_message=wait_msg
    )

async def execute_game_turn(bot: Bot, chat_id: int, user_id: int, action_text: str, progress_message: Message = None):
    """Общая логика выполнения игрового хода"""
    player = await db.get_player(user_id)
    if not player:
        return

    # 1. Бросок кубика d20 движком
    raw_roll, total_roll, dice_verdict = gl.roll_dice_for_action(action_text, player)

    # 2. Подгружаем контекст
    inventory = await db.get_inventory(user_id)
    chronicle = await db.get_chronicle(user_id, limit=6)
    recent_history = await db.get_recent_turns(user_id)

    # 3. Вызываем Gemini API
    turn_output = await gs.generate_turn(
        player=player,
        inventory=inventory,
        chronicle=chronicle,
        recent_history=recent_history,
        action_text=action_text,
        dice_verdict=dice_verdict
    )

    # 4. Обновляем инвентарь в SQLite
    for item in turn_output.items_added:
        await db.add_item(user_id, item)
    for item in turn_output.items_removed:
        await db.remove_item(user_id, item)

    # 5. Обновляем статус игрока
    updated_player = await db.update_player_state(
        user_id=user_id,
        hp_delta=turn_output.hp_change,
        sanity_delta=turn_output.sanity_change,
        gold_delta=turn_output.gold_change,
        location=turn_output.location_name,
        is_dead=turn_output.is_dead,
        death_reason=turn_output.death_reason
    )

    # 6. Записываем в хронику и память
    await db.save_turn_history(user_id, action_text, turn_output.narrative, updated_player["turn_count"])
    if turn_output.key_memory:
        await db.add_chronicle_entry(user_id, updated_player["turn_count"], turn_output.key_memory)

    # 7. Удаляем промежуточное сервисное сообщение если было
    if progress_message:
        try:
            await progress_message.delete()
        except Exception:
            pass

    # 8. Отправляем результат хода
    await send_turn_message(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        turn_data=turn_output,
        dice_verdict=dice_verdict
    )

# --- Дополнительные меню: Инвентарь, Летопись, Профиль ---

@dp.callback_query(F.data == "show_inventory")
async def cb_show_inventory(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player:
        return

    items = await db.get_inventory(user_id)
    items_list = "\n".join([f"• <b>{escape_text(it)}</b>" for it in items]) if items else "<i>Пусто... Только пыль на дне мешка.</i>"

    text = (
        f"🎒 <b>ПОХОДНЫЙ МЕШОК ({len(items)}/8)</b>\n\n"
        f"🪙 <b>Звенит в кошеле:</b> {player['gold']} монет\n\n"
        f"<b>Снаряжение:</b>\n"
        f"{items_list}\n\n"
        f"<i>💡 Совет: вы можете в любой момент нажать 'Своё действие' и написать, как именно вы используете предмет из рюкзака!</i>"
    )
    await callback.message.edit_text(text, reply_markup=kb.get_inventory_keyboard(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "show_chronicle")
async def cb_show_chronicle(callback: CallbackQuery):
    user_id = callback.from_user.id
    entries = await db.get_chronicle(user_id, limit=10)

    chronicle_text = "\n\n".join([f"📜 <i>{escape_text(e)}</i>" for e in entries]) if entries else "Летопись пока чиста."

    text = (
        f"📖 <b>ХРОНИКА СОВЕРШЁННОГО</b>\n\n"
        f"{chronicle_text}\n\n"
        f"<i>Эти деяния помнит этот суровый мир.</i>"
    )
    await callback.message.edit_text(text, reply_markup=kb.get_inventory_keyboard(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "show_profile")
async def cb_show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player:
        return

    hp_bar = gl.render_progress_bar(player["hp"], 100)
    san_bar = gl.render_progress_bar(player["sanity"], 100, filled_char="🟦", empty_char="⬛")

    text = (
        f"👤 <b>ДОСЬЕ ГЕРОЯ</b>\n\n"
        f"<b>Звание:</b> {escape_text(player['class_title'])}\n"
        f"<b>Класс:</b> {escape_text(player['class_name'])}\n"
        f"<b>Пережито дней/ходов:</b> {player['turn_count']}\n\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 {hp_bar}\n"
        f"🧠 <b>Рассудок:</b> {player['sanity']}/100 {san_bar}\n"
        f"🪙 <b>Золото:</b> {player['gold']}\n\n"
        f"<b>Боевые навыки:</b>\n"
        f"• Сила: <b>{player['str_stat']:+d}</b>\n"
        f"• Ловкость: <b>{player['agi_stat']:+d}</b>\n"
        f"• Интеллект: <b>{player['int_stat']:+d}</b>"
    )
    await callback.message.edit_text(text, reply_markup=kb.get_inventory_keyboard(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_game")
async def cb_back_to_game(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player:
        return

    choices = last_user_choices.get(user_id, ["Осмотреться вокруг", "Проверить оружие", "Идти вперед"])
    narrative = last_user_narrative.get(user_id, "Вы начеку.")

    await callback.message.edit_text(
        narrative,
        reply_markup=kb.get_game_turn_keyboard(choices),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(Command("restart"))
@dp.callback_query(F.data == "restart_game")
async def handle_restart_prompt(event, state: FSMContext):
    await state.clear()
    text = (
        "⚠️ <b>ВЫ УВЕРЕНЫ, ЧТО ХОТИТЕ НАЧАТЬ ЗАНОВО?</b>\n\n"
        "Текущий персонаж, его инвентарь, характеристики и летопись будут стёрты навсегда."
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb.get_restart_confirm_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb.get_restart_confirm_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "confirm_restart")
async def handle_restart_confirmed(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    # Очищаем кэш
    last_user_choices.pop(user_id, None)
    last_user_narrative.pop(user_id, None)

    welcome_text = (
        "⚰️ <i>Старая история окончена. Пепел развеян над вересковыми пустошами.</i>\n\n"
        "Выберите происхождение нового героя:"
    )
    await callback.message.edit_text(welcome_text, reply_markup=kb.get_class_selection_keyboard(), parse_mode="HTML")
    await callback.answer()

# --- Главная функция запуска ---

async def main():
    errors = config.validate_config()
    if errors:
        for err in errors:
            logger.error(f"❌ {err}")
        print("\n" + "="*60)
        print("ВНИМАНИЕ! Не заполнены переменные окружения в файле .env:")
        for err in errors:
            print(f"  • {err}")
        print("="*60 + "\n")
        return

    # Инициализация SQLite
    logger.info("Инициализация базы данных SQLite...")
    await db.init_db()

    bot = Bot(token=config.BOT_TOKEN)
    logger.info("Запуск Telegram бота (polling)...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
