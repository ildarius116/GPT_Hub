import json
import logging

import httpx

from app.config import EXTRACTION_MODEL, LITELLM_API_KEY, LITELLM_URL

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Ты извлекаешь долгосрочные факты о пользователе из диалога с ассистентом.

ЧТО ИЗВЛЕКАТЬ (только факты о самом пользователе, не о мире):
- Идентичность: имя, возраст, город, профессия, роль, место работы
- Проекты: над чем работает, технологический стек, цели
- Предпочтения: языки программирования, фреймворки, стиль работы, инструменты
- Явные правила: "всегда делай X", "я предпочитаю Y", "не используй Z"
- Устойчивые обстоятельства: семья, интересы, ограничения

ФОРМАТ КАЖДОГО ФАКТА — ОБЯЗАТЕЛЬНО:
- Полное самодостаточное предложение на русском языке.
- Субъект — "Пользователь" или его имя.
- В факте должно быть понятно и КТО, и ЧТО, без опоры на контекст диалога.
- Минимум 4 слова. Одно слово или отдельная сущность — НЕ факт.

ХОРОШИЕ примеры:
  "Пользователя зовут Ильдар."
  "Пользователь работает DevOps-инженером в компании MWS."
  "Пользователь разрабатывает платформу MWS GPT на базе OpenWebUI и LiteLLM."
  "Пользователь предпочитает Python и FastAPI для бэкенда."
  "Пользователь просит отвечать кратко и без лишних комментариев."

ПЛОХИЕ примеры (НЕ извлекай такое):
  "резюме"                          — одно слово, не факт
  "LinkedIn"                        — сущность без утверждения
  "Python"                          — не факт о пользователе
  "Предпочитает работать в команде" — нет субъекта
  "МИС"                             — непонятная аббревиатура без контекста
  "Ответ на вопрос X"               — не факт о пользователе

ПРАВИЛА (СТРОГО):
- Извлекай ТОЛЬКО то, что пользователь СКАЗАЛ САМ в своих сообщениях (role=user).
- ЗАПРЕЩЕНО: выводить факты из ответов ассистента, из парафразов, из общих знаний
  (например: "МТС — российская компания" → НЕ значит, что пользователь в России;
  "пользователь из МТС" → НЕ значит, что он в Казани).
- ЗАПРЕЩЕНО: додумывать место жительства, возраст, пол, национальность, семейное
  положение, если пользователь об этом не сказал прямо.
- Если факта нет в словах пользователя — НЕ извлекай его. Пустой список лучше галлюцинации.
- Извлекай ВСЕ самостоятельные факты о пользователе, которые он сказал. Если в одном
  сообщении пользователь назвал имя, профессию, место работы, проект и стек — это
  5 разных фактов, и все пять должны попасть в результат.
- Максимум 8 фактов за разговор. Если ничего — верни {"memories": []}.

Верни ТОЛЬКО валидный JSON: {"memories": ["Пользователь ...", "Пользователь ..."]}"""


async def extract_memories(messages: list[dict]) -> list[str]:
    """Extract memorable facts from a conversation using LLM."""
    # Only feed USER messages to the extractor. Assistant paraphrases cause the
    # extractor to hallucinate facts the user never stated ("МТС → Казань" etc).
    user_only = [
        m for m in messages
        if m.get("role") == "user" and m.get("content")
    ]
    conversation = "\n\n".join(
        f"[сообщение пользователя]\n{m['content']}"
        for m in user_only
    )

    if not conversation.strip():
        return []

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{LITELLM_URL}/v1/chat/completions",
                json={
                    "model": EXTRACTION_MODEL,
                    "messages": [
                        {"role": "system", "content": EXTRACTION_PROMPT},
                        {"role": "user", "content": conversation},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                },
                headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON from response (handle markdown code blocks)
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]

            result = json.loads(content)
            return result.get("memories", [])

    except Exception as e:
        logger.error("Memory extraction failed: %s", e)
        return []
