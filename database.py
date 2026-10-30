import json
import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple
from config import DB_PATH, MAX_HP, MAX_SANITY

@asynccontextmanager
async def get_db():
    """Асинхронный контекстный менеджер SQLite с оптимизацией WAL для высокой конкурентности"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA busy_timeout = 5000;")
        await db.execute("PRAGMA synchronous = NORMAL;")
        yield db

async def init_db():
    """Инициализация базы данных и автоматические миграции"""
    async with get_db() as db:
        # Основная таблица персонажей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                class_name TEXT NOT NULL,
                class_title TEXT NOT NULL,
                hp INTEGER NOT NULL DEFAULT 100,
                sanity INTEGER NOT NULL DEFAULT 100,
                gold INTEGER NOT NULL DEFAULT 10,
                turn_count INTEGER NOT NULL DEFAULT 1,
                location TEXT NOT NULL DEFAULT 'Придорожный трактир',
                str_stat INTEGER NOT NULL DEFAULT 0,
                agi_stat INTEGER NOT NULL DEFAULT 0,
                int_stat INTEGER NOT NULL DEFAULT 0,
                is_dead INTEGER NOT NULL DEFAULT 0,
                death_reason TEXT,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                enemy_name TEXT DEFAULT NULL,
                enemy_hp INTEGER NOT NULL DEFAULT 0,
                enemy_max_hp INTEGER NOT NULL DEFAULT 0,
                current_choices TEXT DEFAULT '[]',
                last_narrative TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция колонок для существующих БД
        cursor = await db.execute("PRAGMA table_info(players)")
        columns = [row[1] for row in await cursor.fetchall()]

        new_columns = [
            ("xp", "INTEGER NOT NULL DEFAULT 0"),
            ("level", "INTEGER NOT NULL DEFAULT 1"),
            ("enemy_name", "TEXT DEFAULT NULL"),
            ("enemy_hp", "INTEGER NOT NULL DEFAULT 0"),
            ("enemy_max_hp", "INTEGER NOT NULL DEFAULT 0"),
            ("current_choices", "TEXT DEFAULT '[]'"),
            ("last_narrative", "TEXT DEFAULT ''"),
        ]

        for col_name, col_type in new_columns:
            if col_name not in columns:
                await db.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type};")

        # Таблица инвентаря
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES players (user_id) ON DELETE CASCADE
            )
        """)

        # Таблица летописи ключевых решений
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chronicle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                event_summary TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES players (user_id) ON DELETE CASCADE
            )
        """)

        # Таблица недавних ходов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recent_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                player_action TEXT NOT NULL,
                narrative TEXT NOT NULL,
                turn INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES players (user_id) ON DELETE CASCADE
            )
        """)

        # Таблица «Кладбище павших героев» (Глобальный архив смертей)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS graveyard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                class_title TEXT NOT NULL,
                turns_survived INTEGER NOT NULL,
                gold_earned INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                death_reason TEXT NOT NULL,
                died_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()

async def get_player(user_id: int) -> Optional[Dict[str, Any]]:
    """Получить актуальные данные персонажа"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def create_player(
    user_id: int,
    username: str,
    class_name: str,
    class_title: str,
    hp: int,
    sanity: int,
    gold: int,
    str_stat: int,
    agi_stat: int,
    int_stat: int,
    start_items: List[str]
) -> Dict[str, Any]:
    """Создать нового персонажа с полной очисткой старого состояния"""
    async with get_db() as db:
        await db.execute("DELETE FROM players WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM inventory WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM chronicle WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM recent_turns WHERE user_id = ?", (user_id,))

        await db.execute("""
            INSERT INTO players (
                user_id, username, class_name, class_title, hp, sanity, gold,
                turn_count, location, str_stat, agi_stat, int_stat, is_dead,
                xp, level, enemy_name, enemy_hp, enemy_max_hp, current_choices, last_narrative
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Придорожный трактир', ?, ?, ?, 0, 0, 1, NULL, 0, 0, '[]', '')
        """, (user_id, username, class_name, class_title, hp, sanity, gold, str_stat, agi_stat, int_stat))

        for item in start_items:
            await db.execute(
                "INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1)",
                (user_id, item)
            )

        await db.execute(
            "INSERT INTO chronicle (user_id, turn, event_summary) VALUES (?, 1, ?)",
            (user_id, f"Начал свой путь как {class_title} в придорожном трактире.")
        )
        await db.commit()

    return await get_player(user_id)

async def update_player_state(
    user_id: int,
    hp_delta: int,
    sanity_delta: int,
    gold_delta: int,
    location: Optional[str] = None,
    is_dead: bool = False,
    death_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Обновление характеристик персонажа"""
    player = await get_player(user_id)
    if not player:
        raise ValueError("Player not found")

    new_hp = max(0, min(MAX_HP, player["hp"] + hp_delta))
    new_sanity = max(0, min(MAX_SANITY, player["sanity"] + sanity_delta))
    new_gold = max(0, player["gold"] + gold_delta)
    new_turn = player["turn_count"] + 1
    new_loc = location if location else player["location"]

    if new_hp <= 0:
        is_dead = True
        if not death_reason:
            death_reason = "Смерть от несовместимых с жизнью ран."

    async with get_db() as db:
        await db.execute("""
            UPDATE players
            SET hp = ?, sanity = ?, gold = ?, turn_count = ?, location = ?,
                is_dead = ?, death_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (new_hp, new_sanity, new_gold, new_turn, new_loc, 1 if is_dead else 0, death_reason, user_id))
        await db.commit()

    # Если герой погиб — увековечиваем его на кладбище
    if is_dead:
        await record_death(
            user_id=user_id,
            username=player.get("username", "Неизвестный"),
            class_title=player["class_title"],
            turns=new_turn,
            gold=new_gold,
            level=player.get("level", 1),
            death_reason=death_reason or "Погиб в безвестности."
        )

    return await get_player(user_id)

async def save_choices_and_narrative(user_id: int, choices: List[str], narrative: str):
    """Сохранение кнопок и текста в БД (неубиваемость при перезагрузке бота)"""
    async with get_db() as db:
        await db.execute(
            "UPDATE players SET current_choices = ?, last_narrative = ? WHERE user_id = ?",
            (json.dumps(choices, ensure_ascii=False), narrative, user_id)
        )
        await db.commit()

async def get_saved_choices_and_narrative(user_id: int) -> Tuple[List[str], str]:
    """Получение сохраненных кнопок и текста из SQLite"""
    player = await get_player(user_id)
    if not player:
        return [], ""
    try:
        choices = json.loads(player.get("current_choices") or "[]")
    except Exception:
        choices = []
    narrative = player.get("last_narrative") or ""
    return choices, narrative

async def update_combat_state(user_id: int, enemy_name: Optional[str], enemy_hp: int, enemy_max_hp: int):
    """Обновление статуса боя с боссом/врагом"""
    async with get_db() as db:
        await db.execute("""
            UPDATE players
            SET enemy_name = ?, enemy_hp = ?, enemy_max_hp = ?
            WHERE user_id = ?
        """, (enemy_name, max(0, enemy_hp), enemy_max_hp, user_id))
        await db.commit()

async def add_xp(user_id: int, xp_amount: int) -> Tuple[int, int, bool]:
    """Начисление опыта и проверка Level Up. Возвращает (xp, level, did_level_up)"""
    player = await get_player(user_id)
    if not player or xp_amount <= 0:
        return 0, 1, False

    current_xp = player.get("xp", 0) + xp_amount
    current_lvl = player.get("level", 1)
    xp_needed = current_lvl * 100

    did_level_up = False
    if current_xp >= xp_needed:
        current_lvl += 1
        current_xp -= xp_needed
        did_level_up = True

    async with get_db() as db:
        await db.execute(
            "UPDATE players SET xp = ?, level = ? WHERE user_id = ?",
            (current_xp, current_lvl, user_id)
        )
        await db.commit()

    return current_xp, current_lvl, did_level_up

async def level_up_stat(user_id: int, stat_choice: str) -> Dict[str, Any]:
    """Прокачка характеристики при повышении уровня + частичное исцеление"""
    player = await get_player(user_id)
    if not player:
        raise ValueError("Player not found")

    new_str = player["str_stat"] + (1 if stat_choice == "str" else 0)
    new_agi = player["agi_stat"] + (1 if stat_choice == "agi" else 0)
    new_int = player["int_stat"] + (1 if stat_choice == "int" else 0)

    # Бонус за уровень: +25 HP и +25 Sanity
    new_hp = min(MAX_HP, player["hp"] + 25)
    new_sanity = min(MAX_SANITY, player["sanity"] + 25)

    async with get_db() as db:
        await db.execute("""
            UPDATE players
            SET str_stat = ?, agi_stat = ?, int_stat = ?, hp = ?, sanity = ?
            WHERE user_id = ?
        """, (new_str, new_agi, new_int, new_hp, new_sanity, user_id))
        await db.commit()

    return await get_player(user_id)

async def record_death(user_id: int, username: str, class_title: str, turns: int, gold: int, level: int, death_reason: str):
    """Запись павшего героя на Кладбище"""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO graveyard (user_id, username, class_title, turns_survived, gold_earned, level, death_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, class_title, turns, gold, level, death_reason))
        await db.commit()

async def get_hall_of_fame(limit: int = 10) -> List[Dict[str, Any]]:
    """Топ-10 самых живучих героев всех времен"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT username, class_title, turn_count as turns, gold, level, is_dead
            FROM players
            ORDER BY turn_count DESC, level DESC, gold DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_graveyard(limit: int = 10) -> List[Dict[str, Any]]:
    """Последние 10 погибших персонажей"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT username, class_title, turns_survived, gold_earned, level, death_reason, died_at
            FROM graveyard
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# --- Инвентарь и торговля ---

async def get_inventory(user_id: int) -> List[str]:
    async with get_db() as db:
        async with db.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            items = []
            for name, qty in rows:
                if qty > 1:
                    items.append(f"{name} (x{qty})")
                else:
                    items.append(name)
            return items

async def add_item(user_id: int, item_name: str, quantity: int = 1):
    async with get_db() as db:
        async with db.execute(
            "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?",
            (user_id, item_name)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                await db.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?", (quantity, row[0]))
            else:
                await db.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (user_id, item_name, quantity))
        await db.commit()

async def remove_item(user_id: int, item_name: str, quantity: int = 1) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT id, quantity FROM inventory WHERE user_id = ? AND (item_name = ? OR item_name LIKE ?)",
            (user_id, item_name, f"%{item_name}%")
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            item_id, current_qty = row[0], row[1]
            if current_qty > quantity:
                await db.execute("UPDATE inventory SET quantity = quantity - ? WHERE id = ?", (quantity, item_id))
            else:
                await db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
        await db.commit()
    return True

async def buy_shop_item(user_id: int, item_name: str, cost: int) -> Tuple[bool, str]:
    """Покупка предмета в лавке"""
    player = await get_player(user_id)
    if not player:
        return False, "Персонаж не найден"
    if player["gold"] < cost:
        return False, f"Недостаточно монет! Требуется {cost}, у вас {player['gold']}."

    async with get_db() as db:
        await db.execute("UPDATE players SET gold = gold - ? WHERE user_id = ?", (cost, user_id))
        await db.commit()

    await add_item(user_id, item_name, 1)
    return True, f"Вы приобрели <b>{item_name}</b> за {cost} монет!"

# --- Хроника и история ---

async def add_chronicle_entry(user_id: int, turn: int, summary: str):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO chronicle (user_id, turn, event_summary) VALUES (?, ?, ?)",
            (user_id, turn, summary)
        )
        await db.commit()

async def get_chronicle(user_id: int, limit: int = 10) -> List[str]:
    async with get_db() as db:
        async with db.execute(
            "SELECT turn, event_summary FROM chronicle WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [f"Ход {r[0]}: {r[1]}" for r in reversed(rows)]

async def save_turn_history(user_id: int, player_action: str, narrative: str, turn: int):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO recent_turns (user_id, player_action, narrative, turn) VALUES (?, ?, ?, ?)",
            (user_id, player_action, narrative, turn)
        )
        await db.execute("""
            DELETE FROM recent_turns
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM recent_turns WHERE user_id = ? ORDER BY id DESC LIMIT 6
            )
        """, (user_id, user_id))
        await db.commit()

async def get_recent_turns(user_id: int) -> List[Dict[str, str]]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT player_action, narrative, turn FROM recent_turns WHERE user_id = ? ORDER BY id ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
