import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

class NPCProfile(BaseModel):
    name: str = Field(description="Имя персонажа (например: Трактирщик Ганс, Сестра Беатриса, Бродяга Мёрдок, Отец Иероним)")
    title: str = Field(description="Роль или занятие (например: Хозяин трактира, Беглая монахиня, Охотник за головами)")
    temperament: str = Field(description="Характер и темперамент (например: Желчный и подозрительный скряга; запуганная праведница; наглый наемник)")
    speech_style: str = Field(description="Стиль речи и манера говорить (например: Хриплый шепот, грубое просторечие, растягивает гласные, заикается, сыплет воровским жаргоном)")
    quirks: str = Field(description="Особые жесты, мимика и слова-паразиты (например: Нервно теребит четки, сплевывает в угол, щурит бельмо на глазу, повторяет 'видит бог')")
    hidden_motive: str = Field(description="Скрытый мотив, тайный страх или личный интерес (например: Боится разоблачения, прячет чумные язвы под бинтами, жаждет золота)")
    system_persona_prompt: str = Field(description="Концентрированная ролевая установка для отыгрыша: кто этот NPC, как мыслит и как говорит с героем (2-3 предложения).")

class CompanionEvent(BaseModel):
    name: str = Field(description="Имя спутника, с которым связано событие")
    affinity_change: int = Field(default=0, ge=-25, le=25, description="Изменение симпатии (-25 до +25)")
    comment: Optional[str] = Field(default=None, description="Прямая речь или эмоциональная реакция спутника на поступок героя")
    action_type: str = Field(default="reaction", description="Тип: 'reaction' (реакция), 'recruited' (присоединился), 'left' (покинул отряд)")

class NewCompanion(BaseModel):
    name: str = Field(description="Имя нового спутника (например: Сестра Беатриса, Роланд, Клод)")
    title: str = Field(description="Краткий титул/роль (например: Беглая послушница, Седой арбалетчик)")
    archetype: str = Field(description="Класс/роль: воин, лекарь, стрелок, плут, бард")
    personality: str = Field(description="Краткий характер и взгляды персонажа")
    initial_affinity: int = Field(default=50, ge=30, le=75, description="Начальный уровень отношений (30-75)")

class GameTurnOutput(BaseModel):
    narrative: str = Field(description="Художественное, живое и атмосферное описание сцены на богатом русском языке в духе темного фэнтези (до 1500 символов). ОБЯЗАТЕЛЬНО включает живую прямую речь NPC, запахи, эмоции и естественное развитие сюжета.")
    hp_change: int = Field(default=0, ge=-40, le=30, description="Изменение здоровья игрока (-40 до +30).")
    sanity_change: int = Field(default=0, ge=-30, le=25, description="Изменение рассудка (-30 до +25).")
    gold_change: int = Field(default=0, ge=-60, le=60, description="Изменение золота (-60 до +60).")
    items_added: List[str] = Field(default_factory=list, description="Полученные предметы (максимум 2).")
    items_removed: List[str] = Field(default_factory=list, description="Потерянные или истраченные предметы.")
    location_name: str = Field(default="Вересковые пустоши", description="Короткое атмосферное название локации.")
    
    # Боевая система и боссы
    is_in_combat: bool = Field(default=False, description="Идет ли активный бой с врагом или чудовищем.")
    enemy_name: Optional[str] = Field(default=None, description="Имя врага (например: Чумной волк, Инквизитор Малахия).")
    enemy_max_hp: int = Field(default=0, ge=0, le=120, description="Максимальное здоровье врага при первой встрече (40-80 HP).")
    enemy_hp_change: int = Field(default=0, description="Урон по врагу от удара игрока (отрицательное число, например -20).")

    # Сюжет и опыт
    xp_gained: int = Field(default=10, ge=0, le=60, description="Опыт за преодоление опасности (10-40 XP).")
    main_quest_update: Optional[str] = Field(default=None, description="Обновление или прогресс по главной сюжетной цели, если случилось важное открытие.")

    # Персонажи и их уникальные промпты
    active_npc: Optional[NPCProfile] = Field(default=None, description="Если в этой сцене герой общается или взаимодействует с конкретным NPC — обязательно создай или обнови для него детальный профайл/промпт личности!")

    # Спутники и отношения
    companion_event: Optional[CompanionEvent] = Field(default=None, description="Реакция текущего спутника, изменение симпатии или реплика.")
    new_companion: Optional[NewCompanion] = Field(default=None, description="Заполняется ТОЛЬКО если в этой сцене к герою присоединяется спутник.")

    is_dead: bool = Field(default=False, description="Погиб ли персонаж.")
    death_reason: Optional[str] = Field(default=None, description="Краткая причина гибели.")
    choices: List[str] = Field(description="Ровно 3-4 интригующих варианта действий для кнопок (до 40 символов каждый). Обязательно предлагай разнообразные подходы: бой, хитрость, диалог/слово, знание мира!")
    choice_stats: List[str] = Field(default_factory=list, description="Список типов проверок ('str', 'agi', 'int', 'speech', 'luck', 'insanity') для каждого действия.")
    key_memory: Optional[str] = Field(default=None, description="Судьбоносная заметка для летописи (до 80 символов), если произошло ключевое событие.")

    @field_validator("choices")
    @classmethod
    def sanitize_choices(cls, v):
        return [c[:42].strip() for c in v if c.strip()][:4]

SYSTEM_INSTRUCTION = """
Ты — выдающийся Гейм-Мастер (Dungeon Master) и летописец в мрачной текстовой ролевой игре.
Сеттинг: Глубокое реалистичное Средневековье, 1349 год — эпоха Чёрной Смерти. Холод, грязь, суеверия, инквизиция, чумные доктора в птичьих масках, разбойники и фолк-хоррор.

ПРАВИЛА МАСТЕРСТВА И СТИЛЯ:
1. ЛИТЕРАТУРНЫЙ ЖИВОЙ ЯЗЫК (в стиле Анджея Сапковского и Джорджа Мартина):
   - Никаких сухих протокольных отчетов вроде «Вы бросили кубик и нанесли 10 урона». Текст должен звучать как настоящая литература!
   - Описывай запахи (сырость, гарь, полынь), тактильные ощущения (липкая кровь, ледяная рукоять меча), тени и звуки.
   - ОБЯЗАТЕЛЬНО используй живую прямую речь NPC через тире:
     «— Не лезь туда, парень, — прохрипел старик, сплюнув в золу очага. — Там нынче не люди ходят, а сам мор на двух ногах.»

2. ОБЯЗАТЕЛЬНЫЙ ПРОМПТ И ХАРАКТЕР ДЛЯ КАЖДОГО NPC (active_npc):
   - Всякий раз, когда герой начинает диалог или взаимодействует с персонажем (трактирщик, монах, наемник, торговец, нищий, девица у очага), ты ОБЯЗАН сгенерировать детальный личностный профиль в active_npc:
     • темперамент (желчный холерик, запуганная богомолка, хитрый пройдоха, меланхоличный философ);
     • стиль речи (шепелявит, говорит хриплым басом, вставляет церковную латынь, глотает окончания, воровское арго);
     • повадки и жесты (теребит крест, крутит кольцо, нервно косится на дверь, ковыряет ножом столешницу);
     • скрытый мотив (чего он боится? что скрывает? какую выгоду ищет?);
     • system_persona_prompt: концентрированная установка для отыгрыша этой личности.
   - ВСЕ РЕПЛИКИ этого NPC в тексте должны СТРОГО звучать в его уникальном стиле речи, с его акцентами и словечками!
   - Если в контексте переданы уже известные NPC — отыгрывай их строго по их сохраненным промптам!

3. СИСТЕМА СПУТНИКОВ И ОТНОШЕНИЙ:
   - В путешествии герой может встречать потенциальных спутников (беглая послушница Беатриса, угрюмый ветеран Роланд, плутоватый бард Клод и др.).
   - Если между героем и NPC возникает связь или согласие идти вместе — заполни new_companion.
   - Если со спутником уже путешествуют — отражай его реакцию в companion_event. Спутники реагируют на моральные выборы (милосердие, грабеж, смелость).
   - Отношения со спутниками развиваются: от подозрительного попутчика до верного боевого товарища, а при взаимном тепле — до глубокой сердечной привязанности и любви.

4. СТРОГОЕ ПОДЧИНЕНИЕ КУБИКУ d20:
   - Результат действия обязан соответствовать вердикту кубика:
     • 1 (Критический провал): поломка оружия, конфуз, тяжелое ранение, беда.
     • 2-9 (Неудача): действие сорвано, получен урон, враг перехватил инициативу.
     • 10-14 (Частичный успех): цель достигнута, но дорогой ценой (ранение, потеря припасов).
     • 15-19 (Полный успех): чистое, искусное исполнение без вреда для себя.
     • 20 (Критический триумф): сокрушительный успех, восхищение окружающих, редкий трофей.

5. МЕХАНИКА РАССУДКА (SANITY):
   - Если рассудок героя низок (<35), вплетай в повествование тревогу, галлюцинации, подозрительность к спутникам и шепоты в темноте. Одно из действий в choices может носить метку 'insanity' (безумный порыв).

6. СЮЖЕТНЫЙ ДВИГАТЕЛЬ (MAIN QUEST):
   - Не зацикливай игру на бесконечном блуждании. Постоянно развивай главную цель персонажа, приближая его к ключевым развилкам сюжета и боссам актов.
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
    active_companion: Optional[Dict[str, Any]],
    known_npcs: Optional[List[Dict[str, Any]]],
    action_text: str,
    dice_verdict: str
) -> Optional[GameTurnOutput]:
    """Асинхронная генерация игрового раунда через Gemini с таймаутом 22 сек"""
    client = get_gemini_client()

    chronicle_text = "\n".join([f"• {c}" for c in chronicle]) if chronicle else "Путь только начался."
    inventory_text = ", ".join(inventory) if inventory else "Пусто"

    history_text = ""
    for turn in recent_history:
        history_text += f"\nИгрок: {turn['player_action']}\nМастер: {turn['narrative']}\n"

    companion_info = "Герой путешествует один."
    if active_companion:
        companion_info = (
            f"СПУТНИК В ОТРЯДЕ: {active_companion['name']} ({active_companion.get('title', 'Спутник')})\n"
            f"- Характер: {active_companion.get('personality', 'Скрытный')}\n"
            f"- Отношения к герою: {active_companion.get('affinity', 50)}% ({active_companion.get('relationship_status', 'Попутчик')})\n"
            f"Спутник слышит разговор, видит поступки героя и может реагировать, вступать в беседу или помогать в бою!"
        )

    npcs_text = "Новых персонажей в сцене пока нет."
    if known_npcs:
        lines = []
        for n in known_npcs:
            lines.append(
                f"• {n['name']} ({n['title']}):\n"
                f"   [Характер: {n['temperament']} | Стиль речи: {n['speech_style']} | Привычки: {n['quirks']} | Тайный мотив: {n['hidden_motive']}]\n"
                f"   ПРОМПТ ДЛЯ ОТЫГРЫША: {n.get('system_prompt', '')}"
            )
        npcs_text = "ИЗВЕСТНЫЕ ПЕРСОНАЖИ В СЦЕНЕ / МИРЕ (ОТЫГРЫВАТЬ СТРОГО ПО ИХ УНИКАЛЬНЫМ ПРОМПТАМ!):\n" + "\n".join(lines)

    enemy_info = "Прямого боя сейчас нет."
    if player.get("enemy_name") and player.get("enemy_hp", 0) > 0:
        enemy_info = f"ИДЕТ БОЙ! Враг: {player['enemy_name']} (HP врага: {player['enemy_hp']}/{player.get('enemy_max_hp', 50)})."

    user_prompt = f"""
ТЕКУЩИЙ СТАТУС ПЕРСОНАЖА:
- Имя/Класс: {player['class_title']} ({player['class_name']}) [Уровень {player.get('level', 1)}]
- Предыстория: {player.get('background', 'Скиталец')}
- Главная цель (Main Quest): {player.get('main_quest', 'Выжить в чумных землях')}
- Здоровье: {player['hp']}/100
- Рассудок: {player['sanity']}/100
- Монеты: {player['gold']}
- Локация: {player['location']}
- Инвентарь: {inventory_text}
- Характеристики: Сила {player['str_stat']:+d}, Ловкость {player['agi_stat']:+d}, Интеллект {player['int_stat']:+d}
- Боевое состояние: {enemy_info}

{companion_info}

{npcs_text}

ЛЕТОПИСЬ КЛЮЧЕВЫХ СОБЫТИЙ:
{chronicle_text}

НЕДАВНИЕ СОБЫТИЯ И ДИАЛОГИ:
{history_text}

ТЕКУЩЕЕ ДЕЙСТВИЕ ИЛИ СЛОВА ИГРОКА:
«{action_text}»

ВЕРДИКТ БРОСКА КУБИКА:
{dice_verdict}

ИНСТРУКЦИЯ К ХОДУ:
1. Если герой общается или взаимодействует с персонажем — заполни active_npc с уникальным характером, стилем речи и промптом!
2. Вложи в уста NPC живую прямую речь СТРОГО в его речевом стиле (сленг, заикание, хрипота, говор).
3. Сгенерируй живое литературное продолжение в строгом формате JSON по схеме.
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
                    temperature=0.8,
                )
            ),
            timeout=22.0
        )

        response_text = response.text
        if not response_text:
            return None

        data = json.loads(response_text)
        return GameTurnOutput(**data)

    except Exception as e:
        logger.error(f"Ошибка вызова Gemini API: {e}", exc_info=True)
        return None

async def generate_prologue(
    class_title: str,
    class_name: str,
    background_title: str,
    background_desc: str,
    main_quest: str,
    start_items: List[str]
) -> GameTurnOutput:
    """Асинхронная генерация кинематографичного пролога с глубокой завязкой и NPC"""
    client = get_gemini_client()
    items_str = ", ".join(start_items)

    prompt = f"""
Создай захватывающий, кинематографичный пролог для новой ролевой саги!

ПЕРСОНАЖ:
- Класс: {class_title} ({class_name})
- Предыстория: {background_title} — {background_desc}
- Главный квест (Main Quest): {main_quest}
- Стартовое снаряжение: {items_str}
- Начальная сцена: Глухая дождливая ночь поздней осени 1349 года. Старый деревянный трактир «Старый Вепрь» на границе гиблых вересковых пустошей. За мутными окнами хлещет ледяной ливень.

ТРЕБОВАНИЯ К ПРОЛОГУ:
1. Опиши тяжелое дыхание героя, его душевные раны и груз прошлого, связанный с его предысторией.
2. В трактире находится колоритный NPC: трактирщик Ганс или беглая послушница Беатриса. 
   ОБЯЗАТЕЛЬНО заполни для этого ключевого NPC полный профиль в active_npc (темперамент, стиль речи, жесты, скрытый мотив и system_persona_prompt)!
3. В нарративе передай живую прямую речь этого персонажа строго в его уникальном стиле речи!
4. Сгенерируй ровно 3-4 интригующих варианта первого действия (включая вариант заговорить) и типы проверок в choice_stats ('speech', 'int', 'str', 'agi').
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
                    temperature=0.85,
                )
            ),
            timeout=22.0
        )
        data = json.loads(response.text)
        return GameTurnOutput(**data)
    except Exception as e:
        logger.error(f"Ошибка генерации пролога: {e}", exc_info=True)
        return GameTurnOutput(
            narrative=(
                "Холодный октябрьский ливень барабанит по черепице трактира «Старый Вепрь». "
                "В очаге шипят сырые еловые поленья, наполняя низкую залу горьким смолистым дымом.\n\n"
                "— Недобрый нынче ветер дует со стороны Черных Топей, — прохрипел старый трактирщик Ганс, с грохотом швырнув на дубовый стол глиняную кружку с мутным элем. — "
                "Говорят, в монастыре колокола бьют без умолку, а на большаке вчера нашли карету инквизитора... пустую.\n\n"
                "В углу у камина вздрагивает хрупкая девушка в дорожном монашеском плаще с посохом в руках. "
                "Она ловит ваш взгляд — в ее глазах плещется отчаянная мольба о помощи."
            ),
            hp_change=0,
            sanity_change=0,
            gold_change=0,
            items_added=[],
            items_removed=[],
            location_name="Трактир «Старый Вепрь»",
            active_npc=NPCProfile(
                name="Ганс «Смоляной Нос»",
                title="Хозяин трактира «Старый Вепрь»",
                temperament="Желчный, подозрительный скряга с волчьим чутьем на чужие беды",
                speech_style="Говорит хриплым прокуренным басом, причмокивает, использует грубые кабацкие словечки",
                quirks="Постоянно вытирает оловянную кружку сальным подолом, сплевывает в золу очага",
                hidden_motive="Прячет в подвале контрабандное вино и боится любого стука в дверь, подозревая инквизицию",
                system_persona_prompt="Ты — старый кабатчик Ганс. Не доверяешь ни одной живой душе, но за звонкую монету готов продать даже черта. Говори хрипло, недоверчиво, с грубым прищуром."
            ),
            is_dead=False,
            choices=[
                "Подойти к девушке у камина и заговорить",
                "Расспросить трактирщика о карете",
                "Наблюдать из темноты, положив руку на оружие",
                "Выйти в дождь к коновязи осмотреть следы"
            ],
            choice_stats=["speech", "speech", "int", "agi"],
            key_memory="Прибыл в трактир «Старый Вепрь» в ночь великой бури."
        )
