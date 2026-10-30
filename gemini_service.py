import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

class GameTurnOutput(BaseModel):
    narrative: str = Field(description="Художественное описание последствий действия и текущей ситуации в темном средневековом стиле (до 500 знаков). Сочное, живое, без лишней воды.")
    hp_change: int = Field(default=0, ge=-40, le=30, description="Изменение здоровья игрока (-40 до +30).")
    sanity_change: int = Field(default=0, ge=-30, le=25, description="Изменение рассудка (-30 до +25).")
    gold_change: int = Field(default=0, ge=-60, le=60, description="Изменение золота (-60 до +60).")
    items_added: List[str] = Field(default_factory=list, description="Полученные предметы (максимум 2).")
    items_removed: List[str] = Field(default_factory=list, description="Потерянные или истраченные предметы.")
    location_name: str = Field(default="Вересковые пустоши", description="Короткое название локации.")
    
    # Боевая система и боссы
    is_in_combat: bool = Field(default=False, description="Идет ли активный бой с конкретным врагом или боссом.")
    enemy_name: Optional[str] = Field(default=None, description="Имя врага/босса (например: Чумной волк, Инквизитор).")
    enemy_max_hp: int = Field(default=0, ge=0, le=120, description="Максимальное здоровье врага при первой встрече (40-80 HP).")
    enemy_hp_change: int = Field(default=0, description="Урон по врагу от удара игрока (отрицательное число, например -20).")

    # Прокачка
    xp_gained: int = Field(default=10, ge=0, le=60, description="Опыт за преодоление опасности (10-40 XP).")

    is_dead: bool = Field(default=False, description="Погиб ли персонаж.")
    death_reason: Optional[str] = Field(default=None, description="Краткая причина смерти, если персонаж погиб.")
    choices: List[str] = Field(description="Ровно 3-4 интригующих варианта действий для кнопок (до 35 символов каждый).")
    choice_stats: List[str] = Field(default_factory=list, description="Список из 3-4 значений ('str', 'agi', 'int', 'luck'), указывающих, какая характеристика проверяется для каждого действия в choices.")
    key_memory: Optional[str] = Field(default=None, description="Если случилось судьбоносное событие, короткая заметка (до 80 символов), иначе null.")

    @field_validator("choices")
    @classmethod
    def sanitize_choices(cls, v):
        return [c[:40].strip() for c in v if c.strip()][:4]

SYSTEM_INSTRUCTION = """
Ты — безжалостный, но справедливый Гейм-Мастер (Dungeon Master) в интерактивной текстовой RPG.
Сеттинг: Глубокое мрачное Средневековье (1349 год). Холод, грязь, чумные поветрия, инквизиция, разбойники, феодальные интриги, суеверия и шепот о древнем зле в глухих чащах. Это не детская сказка, а суровый реализм с элементами фолк-хоррора.

ТВОИ ПРАВИЛА:
1. Краткость и атмосфера: Пиши сочно, кинематографично, емко (2-3 абзаца, не более 500 символов в narrative). Описывай звуки, запахи, скрип стали, холод дождя.
2. Подчинение кубику: Если в запросе указан результат броска кубика (d20), результат действия СТРОГО зависит от него:
   - Критический провал (1): оружие ломается, персонаж падает, навлекает беду, получает тяжелый урон.
   - Неудача (<10): действие срывается, герой получает урон, тревога поднята, урон врагу 0.
   - Частичный успех (10-14): цель достигнута, но с ценой (рана, потеря ресурса, шум). В бою наносится частичный урон врагу (-10...-15), но и герой получает сдачу.
   - Полный успех (>=15): безупречное исполнение. Чистый урон врагу (-20...-35), герой невредим.
   - Критический триумф (20): сокрушительный успех, смертоносный урон (-40...-50) и ценный трофей.
3. Боевая система: Если появляется опасный монстр или враг — установи is_in_combat=true, укажи enemy_name и enemy_max_hp (40-70). В ходе боя уменьшай здоровье врага через enemy_hp_change (отрицательное число). Когда здоровье врага достигает 0, бой заканчивается (is_in_combat=false), выдай щедрый опыт (35-50 XP) и трофеи.
4. Выборы и характеристики: К каждому действию в choices укажи проверяемую характеристику в choice_stats: 'str' (Сила), 'agi' (Ловкость), 'int' (Интеллект) или 'luck' (Удача).
5. Защита от читов и бреда: Если игрок пишет безумные вещи («я достал автомат», «я стал богом»), интерпретируй это как горячечный бред истощенного разума. Сними рассудок (-10...-15), опиши изумление окружающих на бессвязные крики героя и верни его к жесткой реальности.
6. Персонаж смертен: Если здоровье падает до нуля или рассудок иссяк — ставь is_dead=true.
"""

def get_gemini_client() -> genai.Client:
    """Создать клиент Gemini"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY не задан в переменных окружения.")
    return genai.Client(api_key=GEMINI_API_KEY)

async def generate_turn(
    player: Dict[str, Any],
    inventory: List[str],
    chronicle: List[str],
    recent_history: List[Dict[str, str]],
    action_text: str,
    dice_verdict: str
) -> Optional[GameTurnOutput]:
    """Асинхронная генерация игрового хода через Gemini с таймаутом 20 сек"""
    client = get_gemini_client()

    chronicle_text = "\n".join([f"• {c}" for c in chronicle]) if chronicle else "Путь только начался."
    inventory_text = ", ".join(inventory) if inventory else "Пусто"

    history_text = ""
    for turn in recent_history:
        history_text += f"\nИгрок: {turn['player_action']}\nМастер: {turn['narrative']}\n"

    enemy_info = "Врага поблизости нет."
    if player.get("enemy_name") and player.get("enemy_hp", 0) > 0:
        enemy_info = f"ИДЕТ БОЙ! Враг: {player['enemy_name']} (Текущее HP: {player['enemy_hp']}/{player.get('enemy_max_hp', 50)})."

    user_prompt = f"""
ТЕКУЩИЙ СТАТУС ПЕРСОНАЖА:
- Имя/Класс: {player['class_title']} ({player['class_name']}) [Уровень {player.get('level', 1)}]
- Здоровье: {player['hp']}/100
- Рассудок: {player['sanity']}/100
- Монеты: {player['gold']}
- Локация: {player['location']}
- Инвентарь: {inventory_text}
- Характеристики: Сила {player['str_stat']:+d}, Ловкость {player['agi_stat']:+d}, Интеллект {player['int_stat']:+d}
- Боевое состояние: {enemy_info}

ЛЕТОПИСЬ КЛЮЧЕВЫХ СОБЫТИЙ:
{chronicle_text}

НЕДАВНИЕ СОБЫТИЯ:
{history_text}

ТЕКУЩЕЕ ДЕЙСТВИЕ ИГРОКА:
«{action_text}»

ВЕРДИКТ БРОСКА КУБИКА:
{dice_verdict}

Сгенерируй следующий ход в строгом формате JSON в соответствии со схемой.
"""

    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_json_schema=GameTurnOutput.model_json_schema(),
                    temperature=0.75,
                )
            ),
            timeout=20.0
        )

        response_text = response.text
        if not response_text:
            return None

        data = json.loads(response_text)
        return GameTurnOutput(**data)

    except Exception as e:
        logger.error(f"Ошибка вызова Gemini API: {e}", exc_info=True)
        return None

async def generate_prologue(class_title: str, class_name: str, start_items: List[str]) -> GameTurnOutput:
    """Асинхронная генерация вступительного пролога для нового персонажа"""
    client = get_gemini_client()
    items_str = ", ".join(start_items)

    prompt = f"""
Персонаж начинает игру!
Класс: {class_title} ({class_name})
Снаряжение: {items_str}
Локация старта: Захудалый придорожный трактир 'Старый Вепрь' поздней дождливой ночью.

Опиши атмосферную завязку: где сидит герой, какая буря за окном, какие мрачные слухи ходят среди выпивох, и какая первая тревожная угроза или зацепка привлекает его внимание.
Сгенерируй JSON с 3 интригующими вариантами первого шага и типами проверок в choice_stats.
"""

    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_json_schema=GameTurnOutput.model_json_schema(),
                    temperature=0.8,
                )
            ),
            timeout=20.0
        )
        data = json.loads(response.text)
        return GameTurnOutput(**data)
    except Exception as e:
        logger.error(f"Ошибка генерации пролога: {e}", exc_info=True)
        return GameTurnOutput(
            narrative="За окнами трактира хлещет холодный октябрьский ливень. В очаге трещат сырые поленья. Вы сидите в темном углу, грея озябшие пальцы о глиняную кружку. Внезапно дверь с грохотом распахивается, и в тепло вваливается запыхавшийся путник в окровавленном плаще...",
            hp_change=0,
            sanity_change=0,
            gold_change=0,
            items_added=[],
            items_removed=[],
            location_name="Трактир 'Старый Вепрь'",
            is_dead=False,
            choices=[
                "Подойти к раненому и расспросить",
                "Положить руку на оружие и наблюдать из тени",
                "Сделать вид, что ничего не заметил, и допить эль"
            ],
            choice_stats=["int", "str", "luck"],
            key_memory="Прибыл в трактир 'Старый Вепрь' в разгар бури."
        )
