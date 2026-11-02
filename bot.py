import asyncio
import logging
import html
from collections import defaultdict
from typing import Dict, List, Any, Optional

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
    waiting_for_companion_talk = State()

# Замки для защиты от одновременных кликов {user_id: Lock}
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

async def send_turn_message(
    bot: Bot,
    chat_id: int,
    user_id: int,
    turn_data: gs.GameTurnOutput,
    dice_verdict: str = "",
    companion_note: str = ""
):
    """Отправка сообщения игрового раунда с кнопками и сохранением в SQLite"""
    player = await db.get_player(user_id)
    if not player:
        return

    items_count = await db.get_inventory_count(user_id)
    active_companion = await db.get_active_companion(user_id)
    status_header = gl.format_status_header(player, items_count, active_companion)

    # Блок броска кубика
    dice_block = f"\n{dice_verdict}\n" if dice_verdict else ""

    # Блок персонажа-собеседника с его уникальным речевым стилем
    npc_block = ""
    if turn_data.active_npc:
        n = turn_data.active_npc
        npc_block = (
            f"👤 <b>Собеседник:</b> {safe_html(n.name)} ({safe_html(n.title)})\n"
            f"<i>[Характер: {safe_html(n.temperament)} | Речь: {safe_html(n.speech_style)}]</i>\n\n"
        )

    # Блок изменений ресурсов и отношений
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
    if companion_note:
        changes.append(companion_note)

    changes_block = f"\n\n<i>[{' | '.join(changes)}]</i>" if changes else ""

    # Ограничение длины нарратива для Telegram (до 2800 символов)
    narrative_text = safe_html(turn_data.narrative)[:2800]

    full_narrative = (
        f"{status_header}"
        f"{dice_block}"
        f"{npc_block}"
        f"{narrative_text}"
        f"{changes_block}"
    )

    # Сохраняем в SQLite и выборы, и привязанные к ним статы для кубика!
    await db.save_choices_and_narrative(user_id, turn_data.choices, turn_data.choice_stats, full_narrative)

    # Проверка на гибель
    if player["is_dead"] or turn_data.is_dead:
        death_reason = safe_html(turn_data.death_reason or player.get("death_reason") or "Ваш путь оборвался во тьме.")
        death_text = (
            f"\n\n💀 <b>СМЕРТЬ НАСТИГЛА ГЕРОЯ</b>\n"
            f"<i>{death_reason}</i>\n"
            f"Прожито дней: <b>{player['turn_count']}</b> | Уровень: <b>{player.get('level', 1)}</b>.\n"
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
        is_in_combat=is_combat,
        has_companion=bool(active_companion)
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
    player = await db.get_player(user_id)

    # Если уже есть живой персонаж — возвращаем в текущую сцену
    if player and not player["is_dead"]:
        items_count = await db.get_inventory_count(user_id)
        active_companion = await db.get_active_companion(user_id)
        choices, choice_stats, last_narrative = await db.get_saved_choices_and_narrative(user_id)
        if not choices:
            choices = ["Осмотреться вокруг", "Проверить снаряжение", "Двигаться вперед"]
            choice_stats = ["int", "int", "agi"]

        status = gl.format_status_header(player, items_count, active_companion)
        narrative_to_show = last_narrative if last_narrative else "Вы продолжаете своё мрачное путешествие."

        await message.answer(
            f"⚔️ <b>Хроники Вересковых Земель</b>\n"
            f"С возвращением, {safe_html(player['class_title'])}!\n\n"
            f"{status}\n"
            f"{narrative_to_show}",
            reply_markup=kb.get_game_turn_keyboard(
                choices,
                choice_stats=choice_stats,
                is_in_combat=bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0),
                has_companion=bool(active_companion)
            ),
            parse_mode="HTML"
        )
        return

    # Экран создания нового героя: Шаг 1 — Класс
    welcome_text = (
        "⚔️ <b>ТЁМНЫЙ ВЕК: САГА О ВЫЖИВАНИИ</b>\n\n"
        "<i>На дворе 1349 год от Рождества Христова. По дорогам Старого Света рыщет Чёрная Смерть, "
        "а в глухих лесах шепчутся о древних проклятиях. Здесь нет бессмертных избранников — "
        "каждое слово и взмах клинка могут стать последними.</i>\n\n"
        "<b>Шаг 1 из 2:</b> Выберите боевое ремесло героя:"
    )
    await message.answer(welcome_text, reply_markup=kb.get_class_selection_keyboard(), parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 <b>РУКОВОДСТВО ПО ВЫЖИВАНИЮ:</b>\n\n"
        "• <b>Живые диалоги и персонажи:</b>\n"
        "  Вы можете свободно общаться с NPC и спутниками! Нажмите «✍️ Своё действие / 🗣️ Сказать персонажу» "
        "  и напишите свою реплику прямым текстом. Персонажи слышат вас, реагируют на слова и помнят отношение к ним.\n\n"
        "• <b>Спутники и романтика:</b>\n"
        "  В трактирах и на дорогах вы встретите попутчиков. Поддерживая их и разделяя трапезу, вы строите "
        "  дружбу и симпатию (от ❄️ Недоверия до 🛡️ Верного товарища и ❤️ Любви). Спутники защищают вас в боях и делятся тайнами.\n\n"
        "• <b>Кубик d20 и характеристики:</b>\n"
        "  Каждое рискованное действие бросает кубик d20 + модификатор (Сила, Ловкость, Интеллект, Красноречие):\n"
        "  - <i>1 — Критический провал</i> (поломка, тяжелая травма).\n"
        "  - <i>2–9 — Неудача</i> (урон, промах, срыв замысла).\n"
        "  - <i>10–14 — Частичный успех</i> (цель достигнута, но с потерями).\n"
        "  - <i>15–19 — Полный успех</i> (чистое исполнение без урона).\n"
        "  - <i>20 — Критический триумф</i> (смертоносный удар, редкий трофей).\n\n"
        "• <b>Рассудок и лагерь:</b>\n"
        "  Берегите рассудок 🧠. Если он упадет ниже 35, героя настигнут морок и галлюцинации. "
        "  Делайте ⛺ Привал, чтобы развести костер, согреться и залечить раны."
    )
    await message.answer(help_text, parse_mode="HTML")

@dp.callback_query(F.data == "back_to_class_select")
async def cb_back_to_class(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    welcome_text = (
        "⚔️ <b>ТЁМНЫЙ ВЕК: САГА О ВЫЖИВАНИИ</b>\n\n"
        "<b>Шаг 1 из 2:</b> Выберите боевое ремесло героя:"
    )
    await safe_edit_message(callback.message, welcome_text, reply_markup=kb.get_class_selection_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("class:"))
async def handle_class_selection(callback: CallbackQuery, state: FSMContext):
    """Шаг 2 создания персонажа: выбор предыстории"""
    await state.clear()
    class_key = callback.data.split(":")[1]
    class_info = gl.CLASSES.get(class_key)
    if not class_info:
        await callback.answer("Неизвестный класс!", show_alert=True)
        return

    text = (
        f"🎭 <b>Вы выбрали: {class_info['title']} ({class_info['name']})</b>\n"
        f"<i>{class_info['desc']}</i>\n\n"
        f"<b>Шаг 2 из 2:</b> Какое бремя, грех или тайна тяготят душу вашего героя?\n"
        f"Это определит завязку сюжета, вашу главную цель и уникальный стартовый предмет:"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_background_selection_keyboard(class_key))
    await callback.answer()

@dp.callback_query(F.data.startswith("bg:"))
async def handle_background_selection(callback: CallbackQuery, state: FSMContext):
    """Создание персонажа с предысторией и генерация кинематографичного пролога"""
    await state.clear()
    user_id = callback.from_user.id

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка выбора!", show_alert=True)
        return

    class_key, bg_key = parts[1], parts[2]
    class_info = gl.CLASSES.get(class_key)
    bg_info = gl.BACKGROUNDS.get(bg_key)

    if not class_info or not bg_info:
        await callback.answer("Данные не найдены!", show_alert=True)
        return

    async with user_locks[user_id]:
        username = callback.from_user.username or callback.from_user.first_name
        await callback.message.edit_text("⏳ <i>Летописец затачивает гусиное перо... Рождается ваша судьба...</i>", parse_mode="HTML")
        await callback.bot.send_chat_action(callback.message.chat.id, "typing")

        # Формируем стартовые предметы (класс + бонусный предмет предыстории)
        start_items = list(class_info["items"])
        if bg_info.get("bonus_item") and bg_info["bonus_item"] not in start_items:
            start_items.append(bg_info["bonus_item"])

        # Модификаторы статов
        str_stat = class_info["str"] + (1 if bg_info.get("bonus_stat") == "str" else 0)
        agi_stat = class_info["agi"] + (1 if bg_info.get("bonus_stat") == "agi" else 0)
        int_stat = class_info["int"] + (1 if bg_info.get("bonus_stat") == "int" else 0)

        player = await db.create_player(
            user_id=user_id,
            username=username,
            class_name=class_info["name"],
            class_title=class_info["title"],
            background=f"{bg_info['title']}: {bg_info['desc']}",
            main_quest=bg_info["quest"],
            hp=class_info["hp"],
            sanity=class_info["sanity"],
            gold=class_info["gold"],
            str_stat=str_stat,
            agi_stat=agi_stat,
            int_stat=int_stat,
            start_items=start_items
        )

        # Генерация сочного художественного пролога
        prologue = await gs.generate_prologue(
            class_title=class_info["title"],
            class_name=class_info["name"],
            background_title=bg_info["title"],
            background_desc=bg_info["desc"],
            main_quest=bg_info["quest"],
            start_items=start_items
        )

        await db.save_turn_history(user_id, "Начало саги", prologue.narrative, 1)
        if prologue.key_memory:
            await db.add_chronicle_entry(user_id, 1, prologue.key_memory)

        if prologue.active_npc:
            n = prologue.active_npc
            await db.save_or_update_npc(
                user_id=user_id,
                name=n.name,
                title=n.title,
                temperament=n.temperament,
                speech_style=n.speech_style,
                quirks=n.quirks,
                hidden_motive=n.hidden_motive,
                system_prompt=n.system_persona_prompt
            )

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

    if user_locks[user_id].locked():
        await callback.answer("⏳ Гейм-Мастер оценивает поступок...", show_alert=False)
        return

    async with user_locks[user_id]:
        param = callback.data.split(":")[1]
        player = await db.get_player(user_id)
        if not player or player["is_dead"]:
            await callback.answer("Персонаж погиб. Начните с /start", show_alert=True)
            return

        choices, choice_stats, _ = await db.get_saved_choices_and_narrative(user_id)
        stat_hint = None

        if param == "retreat":
            action_text = "Пытаюсь спешно разорвать дистанцию и отступить в укрытие"
            stat_hint = "agi"
        else:
            try:
                choice_idx = int(param)
                action_text = choices[choice_idx] if choice_idx < len(choices) else "Действовать осмотрительно"
                stat_hint = choice_stats[choice_idx] if choice_idx < len(choice_stats) else None
            except Exception:
                action_text = "Действовать осмотрительно"
                stat_hint = None

        await callback.answer("🎲 Бросок кубика...")
        await callback.bot.send_chat_action(callback.message.chat.id, "typing")

        await execute_game_turn(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            user_id=user_id,
            action_text=action_text,
            stat_hint=stat_hint,
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
        "✍️ <b>Свобода действий и живая речь:</b>\n"
        "Опишите свой поступок или напишите прямую речь героям.\n\n"
        "<i>Примеры:</i>\n"
        "• <i>«Подсаживаюсь к послушнице и тихо спрашиваю: Кто тебя напугал, дитя?»</i>\n"
        "• <i>«Опрокидываю дубовый стол перед наемниками и обнажаю сталь»</i>\n"
        "• <i>«Осматриваю сапоги путника: нет ли на них болотной тины?»</i>",
        reply_markup=kb.get_cancel_custom_action_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(GameStates.waiting_for_custom_action, F.text)
async def handle_custom_action_text(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    action_text = message.text.strip()[:280]

    if not action_text:
        return

    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await message.answer("💀 Герой погиб. Нажмите /start для новой саги.")
        return

    async with user_locks[user_id]:
        await message.bot.send_chat_action(message.chat.id, "typing")
        wait_msg = await message.answer("🎲 <i>Гейм-Мастер слушает ваши слова и бросает кубик...</i>", parse_mode="HTML")
        await execute_game_turn(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=user_id,
            action_text=action_text,
            stat_hint=None,
            progress_message=wait_msg
        )

@dp.message(GameStates.waiting_for_custom_action)
async def handle_custom_action_non_text(message: Message):
    await message.reply(
        "⚠️ Пожалуйста, опишите ваше действие обычным текстом (стикеры и медиа не поддерживаются).",
        reply_markup=kb.get_cancel_custom_action_keyboard()
    )

async def execute_game_turn(
    bot: Bot,
    chat_id: int,
    user_id: int,
    action_text: str,
    stat_hint: Optional[str] = None,
    progress_message: Message = None
):
    """Выполнение игрового раунда: d20, нейросеть, урон, спутники, квест и опыт"""
    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        return

    # 1. Бросок кубика d20 с ПРЯМЫМ учетом stat_hint (исправлен баг обнуления статов!)
    raw_roll, total_roll, dice_verdict = gl.roll_dice_for_action(action_text, player, stat_hint=stat_hint)

    # 2. Подгружаем контекст: инвентарь, спутника, известных NPC, хронику и историю
    items_list = [it["item_name"] for it in await db.get_inventory_items(user_id)]
    active_companion = await db.get_active_companion(user_id)
    known_npcs = await db.get_npcs(user_id, limit=5)
    chronicle = await db.get_chronicle(user_id, limit=6)
    recent_history = await db.get_recent_turns(user_id)

    # 3. Вызов Gemini API
    turn_output = await gs.generate_turn(
        player=player,
        inventory=items_list,
        chronicle=chronicle,
        recent_history=recent_history,
        active_companion=active_companion,
        known_npcs=known_npcs,
        action_text=action_text,
        dice_verdict=dice_verdict
    )

    if not turn_output:
        if progress_message:
            try:
                await progress_message.delete()
            except Exception:
                pass
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ <i>Связь с Гейм-Мастером на миг затуманилась (сбой квоты API). Ваш персонаж настороже. Повторите попытку.</i>",
            reply_markup=kb.get_game_turn_keyboard(
                choices=["Осмотреться вокруг", "Проверить оружие", "Осторожно сделать шаг"],
                is_in_combat=bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0),
                has_companion=bool(active_companion)
            ),
            parse_mode="HTML"
        )
        return

    # 4. Обновление инвентаря
    for item in turn_output.items_added:
        await db.add_item(user_id, item)
    for item in turn_output.items_removed:
        await db.remove_item(user_id, item)

    # 5. Боевая система: расчет урона по противнику
    if turn_output.is_in_combat:
        enemy_name = turn_output.enemy_name or player.get("enemy_name") or "Враг"
        enemy_max = turn_output.enemy_max_hp if turn_output.enemy_max_hp > 0 else player.get("enemy_max_hp", 60)
        current_enemy_hp = player.get("enemy_hp", enemy_max) if player.get("enemy_hp", 0) > 0 else enemy_max

        # Учитываем оружие игрока (бонус к урону)
        weapon_bonus = 0
        for it_name in items_list:
            if it_name in gl.EQUIPMENT_DATA and gl.EQUIPMENT_DATA[it_name].get("type") == "weapon":
                weapon_bonus = max(weapon_bonus, gl.EQUIPMENT_DATA[it_name].get("dmg_bonus", 0))

        dmg = abs(turn_output.enemy_hp_change)
        if dmg > 0 and weapon_bonus > 0:
            dmg += weapon_bonus

        current_enemy_hp = max(0, current_enemy_hp - dmg)

        if current_enemy_hp <= 0:
            await db.update_combat_state(user_id, None, 0, 0)
            turn_output.xp_gained += 45
        else:
            await db.update_combat_state(user_id, enemy_name, current_enemy_hp, enemy_max)
    else:
        await db.update_combat_state(user_id, None, 0, 0)

    # 6. Учет брони (снижение входящего урона)
    if turn_output.hp_change < 0:
        armor_reduction = 0
        for it_name in items_list:
            if it_name in gl.EQUIPMENT_DATA and gl.EQUIPMENT_DATA[it_name].get("type") == "armor":
                armor_reduction = max(armor_reduction, gl.EQUIPMENT_DATA[it_name].get("dmg_reduction", 0))
        if armor_reduction > 0:
            # Снижаем потерю HP, но не делаем её положительной
            turn_output.hp_change = min(-1, turn_output.hp_change + armor_reduction)

    # 7. Спутники и отношения
    companion_note = ""
    # Новый спутник присоединился
    if turn_output.new_companion and not active_companion:
        nc = turn_output.new_companion
        new_comp = await db.add_companion(
            user_id=user_id,
            name=nc.name,
            title=nc.title,
            archetype=nc.archetype,
            personality=nc.personality,
            initial_affinity=nc.initial_affinity
        )
        if new_comp:
            companion_note = f"🤝 К вам присоединился спутник: <b>{safe_html(nc.name)}</b> ({safe_html(nc.title)})!"

    # Реакция существующего спутника
    elif turn_output.companion_event and active_companion:
        ev = turn_output.companion_event
        if ev.action_type == "left":
            await db.remove_companion(user_id, active_companion["name"])
            companion_note = f"💔 Спутник <b>{safe_html(active_companion['name'])}</b> покинул ваш отряд!"
        else:
            _, aff_msg = await db.update_companion_affinity(user_id, active_companion["name"], ev.affinity_change)
            quote = f" — «<i>{safe_html(ev.comment)}</i>»" if ev.comment else ""
            companion_note = f"{aff_msg}{quote}"

    # 8. Обновление главной сюжетной цели
    if turn_output.main_quest_update:
        await db.update_main_quest(user_id, turn_output.main_quest_update)

    # 9. Сохранение уникального профайла и промпта NPC
    if turn_output.active_npc:
        n = turn_output.active_npc
        await db.save_or_update_npc(
            user_id=user_id,
            name=n.name,
            title=n.title,
            temperament=n.temperament,
            speech_style=n.speech_style,
            quirks=n.quirks,
            hidden_motive=n.hidden_motive,
            system_prompt=n.system_persona_prompt
        )

    # 10. Прокачка и опыт (XP)
    new_xp, new_lvl, did_level_up = await db.add_xp(user_id, turn_output.xp_gained)

    # 10. Обновление характеристик игрока
    updated_player = await db.update_player_state(
        user_id=user_id,
        hp_delta=turn_output.hp_change,
        sanity_delta=turn_output.sanity_change,
        gold_delta=turn_output.gold_change,
        location=turn_output.location_name,
        is_dead=turn_output.is_dead,
        death_reason=turn_output.death_reason
    )

    # 11. Запись в историю
    await db.save_turn_history(user_id, action_text, turn_output.narrative, updated_player["turn_count"])
    if turn_output.key_memory:
        await db.add_chronicle_entry(user_id, updated_player["turn_count"], turn_output.key_memory)

    if progress_message:
        try:
            await progress_message.delete()
        except Exception:
            pass

    # 12. Отправка результата
    await send_turn_message(
        bot=bot,
        chat_id=chat_id,
        user_id=user_id,
        turn_data=turn_output,
        dice_verdict=dice_verdict,
        companion_note=companion_note
    )

    # 13. Если Level Up
    if did_level_up and not updated_player["is_dead"]:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚡ <b>ПОВЫШЕНИЕ УРОВНЯ! (Уровень {new_lvl})</b>\n\n"
                f"Испытания закалили тело и дух: доступно очко усиления.\n"
                f"Выберите характеристику для распределения:"
            ),
            reply_markup=kb.get_level_up_keyboard(updated_player.get("stat_points", 1)),
            parse_mode="HTML"
        )

# --- Обработка прокачки (Level Up) ---

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
            f"Текущие параметры:\n"
            f"• Сила: <b>{player['str_stat']:+d}</b> | Ловкость: <b>{player['agi_stat']:+d}</b> | Интеллект: <b>{player['int_stat']:+d}</b>"
        )

        if player.get("stat_points", 0) > 0:
            msg_text += f"\n\n⚡ <i>Осталось очков прокачки: {player['stat_points']}</i>"
            await safe_edit_message(callback.message, msg_text, reply_markup=kb.get_level_up_keyboard(player['stat_points']))
        else:
            await safe_edit_message(callback.message, msg_text, reply_markup=kb.get_main_menu_keyboard(is_dead=False))

        await callback.answer("Уровень повышен!")

# --- Меню спутников и общение ---

@dp.callback_query(F.data == "show_companions")
async def cb_show_companions(callback: CallbackQuery):
    user_id = callback.from_user.id
    companions = await db.get_companions(user_id)

    if not companions:
        text = (
            "👥 <b>ВАШИ СПУТНИКИ</b>\n\n"
            "<i>Вы странствуете в одиночестве. Однако мир полон беглецов, наемников и монахов, "
            "ищущих надежного попутчика. Прислушивайтесь к разговорам в трактирах и помогайте тем, кто попал в беду.</i>"
        )
        await safe_edit_message(callback.message, text, reply_markup=kb.get_camp_keyboard(has_companion=False))
        await callback.answer()
        return

    text = (
        "👥 <b>ОТРЯД И СПУТНИКИ:</b>\n\n"
        "Нажмите на спутника, чтобы побеседовать по душам, узнать его историю или угостить припасами:"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_companions_keyboard(companions))
    await callback.answer()

@dp.callback_query(F.data.startswith("companion:"))
async def cb_companion_detail(callback: CallbackQuery):
    comp_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    companions = await db.get_companions(user_id)
    comp = next((c for c in companions if c["id"] == comp_id), None)

    if not comp:
        await callback.answer("Спутник не найден!", show_alert=True)
        return

    status_text, icon, aff_bar = gl.get_affinity_status(comp.get("affinity", 50))
    text = (
        f"👤 <b>{safe_html(comp['name'])}</b> ({safe_html(comp.get('title', 'Спутник'))})\n"
        f"Роль: <i>{safe_html(comp.get('archetype', 'Бродяга'))}</i>\n\n"
        f"<b>Характер:</b> <i>{safe_html(comp.get('personality', 'Скрытный'))}</i>\n\n"
        f"<b>Отношения к вам:</b>\n"
        f"{icon} <b>{status_text}</b> [{comp.get('affinity', 50)}%]\n"
        f"{aff_bar}\n\n"
        f"<i>💡 Искренние беседы у костра и совместные опасности сближают вас.</i>"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_companion_detail_keyboard(comp_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("comp_talk:"))
async def cb_comp_talk_prompt(callback: CallbackQuery, state: FSMContext):
    comp_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    companions = await db.get_companions(user_id)
    comp = next((c for c in companions if c["id"] == comp_id), None)

    if not comp:
        await callback.answer("Спутник не найден!", show_alert=True)
        return

    await state.set_state(GameStates.waiting_for_companion_talk)
    await state.update_data(target_companion=comp["name"])

    await callback.message.reply(
        f"💬 <b>Беседа с {safe_html(comp['name'])}:</b>\n"
        f"Напишите прямо сейчас, что вы хотите сказать, спросить или предложить спутнику.\n\n"
        f"<i>Например: «Расскажи, Беатриса, почему инквизиция охотится за тобой?» или «Держись позади меня, я прикрою».</i>",
        reply_markup=kb.get_cancel_custom_action_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(GameStates.waiting_for_companion_talk, F.text)
async def handle_companion_talk_text(message: Message, state: FSMContext):
    data = await state.get_data()
    comp_name = data.get("target_companion", "спутник")
    await state.clear()

    user_id = message.from_user.id
    user_text = message.text.strip()[:280]

    if not user_text:
        return

    action_text = f"Обращаюсь к спутнику ({comp_name}): «{user_text}»"

    async with user_locks[user_id]:
        await message.bot.send_chat_action(message.chat.id, "typing")
        wait_msg = await message.answer(f"💬 <i>{comp_name} слушает ваши слова...</i>", parse_mode="HTML")
        await execute_game_turn(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=user_id,
            action_text=action_text,
            stat_hint="speech",
            progress_message=wait_msg
        )

@dp.callback_query(F.data.startswith("comp_gift:"))
async def cb_comp_gift(callback: CallbackQuery):
    comp_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    companions = await db.get_companions(user_id)
    comp = next((c for c in companions if c["id"] == comp_id), None)

    if not comp:
        await callback.answer("Спутник не найден!", show_alert=True)
        return

    # Проверяем, есть ли еда или монеты
    inv = await db.get_inventory_items(user_id)
    food_item = next((it for it in inv if "хлеб" in it["item_name"].lower() or "сало" in it["item_name"].lower() or "брага" in it["item_name"].lower()), None)

    player = await db.get_player(user_id)

    if food_item:
        await db.remove_item(user_id, food_item["item_name"], 1)
        updated_comp, msg = await db.update_companion_affinity(user_id, comp["name"], delta=10)
        await callback.answer(f"Вы разделили трапезу: {food_item['item_name']} (+10% симпатии)!", show_alert=True)
    elif player["gold"] >= 5:
        await db.update_player_state(user_id, hp_delta=0, sanity_delta=0, gold_delta=-5)
        updated_comp, msg = await db.update_companion_affinity(user_id, comp["name"], delta=8)
        await callback.answer(f"Вы купили кружку горячего сбитня для {comp['name']} (-5 монет, +8% симпатии)!", show_alert=True)
    else:
        await callback.answer("У вас нет припасов или монет, чтобы угостить спутника!", show_alert=True)
        return

    # Обновляем карточку спутника
    status_text, icon, aff_bar = gl.get_affinity_status(updated_comp.get("affinity", 50))
    text = (
        f"👤 <b>{safe_html(updated_comp['name'])}</b> ({safe_html(updated_comp.get('title', 'Спутник'))})\n\n"
        f"💖 <i>{safe_html(updated_comp['name'])} с благодарностью принимает вашу заботу. Лед в сердце тает.</i>\n\n"
        f"<b>Отношения к вам:</b>\n"
        f"{icon} <b>{status_text}</b> [{updated_comp.get('affinity', 50)}%]\n"
        f"{aff_bar}"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_companion_detail_keyboard(comp_id))

# --- Лагерь и привал (замена нелепой вечной лавки) ---

@dp.callback_query(F.data == "show_camp")
async def cb_show_camp(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await callback.answer("Мертвецы не отдыхают.", show_alert=True)
        return

    if player.get("enemy_name") and player.get("enemy_hp", 0) > 0:
        await callback.answer("⚔️ Нельзя разбить лагерь в разгар смертельного боя!", show_alert=True)
        return

    active_companion = await db.get_active_companion(user_id)
    comp_line = f"Рядом с вами греется у костра <b>{safe_html(active_companion['name'])}</b>." if active_companion else "Вы наедине со своими мыслями."

    text = (
        f"⛺ <b>ПРИВАЛ У КОСТРА</b>\n\n"
        f"Потрескивают сухие сучья, разгоняя промозглую ночную тьму. {comp_line}\n"
        f"Здесь можно перевести дыхание, согреться горячей похлебкой и перевязать ноющие раны.\n\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 | 🧠 <b>Рассудок:</b> {player['sanity']}/100"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_camp_keyboard(has_companion=bool(active_companion)))
    await callback.answer()

@dp.callback_query(F.data == "camp_rest")
async def cb_camp_rest(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    if not player or player["is_dead"]:
        await callback.answer("Мертвецы не отдыхают.", show_alert=True)
        return

    success, msg = await db.rest_at_camp(user_id)
    updated_player = await db.get_player(user_id)
    active_companion = await db.get_active_companion(user_id)

    text = (
        f"⛺ <b>ПРИВАЛ У КОСТРА</b>\n\n"
        f"✅ <i>{msg}</i>\n\n"
        f"❤️ <b>Здоровье:</b> {updated_player['hp']}/100 | 🧠 <b>Рассудок:</b> {updated_player['sanity']}/100\n"
        f"🪙 <b>Монеты:</b> {updated_player['gold']}"
    )
    await safe_edit_message(callback.message, text, reply_markup=kb.get_camp_keyboard(has_companion=bool(active_companion)))
    await callback.answer("Отдых восстановил силы!")

# --- Инвентарь и использование расходников ---

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
        desc = ""
        if it["item_name"] in gl.EQUIPMENT_DATA:
            desc = f" <i>({gl.EQUIPMENT_DATA[it['item_name']]['desc']})</i>"
        items_list.append(f"• <b>{name}</b>" + (f" (x{qty})" if qty > 1 else "") + desc)

    content = "\n".join(items_list) if items_list else "<i>Пусто... Только пыль на дне мешка.</i>"

    text = (
        f"🎒 <b>ПОХОДНЫЙ МЕШОК ({len(items)}/8)</b>\n\n"
        f"🪙 <b>Звенит в кошеле:</b> {player['gold']} монет\n\n"
        f"<b>Снаряжение и припасы:</b>\n"
        f"{content}\n\n"
        f"<i>💡 Нажимайте кнопки ниже для мгновенного применения расходников:</i>"
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
            await callback.answer("Этот предмет экипирован пассивно или не расходуется.", show_alert=True)
            return

        success, msg = await db.use_consumable(user_id, item_name, effect["heal_hp"], effect["heal_san"])
        if not success:
            await callback.answer(msg, show_alert=True)
            return

        await callback.answer(f"Использовано: {item_name}!")

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

# --- Системное меню, Зал славы, Кладбище ---

@dp.callback_query(F.data == "show_main_menu")
async def cb_show_main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    player = await db.get_player(user_id)
    is_dead = bool(player and player["is_dead"])

    text = "⚙️ <b>СИСТЕМНОЕ МЕНЮ</b>\n\nВыберите необходимый раздел:"
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
            f"   └ <i>Дней: {p['turns']} | Ур. {p.get('level', 1)} | Золото: {p['gold']} {status_icon}</i>"
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
            f"   └ <i>Прожил: {d['turns_survived']} дней | Оставил: {d['gold_earned']} монет</i>"
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

    quest_text = safe_html(player.get("main_quest") or "Выжить в суровых землях")
    bg_text = safe_html(player.get("background") or "Неизвестный странник")

    text = (
        f"👤 <b>ДОСЬЕ ГЕРОЯ</b>\n\n"
        f"<b>Имя/Класс:</b> {safe_html(player['class_title'])} ({safe_html(player['class_name'])})\n"
        f"<b>Предыстория:</b> <i>{bg_text}</i>\n"
        f"<b>Главная цель:</b> 🎯 <i>{quest_text}</i>\n"
        f"<b>Уровень:</b> ⭐ {player.get('level', 1)} [{player.get('xp', 0)}/{needed_xp} XP]{lvl_extra}\n"
        f"<b>Пережито дней:</b> {player['turn_count']}\n\n"
        f"❤️ <b>Здоровье:</b> {player['hp']}/100 {hp_bar}\n"
        f"🧠 <b>Рассудок:</b> {player['sanity']}/100 {san_bar}\n"
        f"🪙 <b>Золото:</b> {player['gold']}\n\n"
        f"<b>Боевые характеристики:</b>\n"
        f"• Сила: <b>{player['str_stat']:+d}</b> (урон и напор)\n"
        f"• Ловкость: <b>{player['agi_stat']:+d}</b> (уклонение, стрельба, скрытность)\n"
        f"• Интеллект: <b>{player['int_stat']:+d}</b> (рассудок, яды, красноречие)"
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

    choices, choice_stats, narrative = await db.get_saved_choices_and_narrative(user_id)
    if not choices:
        choices = ["Осмотреться вокруг", "Проверить оружие", "Идти вперед"]
        choice_stats = ["int", "int", "agi"]
    if not narrative:
        narrative = "Вы начеку."

    active_companion = await db.get_active_companion(user_id)
    is_combat = bool(player.get("enemy_name") and player.get("enemy_hp", 0) > 0)
    await safe_edit_message(
        callback.message,
        narrative,
        reply_markup=kb.get_game_turn_keyboard(
            choices,
            choice_stats=choice_stats,
            is_in_combat=is_combat,
            has_companion=bool(active_companion)
        )
    )
    await callback.answer()

@dp.message(Command("restart"))
@dp.callback_query(F.data == "restart_game")
async def handle_restart_prompt(event, state: FSMContext):
    await state.clear()
    text = (
        "⚠️ <b>ВЫ УВЕРЕНЫ, ЧТО ХОТИТЕ НАЧАТЬ ЗАНОВО?</b>\n\n"
        "Текущий персонаж, спутники, инвентарь и характеристики будут сброшены. Имя героя сохранится в анналах истории."
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
        "<b>Шаг 1 из 2:</b> Выберите боевое ремесло нового героя:"
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
            BotCommand(command="start", description="Главный экран / Продолжить путь"),
            BotCommand(command="help", description="Правила, диалоги, спутники и механика d20"),
            BotCommand(command="top", description="Зал славы (Топ выживших)"),
            BotCommand(command="graveyard", description="Кладбище павших героев"),
            BotCommand(command="restart", description="Сбросить и создать нового героя"),
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
