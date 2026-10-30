import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

class GameTurnOutput(BaseModel):
    narrative: str = Field(description="Художественное описание последствий действия и текущей ситуации в темном средневековом стиле (до 600 знаков). Сочное, живое, без лишней воды.")
    hp_change: int = Field(default=0, description="Изменение здоровья (-35 до +25). Отрицательное при ранениях/болезни, 0 если без вреда.")
    sanity_change: int = Field(default=0, description="Изменение рассудка (-25 до +15). Падает от ужаса, жестокости, нечисти, неизвестности.")
    gold_change: int = Field(default=0, description="Изменение золота (-50 до +50). Траты, кражи, находки монет.")
    items_added: List[str] = Field(default_factory=list, description="Полученные предметы (максимум 2).")
    items_removed: List[str] = Field(default_factory=list, description="Потерянные или истраченные предметы.")
    location_name: str = Field(description="Короткое название локации (например: Чёрный лес, Катакомбы аббатства, Трактир 'У переправы').")
    is_dead: bool = Field(default=False, description="Погиб ли персонаж.")
    death_reason: Optional[str] = Field(default=None, description="Краткая причина смерти, если персонаж погиб.")
    choices: List[str] = Field(description="Ровно 3-4 интригующих, тактических варианта действий для кнопок (до 35 символов каждый).")
    key_memory: Optional[str] = Field(default=None, description="Если случилось судьбоносное событие (убийство лорда, раскрытие тайны), короткая заметка (до 80 символов), иначе null.")

SYSTEM_INSTRUCTION = """
Ты — безжалостный, но справедливый Гейм-Мастер (Dungeon Master) в интерактивной текстовой RPG.
Сеттинг: Глубокое мрачное Средневековье (1349 год). Холод, грязь, чумные поветрия, инквизиция, разбойники, феодальные интриги, суеверия и шепот о древнем зле в глухих чащах. Это не детская сказка, а суровый реализм с элементами фолк-хоррора.

ТВОИ ПРАВИЛА:
1. Краткость и атмосфера: Пиши сочно, кинематографично, емко (2-4 абзаца, не более 500-600 символов в narrative). Описывай звуки, запахи, скрип стали, холод дождя.
2. Подчинение кубику: Если в запросе указан результат броска кубика (d20), результат действия СТРОГО зависит от него:
   - Критический провал (1): оружие ломается, персонаж падает, навлекает беду.
   - Неудача (<10): действие срывается, герой получает урон, тревога поднята.
   - Частичный успех (10-15): цель достигнута, но с ценой (рана, потраченный ресурс, шум).
   - Полный успех (>=15): безупречное исполнение.
   - Критический триумф (20): сокрушительный успех и бонусная находка.
3. Защита от читов и бреда: Если игрок пишет безумные вещи («я достал автомат», «я стал богом», «убей всех мгновенно»), интерпретируй это как горячечный бред истощенного разума или помутнение рассудка. Сними рассудок (-10...-15), опиши изумление окружающих на бессвязные крики героя и верни его к жесткой реальности.
4. Выборы: Предлагай разноплановые действия (одно силовое, одно скрытное/хитрое, одно связанное с исследованием или диалогом).
5. Персонаж смертен: Если здоровье падает до нуля или игрок совершает самоубийственный поступок при провальном кубике — ставь is_dead=true.
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
) -> GameTurnOutput:
    """Генерация игрового хода через Gemini с гарантированной JSON-структурой"""
    client = get_gemini_client()

    chronicle_text = "\n".join([f"• {c}" for c in chronicle]) if chronicle else "Путь только начался."
    inventory_text = ", ".join(inventory) if inventory else "Пусто"

    history_text = ""
    for turn in recent_history:
        history_text += f"\nИгрок: {turn['player_action']}\nМастер: {turn['narrative']}\n"

    user_prompt = f"""
ТЕКУЩИЙ СТАТУС ПЕРСОНАЖА:
- Имя/Класс: {player['class_title']} ({player['class_name']})
- Здоровье: {player['hp']}/100
- Рассудок: {player['sanity']}/100
- Монеты: {player['gold']}
- Локация: {player['location']}
- Инвентарь: {inventory_text}
- Характеристики: Сила {player['str_stat']:+d}, Ловкость {player['agi_stat']:+d}, Интеллект {player['int_stat']:+d}

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
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_json_schema=GameTurnOutput.model_json_schema(),
                temperature=0.75,
            )
        )

        response_text = response.text
        if not response_text:
            raise ValueError("Пустой ответ от Gemini API")

        data = json.loads(response_text)
        return GameTurnOutput(**data)

    except Exception as e:
        logger.error(f"Ошибка вызова Gemini API: {e}", exc_info=True)
        # Аварийный откат на случай сбоя сети/API, чтобы игра не крашилась
        return GameTurnOutput(
            narrative="Мгла и холод застилают глаза. Мир вокруг на мгновение замирает в тумане неизвестности... Вам удается перевести дыхание и собраться с мыслями.",
            hp_change=0,
            sanity_change=-2,
            gold_change=0,
            items_added=[],
            items_removed=[],
            location_name=player.get("location", "Окрестности"),
            is_dead=False,
            choices=["Осмотреться вокруг", "Проверить снаряжение", "Двигаться вперед с осторожностью"],
            key_memory=None
        )

async def generate_prologue(class_title: str, class_name: str, start_items: List[str]) -> GameTurnOutput:
    """Генерация вступительного пролога для нового персонажа"""
    client = get_gemini_client()

    items_str = ", ".join(start_items)
    prompt = f"""
Персонаж начинает игру!
Класс: {class_title} ({class_name})
Снаряжение: {items_str}
Локация старта: Захудалый придорожный трактир 'Старый Вепрь' поздней дождливой ночью.

Опиши атмосферную завязку: где сидит герой, какая буря за окном, какие мрачные слухи ходят среди выпивох, и какая первая тревожная угроза или зацепка привлекает его внимание.
Сгенерируй JSON с 3 интригующими вариантами первого шага.
"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_json_schema=GameTurnOutput.model_json_schema(),
                temperature=0.8,
            )
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
            key_memory="Прибыл в трактир 'Старый Вепрь' в разгар бури."
        )
