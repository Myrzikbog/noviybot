import asyncio
import logging
import html
from collections import defaultdict
from typing import Dict, List, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BotCommand
from aiogram.exceptions import TelegramBadRequest

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

# Замки для защиты от двойных кликов и параллельных запросов {user_id: Lock}
user_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

def safe_html(text: Any) -> str:
    """Безопасное экранирование текста для HTML режима Telegram"""
    return html.escape(str(text or ""))

async def safe_edit_message(message: Message, text: str, reply_markup=None):
    """Безопасное редактирование сообщения с защитой от 'message is not modified'"""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.warning(f"Ошибка при edit_text: {e}")

async def send_turn_message(bot: Bot, chat_id: int, user_id: int, turn_data: gs.GameTurnOutput, dice_verdict: str = ""):
    """Отправка сообщения игрового раунда с кнопками и сохранением в SQLite"""
    player = await db.get_player(user_id)
    if not player:
        return

    items_count = await db.get_inventory_count(user_id)
    status_header = gl.format_status_header(player, items_count)

    # Блок броска кубика
    dice_block = f"\n{dice_verdict}\n" if dice_verdict else ""

    # Блок изменений ресурсов
    changes = []
    if turn_data.hp_change != 0:
        changes.append(f"❤️ {'+' if turn_data.hp_change > 0 else ''}{turn_data.hp_change} HP")
    if turn_data.sanity_change != 0:
        changes.append(f"🧠 {'+' if turn_data.sanity_change > 0 else ''}{turn_data.sanity_change} Рассудок")
    if turn_data.gold_change != 0:
        changes.append(f"🪙 {'+' if turn_data.gold_change > 0 else ''}{turn_data.gold_change} монет")
    if turn_data.xp_gained > 0:
        changes.append(f"⭐ +{turn_data.xp_gained} XP")
    if turn_data.items_added:
        safe_items = [safe_html(it) for it in turn_data.items_added]
        changes.append(f"🎁 Получено: {', '.join(safe_items)}")
    if turn_data.items_removed:
        safe_items = [safe_html(it) for it in turn_data.items_removed]
        changes.append(f"🔻 Потеряно: {', '.join(safe_items)}")

    changes_block = f"\n\n<i>[{' | '.join(changes)}]</i>" if changes else ""

    # Ограничение длины нарратива для защиты от лимита 4096 символов Telegram
    narrative_text = safe_html(turn_data.narrative)[:2200]

    full_narrative = (
        f"{status_header}"
        f"{dice_block}"
        f"{narrative_text}"
        f"{changes_block}"
    )

    # Сохраняем в SQLite для устойчивости к перезапуску бота!
    await db.save_choices_and_narrative(user_id, turn_data.choices, full_narrative)

    # Проверка на гибель
    if player["is_dead"] or turn_data.is_dead:
        death_reason = safe_html(turn_data.death_reason or player.get("death_reason") or "Ваш путь оборвался во тьме.")
        death_text = (
            f"\n\n💀 <b>СМЕРТЬ НАСТИГЛА ГЕРОЯ</b>\n"
            f"<i>{death_reason}</i>\n"
            f"Прожито ходов: <b>{player['turn_count']}</b> | Уровень: <b>{player.get('level', 1)}</b>.\n"
            f"Ваше имя высечено на надгробии Кладбища павших."
        )
        await bot.send_message(
            chat_id=chat_id,
            text=full_narrative + death_text,
            reply_markup=kb.get_death_keyboard(),
            parse_mode="HTML"
        )
        return

    # Отправка обычного хода
    is_combat = bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0)
    reply_markup = kb.get_game_turn_keyboard(
        choices=turn_data.choices,
        choice_stats=turn_data.choice_stats,
        is_in_combat=is_combat
    )
    await bot.send_message(
        chat_id=chat_id,
        text=full_narrative,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# --- Хэндлеры команд и интерфейса ---

dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    player = await db.get_player(user_id)

    # Если уже есть живой персонаж
    if player and not player["is_dead"]:
        items_count = await db.get_inventory_count(user_id)
        choices, last_narrative = await db.get_saved_choices_and_narrative(user_id)
        if not choices:
            choices = ["Осмотреться вокруг", "Проверить снаряжение", "Двигаться вперед"]

        status = gl.format_status_header(player, items_count)
        narrative_to_show = last_narrative if last_narrative else "Вы продолжаете своё мрачное путешествие."

        await message.answer(
            f"⚔️ <b>Хроники Вересковых Земель</b>\n"
            f"С возвращением, {safe_html(player['class_title'])}!\n\n"
            f"{status}\n"
            f"{narrative_to_show}",
            reply_markup=kb.get_game_turn_keyboard(choices, is_in_combat=bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0)),
            parse_mode="HTML"
        )
        return

    # Экран создания нового героя
    welcome_text = (
        "⚔️ <b>ТЁМНЫЙ ВЕК: САГА О ВЫЖИВАНИИ</b>\n\n"
        "<i>На дворе 1349 год. Земли раздирает мор, страх и феодальный произвол. "
        "В дремучих лесах нечисть шепчет на забытых наречиях, а на дорогах правят мародеры. "
        "Здесь нет бессмертных избранных — каждый шаг может стать последним.</i>\n\n"
        "Выберите происхождение вашего героя:"
    )
    await message.answer(welcome_text, reply_markup=kb.get_class_selection_keyboard(), parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>РУКОВОДСТВО ПО ВЫЖИВАНИЮ:</b>\n\n"
        "• <b>Кубик d20:</b> Каждое рискованное действие бросает кубик от 1 до 20 с учетом ваших характеристик:\n"
        "  - <i>1 — Критический провал</i> (оружие ломается, тяжелая травма).\n"
        "  - <i>2–9 — Неудача</i> (урон, промах, срыв плана).\n"
        "  - <i>10–14 — Частичный успех</i> (цель достигнута, но с ценой).\n"
        "  - <i>15–19 — Полный успех</i> (чистое исполнение без потерь).\n"
        "  - <i>20 — Критический триумф</i> (сокрушительный удар, редкий трофей).\n\n"
        "• <b>Характеристики:</b>\n"
        "  - ⚔️ <i>Сила</i>: урон оружием, выбивание дверей, силовое сопротивление.\n"
        "  - 🦶 <i>Ловкость</i>: скрытность, уклонение, стрельба, взлом замков.\n"
        "  - 🧠 <i>Интеллект</i>: знание трав, ядов, анатомии и сопротивление ужасу.\n\n"
        "• <b>Здоровье и Рассудок:</b>\n"
        "  Падение ❤️ HP или 🧠 Рассудка до 0 ведет к <b>необратимой смерти персонажа</b>!\n\n"
        "• <b>Свобода действий:</b>\n"
        "  Вы можете в любой момент нажать «✍️ Написать своё действие» и описать свой поступок словами!"
    )
    await message.answer(help_text, parse_mode="HTML")

@dp.callback_query(F.data.startswith("class:"))
async def handle_class_selection(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id

    async with user_locks[user_id]:
        class_key = callback.data.split(":")[1]
        class_info = gl.CLASSES.get(class_key)
        if not class_info:
            await callback.answer("Неизвестный класс!", show_alert=True)
            return

        username = callback.from_user.username or callback.from_user.first_name
        await callback.message.edit_text("⏳ <i>Гейм-Мастер открывает старинную книгу судеб...</i>", parse_mode="HTML")
        await callback.bot.send_chat_action(callback.message.chat.id, "typing")

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

        prologue = await gs.generate_prologue(
            class_title=class_info["title"],
            class_name=class_info["name"],
            start_items=class_info["items"]
        )

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

    # Проверка замка от спама
    if user_locks[user_id].locked():
        await callback.answer("⏳ Гейм-Мастер уже бросает кубики...", show_alert=False)
        return

    async with user_locks[user_id]:
        param = callback.data.split(":")[1]
        player = await db.get_player(user_id)
        if not player or player["is_dead"]:
            await callback.answer("Персонаж погиб. Начните с /start", show_alert=True)
            return

        choices, _ = await db.get_saved_choices_and_narrative(user_id)

        if param == "retreat":
            action_text = "Пытаюсь спешно разорвать дистанцию и отступить в укрытие"
        else:
            try:
                choice_idx = int(param)
                action_text = choices[choice_idx] if choice_idx < len(choices) else "Действовать осмотрительно"
            except Exception:
                action_text = "Действовать осмотрительно"

        await callback.answer("🎲 Бросок кубика...")
        await callback.bot.send_chat_action(callback.message.chat.id, "typing")

        await execute_game_turn(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=user_id,
            action_text=action_text,
            progress_message=callback.message
        )

@dp.callback_query(F.data == "custom_action")
async def handle_custom_action_prompt(callback: CallbackQuery, state: FSMContext):
    player = await db.get_player(callback.from_user.id)
    if not player or player["is_dead"]:
        await callback.answer("💀 Персонаж погиб. Начните заново с /start", show_alert=True)
        return

    await state.set_state(GameStates.waiting_for_custom_action)
    await callback.message.reply(
        "✍️ <b>Ваше действие:</b>\n"
        "Напишите текстом любое действие (до 250 символов).\n"
        "<i>Например: 'Достаю кинжал, гашу факел и тихо подбираюсь к часовому сзади'</i>",
        reply_markup=kb.get_cancel_custom_action_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(GameStates.waiting_for_custom_action, F.text)
async def handle_custom_action_text(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    action_text = message.text.strip()[:250]  # Жесткий лимит длины!

    if not action_text:
        return

    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await message.answer("💀 Герой погиб. Нажмите /start для новой саги.")
        return

    async with user_locks[user_id]:
        await message.bot.send_chat_action(message.chat.id, "typing")
        wait_msg = await message.answer("🎲 <i>Бросаем кубик d20... Гейм-Мастер оценивает поступок...</i>", parse_mode="HTML")
        await execute_game_turn(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=user_id,
            action_text=action_text,
            progress_message=wait_msg
        )

@dp.message(GameStates.waiting_for_custom_action)
async def handle_custom_action_non_text(message: Message):
    """Защита от стикеров, голосовых и медиа в режиме ввода действия"""
    await message.reply(
        "⚠️ Пожалуйста, опишите ваше действие обычным текстом (стикеры, фото и голосовые сообщения не поддерживаются).",
        reply_markup=kb.get_cancel_custom_action_keyboard()
    )

async def execute_game_turn(bot: Bot, chat_id: int, user_id: int, action_text: str, progress_message: Message = None):
    """Выполнение игрового хода: d20, асинхронный Gemini, урон, опыт и прокачка"""
    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        return

    # 1. Бросок кубика d20
    raw_roll, total_roll, dice_verdict = gl.roll_dice_for_action(action_text, player)

    # 2. Подгружаем контекст
    items_list = [it["item_name"] for it in await db.get_inventory_items(user_id)]
    chronicle = await db.get_chronicle(user_id, limit=6)
    recent_history = await db.get_recent_turns(user_id)

    # 3. Асинхронный вызов Gemini с таймаутом
    turn_output = await gs.generate_turn(
        player=player,
        inventory=items_list,
        chronicle=chronicle,
        recent_history=recent_history,
        action_text=action_text,
        dice_verdict=dice_verdict
    )

    # Если API упал или вернул таймаут
    if not turn_output:
        if progress_message:
            try:
                await progress_message.delete()
            except Exception:
                pass
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ <i>Связь с Гейм-Мастером на мгновение прервалась (сбой сети или квоты API). Ваш персонаж начеку. Попробуйте повторить выбор.</i>",
            reply_markup=kb.get_game_turn_keyboard(
                choices=["Осмотреться вокруг", "Проверить оружие", "Осторожно сделать шаг"],
                is_in_combat=bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0)
            ),
            parse_mode="HTML"
        )
        return

    # 4. Обновление инвентаря с проверкой вместимости
    for item in turn_output.items_added:
        await db.add_item(user_id, item)
    for item in turn_output.items_removed:
        await db.remove_item(user_id, item)

    # 5. Боевая система: расчет урона по боссу
    if turn_output.is_in_combat:
        enemy_name = turn_output.enemy_name or player.get("enemy_name") or "Враг"
        enemy_max = turn_output.enemy_max_hp if turn_output.enemy_max_hp > 0 else player.get("enemy_max_hp", 60)
        current_enemy_hp = player.get("enemy_hp", enemy_max) if player.get("enemy_hp", 0) > 0 else enemy_max

        # Преобразуем урон в безопасное отрицательное число
        dmg = abs(turn_output.enemy_hp_change)
        current_enemy_hp = max(0, current_enemy_hp - dmg)

        if current_enemy_hp <= 0:
            await db.update_combat_state(user_id, None, 0, 0)
            turn_output.xp_gained += 40
        else:
            await db.update_combat_state(user_id, enemy_name, current_enemy_hp, enemy_max)
    else:
        await db.update_combat_state(user_id, None, 0, 0)

    # 6. Прокачка и опыт (XP / Level Up)
    new_xp, new_lvl, did_level_up = await db.add_xp(user_id, turn_output.xp_gained)

    # 7. Обновление состояния игрока
    updated_player = await db.update_player_state(
        user_id=user_id,
        hp_delta=turn_output.hp_change,
        sanity_delta=turn_output.sanity_change,
        gold_delta=turn_output.gold_change,
        location=turn_output.location_name,
        is_dead=turn_output.is_dead,
        death_reason=turn_output.death_reason
    )

    # 8. Запись в историю
    await db.save_turn_history(user_id, action_text, turn_output.narrative, updated_player["turn_count"])
    if turn_output.key_memory:
        await db.add_chronicle_entry(user_id, updated_player["turn_count"], turn_output.key_memory)

    if progress_message:
        try:
            await progress_message.delete()
        except Exception:
            pass

    # 9. Отправка результата хода
    await send_turn_message(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        turn_data=turn_output,
        dice_verdict=dice_verdict
    )

    # 10. Если произошел Level Up — отправляем меню выбора прокачки
    if did_level_up and not updated_player["is_dead"]:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚡ <b>ПОВЫШЕНИЕ УРОВНЯ! (Уровень {new_lvl})</b>\n\n"
                f"Ваш опыт борьбы за жизнь приносит плоды: доступно очко усиления.\n"
                f"Выберите характеристику для постоянной прокачки:"
            ),
            reply_markup=kb.get_level_up_keyboard(updated_player.get("stat_points", 1)),
            parse_mode="HTML"
        )

# --- Обработка прокачки (Level Up) с защитой от читов ---

@dp.callback_query(F.data.startswith("lvlup:"))
async def handle_levelup_choice(callback: CallbackQuery):
    stat = callback.data.split(":")[1]
    user_id = callback.from_user.id
    stat_names = {"str": "Сила", "agi": "Ловкость", "int": "Интеллект"}

    async with user_locks[user_id]:
        player = await db.level_up_stat(user_id, stat)
        if not player:
            await callback.answer("У вас нет очков характеристик для распределения!", show_alert=True)
            return

        stat_title = stat_names.get(stat, "Характеристика")
        msg_text = (
            f"✨ <b>{stat_title} навсегда увеличена на +1!</b> (+25 HP и +25 Рассудка восстановлено)\n\n"
            f"Текущие боевые параметры:\n"
            f"• Сила: <b>{player['str_stat']:+d}</b> | Ловкость: <b>{player['agi_stat']:+d}</b> | Интеллект: <b>{player['int_stat']:+d}</b>"
        )

        # Если еще остались нераспределенные очки
        if player.get("stat_points", 0) > 0:
            msg_text += f"\n\n⚡ <i>Осталось очков прокачки: {player['stat_points']}</i>"
            await safe_edit_message(callback.message, msg_text, reply_markup=kb.get_level_up_keyboard(player['stat_points']))
        else:
            await safe_edit_message(callback.message, msg_text, reply_markup=kb.get_main_menu_keyboard(is_dead=False))

        await callback.answer("Уровень повышен!")

# --- Интерактивный рюкзак и использование предметов ---

@dp.callback_query(F.data == "show_inventory")
async def cb_show_inventory(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await callback.answer("Герой мертв.", show_alert=True)
        return

    items = await db.get_inventory_items(user_id)
    items_list = []
    for it in items:
        name = safe_html(it["item_name"])
        qty = it["quantity"]
        items_list.append(f"• <b>{name}</b>" + (f" (x{qty})" if qty > 1 else ""))

    content = "\n".join(items_list) if items_list else "<i>Пусто... Только пыль на дне мешка.</i>"

    text = (
        f"🎒 <b>ПОХОДНЫЙ МЕШОК ({len(items)}/8)</b>\n\n"
        f"🪙 <b>Звенит в кошеле:</b> {player['gold']} монет\n\n"
        f"<b>Снаряжение:</b>\n"
        f"{content}\n\n"
        f"<i>💡 Нажимайте кнопки ниже, чтобы мгновенно применить расходники из рюкзака:</i>"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_inventory_keyboard(items))
    await callback.answer()

@dp.callback_query(F.data.startswith("use_item:"))
async def cb_use_item(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with user_locks[user_id]:
        player = await db.get_player(user_id)
        if not player or player["is_dead"]:
            await callback.answer("Персонаж мертв.", show_alert=True)
            return

        items = await db.get_inventory_items(user_id)
        target_item = next((it for it in items if it["id"] == item_id), None)
        if not target_item:
            await callback.answer("Предмет не найден в сумке.", show_alert=True)
            return

        item_name = target_item["item_name"]
        effect = gl.CONSUMABLE_EFFECTS.get(item_name)
        if not effect:
            await callback.answer("Этот предмет нельзя применить напрямую.", show_alert=True)
            return

        success, msg = await db.use_consumable(user_id, item_name, effect["heal_hp"], effect["heal_san"])
        if not success:
            await callback.answer(msg, show_alert=True)
            return

        await callback.answer(f"Использовано: {item_name}!")

        # Обновляем экран рюкзака
        updated_items = await db.get_inventory_items(user_id)
        updated_player = await db.get_player(user_id)
        items_list = [f"• <b>{safe_html(it['item_name'])}</b>" + (f" (x{it['quantity']})" if it['quantity'] > 1 else "") for it in updated_items]
        content = "\n".join(items_list) if items_list else "<i>Пусто... Только пыль на дне мешка.</i>"

        text = (
            f"🎒 <b>ПОХОДНЫЙ МЕШОК ({len(updated_items)}/8)</b>\n\n"
            f"✅ <i>{msg}</i>\n\n"
            f"❤️ <b>Здоровье:</b> {updated_player['hp']}/100 | 🧠 <b>Рассудок:</b> {updated_player['sanity']}/100\n"
            f"🪙 <b>Звенит в кошеле:</b> {updated_player['gold']} монет\n\n"
            f"<b>Снаряжение:</b>\n"
            f"{content}"
        )
        await safe_edit_message(callback.message, text, reply_markup=kb.get_inventory_keyboard(updated_items))

# --- Лавка торговца с защитой от двойного списания ---

@dp.callback_query(F.data == "show_shop")
async def cb_show_shop(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await callback.answer("Мертвые не торгуют.", show_alert=True)
        return

    # Запрет лавки в бою
    if player.get("enemy_name") and player.get("enemy_hp", 0) > 0:
        await callback.answer("⚔️ Нельзя торговать посреди смертельного боя!", show_alert=True)
        return

    text = (
        f"🛒 <b>ЛАВКА ПРИДОРОЖНОГО ТОРГОВЦА</b>\n\n"
        f"Старик в засаленном кафтане раскладывает припасы на повозке.\n"
        f"🪙 <b>Ваш кошель:</b> {player['gold']} монет\n\n"
        f"<i>Приобретенные расходники можно использовать прямо из рюкзака:</i>"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_shop_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def handle_buy_item(callback: CallbackQuery):
    item_key = callback.data.split(":")[1]
    item_info = gl.SHOP_ITEMS.get(item_key)
    if not item_info:
        await callback.answer("Товар не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    async with user_locks[user_id]:
        player = await db.get_player(user_id)
        if not player or player["is_dead"]:
            await callback.answer("Герой мертв.", show_alert=True)
            return

        success, msg = await db.buy_shop_item(user_id, item_info["name"], item_info["cost"])
        if not success:
            await callback.answer(msg, show_alert=True)
            return

        await callback.answer(f"Куплено: {item_info['name']}!")
        updated_player = await db.get_player(user_id)
        text = (
            f"🛒 <b>ЛАВКА ПРИДОРОЖНОГО ТОРГОВЦА</b>\n\n"
            f"✅ <i>{msg}</i>\n\n"
            f"🪙 <b>Ваш кошель:</b> {updated_player['gold']} монет\n\n"
            f"<i>Что-нибудь ещё?</i>"
        )
        await safe_edit_message(callback.message, text, reply_markup=kb.get_shop_keyboard())

# --- Системное меню, Зал славы, Кладбище ---

@dp.callback_query(F.data == "show_main_menu")
async def cb_show_main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    is_dead = bool(player and player["is_dead"])

    text = (
        f"⚙️ <b>СИСТЕМНОЕ МЕНЮ</b>\n\n"
        f"Выберите необходимый раздел:"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_main_menu_keyboard(is_dead=is_dead))
    await callback.answer()

@dp.message(Command("top"))
@dp.callback_query(F.data == "show_hall_of_fame")
async def cb_show_hall_of_fame(event):
    top_players = await db.get_hall_of_fame(limit=10)

    rows = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, p in enumerate(top_players):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        status_icon = "💀" if p.get("is_dead") else "🛡️"
        rows.append(
            f"{medal} <b>{safe_html(p.get('username') or 'Путник')}</b> ({safe_html(p['class_title'])})\n"
            f"   └ <i>Ходов: {p['turns']} | Ур. {p.get('level', 1)} | Золото: {p['gold']} {status_icon}</i>"
        )

    content = "\n\n".join(rows) if rows else "Зал славы пока пуст. Будьте первыми!"
    text = f"🏆 <b>ЗАЛ СЛАВЫ: САМЫЕ ЖИВУЧИЕ ГЕРОИ</b>\n\n{content}"

    if isinstance(event, CallbackQuery):
        await safe_edit_message(event.message, text, reply_markup=kb.get_main_menu_keyboard(is_dead=False))
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb.get_main_menu_keyboard(is_dead=False), parse_mode="HTML")

@dp.message(Command("graveyard"))
@dp.callback_query(F.data == "show_graveyard")
async def cb_show_graveyard(event):
    dead_heroes = await db.get_graveyard(limit=8)

    rows = []
    for d in dead_heroes:
        rows.append(
            f"🪦 <b>{safe_html(d.get('username') or 'Путник')}</b> ({safe_html(d['class_title'])}, Ур. {d.get('level', 1)})\n"
            f"   ├ <i>Смерть: {safe_html(d['death_reason'])}</i>\n"
            f"   └ <i>Прожил: {d['turns_survived']} ходов | Оставил: {d['gold_earned']} монет</i>"
        )

    content = "\n\n".join(rows) if rows else "На этом кладбище пока нет свежих могил."
    text = f"⚰️ <b>КЛАДБИЩЕ ПАВШИХ ГЕРОЕВ</b>\n\n{content}"

    if isinstance(event, CallbackQuery):
        await safe_edit_message(event.message, text, reply_markup=kb.get_main_menu_keyboard(is_dead=True))
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb.get_main_menu_keyboard(is_dead=True), parse_mode="HTML")

@dp.callback_query(F.data == "show_chronicle")
async def cb_show_chronicle(callback: CallbackQuery):
    user_id = callback.from_user.id
    entries = await db.get_chronicle(user_id, limit=10)
    chronicle_text = "\n\n".join([f"📜 <i>{safe_html(e)}</i>" for e in entries]) if entries else "Летопись пока чиста."

    text = (
        f"📖 <b>ХРОНИКА СОВЕРШЁННОГО</b>\n\n"
        f"{chronicle_text}\n\n"
        f"<i>Эти деяния помнит этот суровый мир.</i>"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_main_menu_keyboard(is_dead=False))
    await callback.answer()

@dp.callback_query(F.data == "show_profile")
async def cb_show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player:
        return

    hp_bar = gl.render_progress_bar(player["hp"], 100)
    san_bar = gl.render_progress_bar(player["sanity"], 100, filled_char="🟦", empty_char="░")
    needed_xp = player.get("level", 1) * 150 + 50

    stat_points = player.get("stat_points", 0)
    lvl_extra = f" (⚡ Доступно очков: <b>{stat_points}</b>)" if stat_points > 0 else ""

    text = (
        f"👤 <b>ДОСЬЕ ГЕРОЯ</b>\n\n"
        f"<b>Звание:</b> {safe_html(player['class_title'])}\n"
        f"<b>Класс:</b> {safe_html(player['class_name'])}\n"
        f"<b>Уровень:</b> ⭐ {player.get('level', 1)} [{player.get('xp', 0)}/{needed_xp} XP]{lvl_extra}\n"
        f"<b>Пережито дней/ходов:</b> {player['turn_count']}\n\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 {hp_bar}\n"
        f"🧠 <b>Рассудок:</b> {player['sanity']}/100 {san_bar}\n"
        f"🪙 <b>Золото:</b> {player['gold']}\n\n"
        f"<b>Боевые характеристики:</b>\n"
        f"• Сила: <b>{player['str_stat']:+d}</b> (урон и напор)\n"
        f"• Ловкость: <b>{player['agi_stat']:+d}</b> (уклонение, стрельба, скрытность)\n"
        f"• Интеллект: <b>{player['int_stat']:+d}</b> (рассудок, лечение, знание трав)"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_main_menu_keyboard(is_dead=bool(player["is_dead"])))
    await callback.answer()

@dp.callback_query(F.data == "back_to_game")
async def cb_back_to_game(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player:
        return

    if player["is_dead"]:
        await callback.answer("💀 Герой погиб. Начните заново с /start", show_alert=True)
        return

    choices, narrative = await db.get_saved_choices_and_narrative(user_id)
    if not choices:
        choices = ["Осмотреться вокруг", "Проверить оружие", "Идти вперед"]
    if not narrative:
        narrative = "Вы начеку."

    is_combat = bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0)
    await safe_edit_message(
        callback.message,
        narrative,
        reply_markup=kb.get_game_turn_keyboard(choices, is_in_combat=is_combat)
    )
    await callback.answer()

@dp.message(Command("restart"))
@dp.callback_query(F.data == "restart_game")
async def handle_restart_prompt(event, state: FSMContext):
    await state.clear()
    text = (
        "⚠️ <b>ВЫ УВЕРЕНЫ, ЧТО ХОТИТЕ НАЧАТЬ ЗАНОВО?</b>\n\n"
        "Текущий персонаж, его инвентарь и характеристики будут сброшены. Имя героя сохранится в анналах истории."
    )
    if isinstance(event, CallbackQuery):
        await safe_edit_message(event.message, text, reply_markup=kb.get_restart_confirm_keyboard())
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb.get_restart_confirm_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "confirm_restart")
async def handle_restart_confirmed(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    welcome_text = (
        "⚰️ <i>Старая история окончена. Пепел развеян над вересковыми пустошами.</i>\n\n"
        "Выберите происхождение нового героя:"
    )
    await safe_edit_message(callback.message, welcome_text, reply_markup=kb.get_class_selection_keyboard())
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

    logger.info("Инициализация базы данных SQLite с оптимизацией WAL...")
    await db.init_db()

    bot = Bot(token=config.BOT_TOKEN)

    # Регистрация меню команд Telegram в нижнем углу интерфейса
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Продолжить игру / Главный экран"),
            BotCommand(command="help", description="Правила игры, кубик d20 и механики"),
            BotCommand(command="top", description="Зал славы (Топ выживших)"),
            BotCommand(command="graveyard", description="Кладбище павших героев"),
            BotCommand(command="restart", description="Сбросить и начать заново новым героем"),
        ])
    except Exception as e:
        logger.warning(f"Не удалось установить команды меню: {e}")

    logger.info("Запуск Telegram бота (polling)...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
