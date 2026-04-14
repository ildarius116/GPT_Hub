# MWS GPT Platform

Self-hosted платформа AI-чата с авто-роутингом, долгосрочной памятью, голосом, презентациями и мониторингом.

Построена на [OpenWebUI](https://github.com/open-webui/open-webui) (готовый образ) с [LiteLLM](https://github.com/BerriAI/litellm) в качестве AI-шлюза к единственному upstream — **MWS GPT API** (`https://api.gpt.mws.ru/v1`, OpenAI-совместимый). Постоянная пользовательская память, генерация `.pptx`, TTS и полный observability-стек — это собственные сопутствующие сервисы.

## Быстрый старт

### Требования

- Docker и Docker Compose v2
- `MWS_GPT_API_KEY` — единственный обязательный секрет

### Запуск без конфигурации

```bash
git clone <repository-url>
cd task-repo
cp .env.example .env
# Отредактируйте .env: укажите MWS_GPT_API_KEY=sk-...
docker compose up -d
```

Вот и всё. При первом запуске:

1. `docker-compose.yml` задаёт dev-значения по умолчанию для всех остальных секретов (`POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `OPENWEBUI_SECRET_KEY`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) — для продакшена переопределите их в `.env`.
2. Langfuse поднимается в headless-режиме через `LANGFUSE_INIT_*`: организация `mws`, проект `mws-gpt`, админ `admin@mws.local`, API-ключ автоматически прокинут в LiteLLM.
3. Откройте http://localhost:3000 и зарегистрируйтесь — первый зарегистрированный пользователь становится админом.
4. Sidecar `bootstrap` замечает нового админа и:
   - генерирует случайный OpenWebUI admin API key, вставляет его в таблицу `api_key` (валиден для `Authorization: Bearer`),
   - публикует его в `./data/secrets/owui_admin_token` (читается pptx-delivery пайпом через read-only bind-mount),
   - записывает `OWUI_ADMIN_TOKEN=...` в `.env`, чтобы пережить пересоздание контейнеров,
   - заливает `mws_auto_router`, `mws_memory` и `mws_image_gen` в таблицу `function` OpenWebUI с `is_active=TRUE`, `is_global=TRUE`.

Перезагрузите http://localhost:3000 один раз — `MWS GPT Auto 🎯` появится в начале списка моделей, memory-фильтр будет подключён к каждому чату, а генерация `.pptx` заработает end-to-end.

Ни ручной загрузки функций, ни `make`-таргетов, ни дополнительных команд.

### Правка исходников пайпов

Если вы редактируете `pipelines/auto_router_function.py` или другой исходник пайпа:

```bash
docker compose restart bootstrap && docker compose restart openwebui
```

Sidecar `bootstrap` идемпотентен и делает UPSERT нового содержимого в БД. `make deploy-functions` — альтернативный явный путь (требует `OWUI_ADMIN_TOKEN` в окружении).

## Возможности

- **26 моделей MWS GPT** — чат, vision, embeddings, STT, генерация изображений — всё через один upstream
- **Авто-роутер** — виртуальная модель `MWS GPT Auto 🎯` классифицирует каждый запрос (правила + LLM-фолбэк) и параллельно диспатчит до 13 сабагентов, агрегируя единый стриминговый ответ
- **Долгосрочная память** — два параллельных слоя: устойчивые **факты** о пользователе (LLM-извлечение только из сообщений пользователя) и **эпизоды диалогов** (summary + 1024-мерный pgvector-эмбеддинг, recall с временным окном)
- **Голос** — STT через `mws/whisper-turbo` (через LiteLLM), TTS через локальный gTTS-компаньон (OpenAI-совместимый API)
- **Документы** — загрузка PDF, DOCX, CSV; вопросы по документу идут в `_sa_doc_qa` на `mws/glm-4.6` (с большим контекстным окном), контекст документа намеренно не сохраняется между сообщениями
- **Реальная генерация `.pptx`** — отдельный `pptx-service` парсит PDF/DOCX/TXT, вызывает `mws/glm-4.6` в JSON-режиме, рендерит через `python-pptx`, отдаёт файл обратно в чат
- **Трейсинг LLM** — каждый запрос LiteLLM трейсится в Langfuse (headless-provisioning при первом запуске)
- **Мониторинг** — Prometheus + готовые Grafana-дашборды
- **Безопасность** — nginx rate limiting, security headers, блокировка attack-путей, `no-new-privileges` на всех контейнерах

## Архитектура

```
Пользователь → Nginx (:80) → OpenWebUI (:3000)
                                 │
                            LiteLLM (:4000 internal) → MWS GPT API (https://api.gpt.mws.ru/v1)
                                 │
                   Memory Service (internal)  ← фильтр OpenWebUI (inlet/outlet)
                   TTS Service (internal)     ← gTTS, OpenAI-совместимый /v1/audio/speech
                   PPTX Service (internal)    ← python-pptx, парсит PDF/DOCX/TXT, LLM в JSON-режиме
                   Langfuse (internal)        ← трейсинг-колбэки
                   Prometheus (internal)      ← сбор метрик
                   Grafana (:3002)            ← дашборды
                   Bootstrap (one-shot)       ← заливает функции + admin API token при первой регистрации
```

**Схема запроса:** OpenWebUI обращается к LiteLLM как к OpenAI-совместимому API (`OPENAI_API_BASE_URLS=http://litellm:4000/v1`). Глобальный фильтр `mws_memory` ищет в Memory Service релевантные факты о пользователе и инжектит их в system-prompt перед каждым запросом. После ответов он извлекает новые факты и пишет эпизод диалога. LiteLLM форвардит всё в MWS GPT API и шлёт трейсы в Langfuse. Embeddings (для документов) и STT также проходят через LiteLLM, а не через локальные модели.

## Сервисы

| Сервис | Образ / Build | Порт на хосте | Описание |
|---------|---------------|-----------|-------------|
| **postgres** | pgvector/pgvector:pg16 | 127.0.0.1:5432 | 4 БД (openwebui, litellm, langfuse, memory); данные в bind-mount `./data/postgres` |
| **redis** | redis:7-alpine | — | Кеш ответов LiteLLM |
| **litellm** | build: ./litellm | — | AI-шлюз, роутинг, фолбэки, колбэки Langfuse |
| **openwebui** | ghcr.io/open-webui/open-webui:main | 3000 | Чат-UI, загрузка файлов, админ-настройки |
| **memory-service** | build: ./memory-service | — | FastAPI + pgvector; факты и эпизоды |
| **tts-service** | build: ./tts-service | — | TTS на gTTS, OpenAI-совместимый API |
| **pptx-service** | build: ./pptx-service | — | python-pptx + pypdf + python-docx; LLM-схема через `mws/glm-4.6` |
| **langfuse** | langfuse/langfuse:2 | — | Трейсинг и аналитика LLM (headless-provisioning) |
| **prometheus** | prom/prometheus:latest | — | Сбор метрик (ретеншн 30 дней) |
| **grafana** | grafana/grafana:latest | 3002 | Дашборды |
| **nginx** | nginx:alpine | 80, 443 | Reverse proxy с rate limiting и security headers |
| **bootstrap** | python:3.11-slim | — | One-shot init: ждёт первой регистрации, заливает пайпы + admin API token |

Внутренние сервисы (помеченные `—`) доступны только внутри Docker-сети.

## Модели

Все 26 моделей указывают на MWS GPT API через алиасы в `litellm/config.yaml`:

- **Chat / instruct:** `mws/gpt-alpha` (по умолчанию), `mws/qwen3-235b`, `mws/qwen3-32b`, `mws/qwen3-coder`, `mws/llama-3.1-8b`, `mws/llama-3.3-70b`, `mws/gpt-oss-120b`, `mws/gpt-oss-20b`, `mws/glm-4.6`, `mws/kimi-k2`, `mws/deepseek-r1-32b`, `mws/qwq-32b`, `mws/gemma-3-27b`, `mws/qwen2.5-72b`
- **Vision:** `mws/qwen3-vl`, `mws/qwen2.5-vl`, `mws/qwen2.5-vl-72b`, `mws/cotype-pro-vl`
- **Embeddings:** `mws/bge-m3`, `mws/bge-gemma2`, `mws/qwen3-embedding`
- **STT (whisper):** `mws/whisper-medium`, `mws/whisper-turbo`
- **Генерация изображений:** `mws/qwen-image`, `mws/qwen-image-lightning` — отдаются в дропдауне как виртуальные пайпы **MWS Image 🎨** / **MWS Image Lightning ⚡**

Цепочки фолбэков: `mws/gpt-alpha → [mws/qwen3-235b, mws/llama-3.3-70b]`, `mws/qwen3-coder → [mws/qwen3-235b, mws/gpt-oss-120b]`, `mws/gpt-oss-120b → [mws/qwen3-235b, mws/llama-3.3-70b]`. Включён Redis-кеш ответов. `drop_params: true`.

## Команды

| Команда | Описание |
|---------|-------------|
| `docker compose up -d` | Запустить все сервисы |
| `docker compose down` | Остановить все сервисы |
| `docker compose ps` | Статус сервисов |
| `docker compose logs -f <service>` | Смотреть логи конкретного сервиса |
| `make build` | Собрать кастомные образы (litellm, memory-service, tts-service, pptx-service) |
| `make reset` | Удалить volumes и пересобрать (деструктивно) |
| `make prod` | Запустить с production-оверрайдами |
| `make backup` | Дамп всех 4 БД PostgreSQL |
| `make restore DB=<db> FILE=<path>` | Восстановить конкретную БД |
| `make deploy-functions` | Вручную перезалить исходники пайпов (требует `OWUI_ADMIN_TOKEN`) |

## Web-интерфейсы

| Сервис | URL | Учётные данные |
|---------|-----|-------------|
| OpenWebUI | http://localhost (nginx) или http://localhost:3000 (напрямую) | Первый зарегистрированный пользователь = админ |
| Grafana | http://localhost:3002 | admin / admin (или `GRAFANA_ADMIN_PASSWORD`) |
| Langfuse | только внутри (выставить через `docker compose port langfuse 3000`) | `admin@mws.local` / `LANGFUSE_INIT_USER_PASSWORD` |
| Prometheus | только внутри | Без авторизации |
| Postgres | 127.0.0.1:5432 (только localhost, для SSH-туннеля DBeaver) | `mws` / `POSTGRES_PASSWORD` |

## Production

```bash
make prod
# или: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Production-оверрайды: лимиты ресурсов (~4.5 ГБ суммарно RAM), ротация логов (json-file, 10 МБ × 3 на сервис), `restart: always`.

**Для прода переопределите dev-дефолты секретов в `.env`:**

```bash
# Сгенерировать сильные случайные значения
openssl rand -hex 32   # LITELLM_MASTER_KEY, OPENWEBUI_SECRET_KEY, LANGFUSE_NEXTAUTH_SECRET, LANGFUSE_SALT
openssl rand -hex 16   # POSTGRES_PASSWORD
```

Public/secret ключи Langfuse можно ротировать, залогинившись в UI Langfuse под засиженным админом и выпустив новый API-ключ проекта, затем обновить `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` в `.env`.

### Бэкапы

```bash
make backup                              # дампит все 4 БД в backups/
make restore DB=memory FILE=backups/memory_2026-03-29_120000.sql.gz
```

Бэкапы старше 7 дней удаляются автоматически. Обратите внимание: `./data/postgres` — host bind-mount, поэтому он переживает `docker compose down -v` / пересоздание контейнеров — `make reset` снесёт volumes, но чтобы действительно обнулить БД, придётся вручную выполнить `rm -rf ./data/postgres`.

## Безопасность

- **Харденинг Nginx** — rate limiting (10 req/s на общие, 5 req/s на API, без лимита на статику), security headers (X-Frame-Options, CSP с `https:` в `img-src` для URL сгенерированных картинок, X-Content-Type-Options), блокировка attack-путей
- **Изоляция контейнеров** — `no-new-privileges` на всех сервисах; read-only файловая система на nginx и prometheus; внутренние сервисы не торчат наружу
- **Postgres** — слушает только `127.0.0.1:5432`, доступ через SSH-туннель (DBeaver)
- **Валидация секретов** — `bash scripts/check-secrets.sh` проверяет полноту `.env` и ищет утёкшие API-ключи в отслеживаемых файлах
- **HTTPS готов** — в конфиге nginx есть закомментированный SSL-блок для TLS 1.2/1.3 с современными ciphersuites

## Ключевые файлы

| Файл | Назначение |
|------|---------|
| `docker-compose.yml` | Полный стек из 12 сервисов с dev-дефолтами секретов через `${VAR:-default}` |
| `docker-compose.prod.yml` | Production-оверрайды (лимиты, логирование) |
| `litellm/config.yaml` | Определения моделей, роутинг, фолбэки, кеш, колбэки Langfuse |
| `memory-service/app/` | FastAPI + pgvector: факты и эпизоды диалогов |
| `tts-service/main.py` | TTS-эндпоинт на gTTS |
| `pptx-service/` | FastAPI `POST /build`: PDF/DOCX/TXT → JSON-схема LLM → python-pptx |
| `pipelines/auto_router_function.py` | **MWS GPT Auto 🎯** — Pipe-функция авто-роутера |
| `pipelines/memory_function.py` | Глобальный фильтр: inject памяти в inlet, извлечение фактов + эпизодов в outlet |
| `pipelines/image_gen_function.py` | **MWS Image 🎨** / **Lightning ⚡** — виртуальные модели генерации изображений |
| `pipelines/memory_tool.py` | Chat-tool для просмотра/управления памятью |
| `pipelines/usage_stats_tool.py` | Chat-tool для статистики использования |
| `scripts/bootstrap.py` | One-shot init sidecar (функции + provisioning admin API token) |
| `scripts/init-databases.sql` | Инициализация нескольких БД PostgreSQL |
| `nginx/nginx.conf` | Reverse proxy с security-конфигом |
| `monitoring/` | Конфиг Prometheus и Grafana-дашборды |
| `.env.example` | Шаблон переменных окружения |
| `CLAUDE.md` | Инструкции для AI-агента и архитектурный справочник |
| `PLAN_chat_agents.md` | Мастер-дизайн авто-роутера |
| `PLAN_db_memory.md` | Дизайн постоянной памяти диалогов |
| `PLAN_presentations.md` | Дизайн генерации `.pptx` |
| `model_capabilities.md` | Кураторская карта «задача → модель» для классификатора |

## Авто-роутер — `MWS GPT Auto 🎯`

Виртуальная модель, которая автоматически подбирает сабагентов под каждый запрос.

### Что делает автоматически

| Вы присылаете… | Он диспатчит в… |
|---|---|
| Обычный русский текст | `sa_ru_chat` (`mws/qwen3-235b`) |
| Обычный английский текст | `sa_general` (`mws/gpt-alpha`) |
| Вопрос по коду | `sa_code` (`mws/qwen3-coder`) |
| Математическое доказательство / формальные рассуждения | `sa_reasoner` (`mws/deepseek-r1-32b`, CoT обрезается до `### Answer:`) |
| Длинный вставленный текст (≥1500 символов) | `sa_long_doc` (`mws/glm-4.6`) |
| Прикреплённое изображение | `sa_vision` (`mws/cotype-pro-vl` RU / `mws/qwen3-vl` EN, автофолбэк на cotype при blind-ответе) |
| Прикреплённое аудио | `sa_stt` (`mws/whisper-turbo`) → переклассификация по транскрипту |
| Прикреплённый PDF/DOCX | `sa_doc_qa` (`mws/glm-4.6`, только по документу текущего сообщения) |
| «Сделай презентацию…» + документ | `sa_presentation` (pptx-service → JSON-схема `mws/glm-4.6` → файл-артефакт `.pptx`) |
| «Нарисуй …» / «generate image» | `sa_image_gen` (`mws/qwen-image-lightning`) |
| «Найди в интернете…» | `sa_web_search` (DuckDuckGo + `mws/kimi-k2`) |
| Сообщение с `https://…` (без прикреплённого документа) | `sa_web_fetch` (httpx + `mws/llama-3.1-8b`) |
| «о чём мы вчера говорили?» | `sa_memory_recall` (поиск по эпизодам с временным окном) |

Каждый ответ начинается со сворачиваемого блока **🎯 Routing decision** с определённым языком, выбранными сабагентами и моделями. Каждый сабагент работает параллельно, возвращает компактный summary (≤500 токенов), а финальный агрегатор на `mws/qwen3-235b` (RU) или `mws/gpt-alpha` (EN) стримит ответ в markdown — никогда не видя сырого chain-of-thought сабагентов.

### Ручной выбор модели

В дропдауне также доступны все сырые алиасы `mws/*`. Выберите один вручную (например, `mws/qwen3-235b`) — авто-роутер **полностью обходится**, запрос уходит напрямую в LiteLLM. Используйте для детерминированного выбора модели.

### Дизайн-документы

См. `PLAN_chat_agents.md` (авто-роутер), `PLAN_db_memory.md` (эпизоды), `PLAN_presentations.md` (pptx), а также отчёты фаз в `tasks_done/phase-{9,10,11}-done.md`.

## Лицензия

TBD
