import aiosqlite
from typing import Optional, List, Dict, Any
from config import DB_PATH, MAX_HP, MAX_SANITY

async def init_db():
    """Инициализация таблиц базы данных SQLite"""
    async with aiosqlite.connect(DB_PATH) as db:
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES players (user_id) ON DELETE CASCADE
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS chronicle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                turn INTEGER NOT NULL,
                event_summary TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES players (user_id) ON DELETE CASCADE
            )
        """)

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

        await db.commit()

async def get_player(user_id: int) -> Optional[Dict[str, Any]]:
    """Получить данные игрока"""
    async with aiosqlite.connect(DB_PATH) as db:
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
    """Создать нового персонажа или сбросить старого"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Удаляем старые записи если есть
        await db.execute("DELETE FROM players WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM inventory WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM chronicle WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM recent_turns WHERE user_id = ?", (user_id,))

        await db.execute("""
            INSERT INTO players (
                user_id, username, class_name, class_title, hp, sanity, gold,
                turn_count, location, str_stat, agi_stat, int_stat, is_dead
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Придорожный трактир', ?, ?, ?, 0)
        """, (user_id, username, class_name, class_title, hp, sanity, gold, str_stat, agi_stat, int_stat))

        for item in start_items:
            await db.execute(
                "INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1)",
                (user_id, item)
            )

        # Стартовая запись в летопись
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
    """Обновление характеристик игрока"""
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
            death_reason = "Смерть от тяжелых ранений."

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE players
            SET hp = ?, sanity = ?, gold = ?, turn_count = ?, location = ?,
                is_dead = ?, death_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (new_hp, new_sanity, new_gold, new_turn, new_loc, 1 if is_dead else 0, death_reason, user_id))
        await db.commit()

    return await get_player(user_id)

async def get_inventory(user_id: int) -> List[str]:
    """Список предметов игрока"""
    async with aiosqlite.connect(DB_PATH) as db:
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
    """Добавить предмет в инвентарь"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, quantity FROM inventory WHERE user_id = ? AND item_name = ?",
            (user_id, item_name)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    "UPDATE inventory SET quantity = quantity + ? WHERE id = ?",
                    (quantity, row[0])
                )
            else:
                await db.execute(
                    "INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)",
                    (user_id, item_name, quantity)
                )
        await db.commit()

async def remove_item(user_id: int, item_name: str, quantity: int = 1) -> bool:
    """Удалить или уменьшить количество предмета"""
    # Ищем частичное совпадение если название не точное
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, quantity, item_name FROM inventory WHERE user_id = ? AND (item_name = ? OR item_name LIKE ?)",
            (user_id, item_name, f"%{item_name}%")
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            item_id, current_qty, full_name = row
            if current_qty > quantity:
                await db.execute("UPDATE inventory SET quantity = quantity - ? WHERE id = ?", (quantity, item_id))
            else:
                await db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
        await db.commit()
    return True

async def add_chronicle_entry(user_id: int, turn: int, summary: str):
    """Добавить важное событие в летопись"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chronicle (user_id, turn, event_summary) VALUES (?, ?, ?)",
            (user_id, turn, summary)
        )
        await db.commit()

async def get_chronicle(user_id: int, limit: int = 10) -> List[str]:
    """Получить ключевые события летописи"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT turn, event_summary FROM chronicle WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [f"Ход {r[0]}: {r[1]}" for r in reversed(rows)]

async def save_turn_history(user_id: int, player_action: str, narrative: str, turn: int):
    """Сохранить ход в недавнюю историю (хранятся последние 6)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO recent_turns (user_id, player_action, narrative, turn) VALUES (?, ?, ?, ?)",
            (user_id, player_action, narrative, turn)
        )
        # Очищаем старые ходы, оставляя последние 6
        await db.execute("""
            DELETE FROM recent_turns
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM recent_turns WHERE user_id = ? ORDER BY id DESC LIMIT 6
            )
        """, (user_id, user_id))
        await db.commit()

async def get_recent_turns(user_id: int) -> List[Dict[str, str]]:
    """Получить недавние ходы для контекста AI"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT player_action, narrative, turn FROM recent_turns WHERE user_id = ? ORDER BY id ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
