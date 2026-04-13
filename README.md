# MWS GPT Platform

Self-hosted AI chat platform with auto-routing, long-term memory, voice, presentations, and monitoring.

Built on [OpenWebUI](https://github.com/open-webui/open-webui) (prebuilt image) with [LiteLLM](https://github.com/BerriAI/litellm) as the AI gateway to a single upstream — **MWS GPT API** (`https://api.gpt.mws.ru/v1`, OpenAI-compatible). Persistent user memory, `.pptx` generation, TTS, and a full observability stack are custom companion services.

## Features

- **26 MWS GPT models** — chat, vision, embeddings, STT, image generation, all via one upstream
- **Auto-Router** — `MWS GPT Auto 🎯` virtual model classifies each request (rules + LLM fallback) and dispatches up to 13 subagents in parallel, aggregating a single streaming answer
- **Long-term memory** — two parallel layers: durable user **facts** (LLM-extracted from user turns only) and **conversation episodes** (summary + 1024-dim pgvector embedding, time-window recall)
- **Voice** — STT via `mws/whisper-turbo` (through LiteLLM), TTS via local gTTS companion (OpenAI-compatible API)
- **RAG** — upload PDFs, DOCX, CSV; embeddings routed via LiteLLM → `mws/bge-m3`
- **Real `.pptx` generation** — dedicated `pptx-service` parses PDF/DOCX/TXT, calls `mws/glm-4.6` in JSON mode, renders via `python-pptx`, delivers the file back into chat
- **LLM tracing** — every LiteLLM request traced in Langfuse (headless-provisioned on first boot)
- **Monitoring** — Prometheus + pre-built Grafana dashboards
- **Security** — nginx rate limiting, security headers, attack path blocking, `no-new-privileges` on all containers

## Architecture

```
User → Nginx (:80) → OpenWebUI (:3000)
                         │
                    LiteLLM (:4000 internal) → MWS GPT API (https://api.gpt.mws.ru/v1)
                         │
           Memory Service (internal)  ← OpenWebUI filter (inlet/outlet)
           TTS Service (internal)     ← gTTS, OpenAI-compatible /v1/audio/speech
           PPTX Service (internal)    ← python-pptx, parses PDF/DOCX/TXT, LLM JSON mode
           Langfuse (internal)        ← tracing callbacks
           Prometheus (internal)      ← metrics scraping
           Grafana (:3002)            ← dashboards
           Bootstrap (one-shot)       ← seeds functions + admin API token on first signup
```

**Request flow:** OpenWebUI treats LiteLLM as an OpenAI-compatible API (`OPENAI_API_BASE_URLS=http://litellm:4000/v1`). The global `mws_memory` filter searches the Memory Service for relevant user facts and injects them into the system prompt before each request. After responses, it extracts new facts and writes a conversation episode. LiteLLM forwards everything to MWS GPT API and sends traces to Langfuse. Embeddings (RAG) and STT also route through LiteLLM, not through local models.

## Services

| Service | Image / Build | Host Port | Description |
|---------|---------------|-----------|-------------|
| **postgres** | pgvector/pgvector:pg16 | 127.0.0.1:5432 | 4 databases (openwebui, litellm, langfuse, memory); data in `./data/postgres` bind-mount |
| **redis** | redis:7-alpine | — | LiteLLM response cache |
| **litellm** | build: ./litellm | — | AI gateway, routing, fallbacks, Langfuse callbacks |
| **openwebui** | ghcr.io/open-webui/open-webui:main | 3000 | Chat UI, RAG, file uploads, admin settings |
| **memory-service** | build: ./memory-service | — | FastAPI + pgvector; facts + episodes |
| **tts-service** | build: ./tts-service | — | gTTS-based TTS, OpenAI-compatible API |
| **pptx-service** | build: ./pptx-service | — | python-pptx + pypdf + python-docx; LLM schema via `mws/glm-4.6` |
| **langfuse** | langfuse/langfuse:2 | — | LLM tracing and analytics (headless-provisioned) |
| **prometheus** | prom/prometheus:latest | — | Metrics collection (30d retention) |
| **grafana** | grafana/grafana:latest | 3002 | Dashboards |
| **nginx** | nginx:alpine | 80, 443 | Reverse proxy with rate limiting and security headers |
| **bootstrap** | python:3.11-slim | — | One-shot init: waits for first signup, seeds pipes + admin API token |

Internal services (marked `—`) are accessible only via the Docker network.

## Models

All 26 models point at MWS GPT API via `litellm/config.yaml` aliases:

- **Chat / instruct:** `mws/gpt-alpha` (default), `mws/qwen3-235b`, `mws/qwen3-32b`, `mws/qwen3-coder`, `mws/llama-3.1-8b`, `mws/llama-3.3-70b`, `mws/gpt-oss-120b`, `mws/gpt-oss-20b`, `mws/glm-4.6`, `mws/kimi-k2`, `mws/deepseek-r1-32b`, `mws/qwq-32b`, `mws/gemma-3-27b`, `mws/qwen2.5-72b`
- **Vision:** `mws/qwen3-vl`, `mws/qwen2.5-vl`, `mws/qwen2.5-vl-72b`, `mws/cotype-pro-vl`
- **Embeddings:** `mws/bge-m3`, `mws/bge-gemma2`, `mws/qwen3-embedding`
- **STT (whisper):** `mws/whisper-medium`, `mws/whisper-turbo`
- **Image generation:** `mws/qwen-image`, `mws/qwen-image-lightning` — exposed in the dropdown as **MWS Image 🎨** / **MWS Image Lightning ⚡** virtual pipes

Fallback chains: `mws/gpt-alpha → [mws/qwen3-235b, mws/llama-3.3-70b]`, `mws/qwen3-coder → [mws/qwen3-235b, mws/gpt-oss-120b]`, `mws/gpt-oss-120b → [mws/qwen3-235b, mws/llama-3.3-70b]`. Redis response cache enabled. `drop_params: true`.

## Quick Start

### Prerequisites

- Docker and Docker Compose v2
- `MWS_GPT_API_KEY` — the only mandatory secret

### Zero-config startup

```bash
git clone <repository-url>
cd task-repo
cp .env.example .env
# Edit .env: set MWS_GPT_API_KEY=sk-...
docker compose up -d
```

That's it. On first boot:

1. `docker-compose.yml` provides dev defaults for all other secrets (`POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `OPENWEBUI_SECRET_KEY`, `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) — override them in `.env` for prod.
2. Langfuse is headless-provisioned via `LANGFUSE_INIT_*`: org `mws`, project `mws-gpt`, admin `admin@mws.local`, API key wired to LiteLLM.
3. Open http://localhost:3000 and register — first signup becomes admin.
4. The `bootstrap` sidecar detects the new admin and:
   - generates a random OpenWebUI admin API key, inserts it into the `api_key` table (valid for `Authorization: Bearer`),
   - publishes it to `./data/secrets/owui_admin_token` (consumed by the pptx-delivery pipe via a read-only bind-mount),
   - writes `OWUI_ADMIN_TOKEN=...` into `.env` so it survives recreation,
   - seeds `mws_auto_router`, `mws_memory`, and `mws_image_gen` into OpenWebUI's `function` table with `is_active=TRUE`, `is_global=TRUE`.

Reload http://localhost:3000 once — `MWS GPT Auto 🎯` appears at the top of the model dropdown, the memory filter is attached to every chat, and `.pptx` generation works end-to-end.

No manual function upload, no `make` targets, no extra commands.

### Editing pipe sources

If you edit `pipelines/auto_router_function.py` or another pipe source file:

```bash
docker compose restart bootstrap && docker compose restart openwebui
```

The bootstrap sidecar is idempotent and UPSERTs the new content into the DB. `make deploy-functions` is the alternative explicit path (requires `OWUI_ADMIN_TOKEN` in env).

## Commands

| Command | Description |
|---------|-------------|
| `docker compose up -d` | Start all services |
| `docker compose down` | Stop all services |
| `docker compose ps` | Show service status |
| `docker compose logs -f <service>` | Tail logs for a specific service |
| `make build` | Build custom images (litellm, memory-service, tts-service, pptx-service) |
| `make reset` | Destroy volumes and rebuild (destructive) |
| `make prod` | Start with production overrides |
| `make backup` | Backup all 4 PostgreSQL databases |
| `make restore DB=<db> FILE=<path>` | Restore a specific database |
| `make deploy-functions` | Manually redeploy pipe sources (requires `OWUI_ADMIN_TOKEN`) |

## Web UIs

| Service | URL | Credentials |
|---------|-----|-------------|
| OpenWebUI | http://localhost (nginx) or http://localhost:3000 (direct) | First registered user = admin |
| Grafana | http://localhost:3002 | admin / admin (or `GRAFANA_ADMIN_PASSWORD`) |
| Langfuse | internal only (use `docker compose port langfuse 3000` to expose) | `admin@mws.local` / `LANGFUSE_INIT_USER_PASSWORD` |
| Prometheus | internal only | No auth |
| Postgres | 127.0.0.1:5432 (localhost-only, for DBeaver SSH tunnel) | `mws` / `POSTGRES_PASSWORD` |

## Production

```bash
make prod
# or: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Production overrides: resource limits (~4.5 GB total RAM), log rotation (json-file, 10 MB × 3 per service), `restart: always`.

**For prod, override the dev-default secrets in `.env`:**

```bash
# Generate strong random values
openssl rand -hex 32   # LITELLM_MASTER_KEY, OPENWEBUI_SECRET_KEY, LANGFUSE_NEXTAUTH_SECRET, LANGFUSE_SALT
openssl rand -hex 16   # POSTGRES_PASSWORD
```

Langfuse public/secret keys can be rotated by signing into Langfuse UI with the seeded admin and issuing a new project API key, then updating `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` in `.env`.

### Backups

```bash
make backup                              # dumps all 4 databases to backups/
make restore DB=memory FILE=backups/memory_2026-03-29_120000.sql.gz
```

Backups older than 7 days are automatically cleaned up. Note that `./data/postgres` is a host bind-mount, so it also survives `docker compose down -v` / container rebuilds — `make reset` will wipe volumes but you must manually `rm -rf ./data/postgres` to truly reset the DB.

## Security

- **Nginx hardening** — rate limiting (10 req/s general, 5 req/s API, no limit on static assets), security headers (X-Frame-Options, CSP with `https:` in `img-src` for generated image URLs, X-Content-Type-Options), blocked attack paths
- **Container isolation** — `no-new-privileges` on all services; read-only filesystems on nginx and prometheus; internal services not exposed to host
- **Postgres** — bound to `127.0.0.1:5432` only, accessible via SSH tunnel (DBeaver)
- **Secrets validation** — `bash scripts/check-secrets.sh` verifies `.env` completeness and scans for leaked API keys in tracked files
- **HTTPS ready** — nginx config includes commented SSL block for TLS 1.2/1.3 with modern ciphersuites

## Key Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Full 12-service stack with dev secret defaults via `${VAR:-default}` |
| `docker-compose.prod.yml` | Production overrides (limits, logging) |
| `litellm/config.yaml` | Model definitions, routing, fallbacks, cache, Langfuse callbacks |
| `memory-service/app/` | FastAPI + pgvector: facts and conversation episodes |
| `tts-service/main.py` | gTTS-based TTS endpoint |
| `pptx-service/` | FastAPI `POST /build`: PDF/DOCX/TXT → LLM JSON schema → python-pptx |
| `pipelines/auto_router_function.py` | **MWS GPT Auto 🎯** — auto-router Pipe function |
| `pipelines/memory_function.py` | Global filter: inject user memories inlet, extract facts + episodes outlet |
| `pipelines/image_gen_function.py` | **MWS Image 🎨** / **Lightning ⚡** — image generation virtual models |
| `pipelines/memory_tool.py` | Chat tool for viewing/managing memories |
| `pipelines/usage_stats_tool.py` | Chat tool for usage statistics |
| `scripts/bootstrap.py` | One-shot init sidecar (functions + admin API token provisioning) |
| `scripts/init-databases.sql` | Multi-database PostgreSQL init |
| `nginx/nginx.conf` | Reverse proxy with security config |
| `monitoring/` | Prometheus config and Grafana dashboards |
| `.env.example` | Template for environment variables |
| `CLAUDE.md` | AI agent instructions and architecture reference |
| `PLAN_chat_agents.md` | Master design doc for the auto-router |
| `PLAN_db_memory.md` | Design doc for persistent conversation memory |
| `PLAN_presentations.md` | Design doc for `.pptx` generation |
| `model_capabilities.md` | Curated task-to-model map used by the classifier |

## Auto-Router — `MWS GPT Auto 🎯`

The virtual model that auto-selects subagents for every request.

### What it does automatically

| You send… | It dispatches to… |
|---|---|
| Plain RU text | `sa_ru_chat` (`mws/qwen3-235b`) |
| Plain EN text | `sa_general` (`mws/gpt-alpha`) |
| Code question | `sa_code` (`mws/qwen3-coder`) |
| Math proof / formal reasoning | `sa_reasoner` (`mws/deepseek-r1-32b`, CoT stripped before `### Answer:`) |
| Long pasted text (≥1500 chars) | `sa_long_doc` (`mws/glm-4.6`) |
| Attached image | `sa_vision` (`mws/cotype-pro-vl` RU / `mws/qwen3-vl` EN, auto-fallback to cotype on blind response) |
| Attached audio | `sa_stt` (`mws/whisper-turbo`) → re-planned from transcript |
| Attached PDF/DOCX | `sa_doc_qa` (`mws/glm-4.6` via built-in RAG, scoped to current document) |
| "Сделай презентацию…" + doc | `sa_presentation` (pptx-service → `mws/glm-4.6` JSON schema → `.pptx` file artifact) |
| "Нарисуй …" / "generate image" | `sa_image_gen` (`mws/qwen-image`) |
| "Найди в интернете…" | `sa_web_search` (DuckDuckGo + `mws/kimi-k2`) |
| A message with `https://…` (no attached doc) | `sa_web_fetch` (httpx + `mws/llama-3.1-8b`) |
| "о чём мы вчера говорили?" | `sa_memory_recall` (episodes search with time window) |

Every response begins with a collapsible **🎯 Routing decision** block showing the detected language, chosen subagents, and models. Each subagent runs in parallel, returns a compact summary (≤500 tokens), and the final `mws/qwen3-235b` (RU) or `mws/gpt-alpha` (EN) aggregator streams the answer in markdown — without ever seeing the sub-responses' raw chain-of-thought.

### Manual model override

The dropdown also lists every raw `mws/*` alias. Pick one manually (e.g. `mws/qwen3-235b`) and the auto-router is **completely bypassed** — the request goes straight to LiteLLM. Use this for deterministic model selection.

### Design docs

See `PLAN_chat_agents.md` (auto-router), `PLAN_db_memory.md` (episodes), `PLAN_presentations.md` (pptx), and phase reports in `tasks_done/phase-{9,10,11}-done.md`.

## License

TBD
