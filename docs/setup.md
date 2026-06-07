# Project Setup Guide

This guide covers everything needed to run **Manga AI** locally for development
and to deploy it in production with Docker Compose.

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.14 | Required by all packages |
| [uv](https://docs.astral.sh/uv/) | latest | Workspace dependency manager |
| Docker + Docker Compose | 24 / 2.20 | Required for production (and optional for dev) |
| Git | any | |

You also need credentials for at least one AI backend (see [Environment variables](#environment-variables)).

---

## Repository layout

```
manga-ai/
├── packages/
│   ├── ai_translate/   # Vision-LLM image translator
│   ├── manga_dex/      # MangaDex API client + SQLite cache
│   └── api/            # FastAPI service
├── infra/              # Keycloak realm config
├── docs/               # Sphinx documentation
└── docker-compose.yml
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in the required values before starting
any service:

```bash
cp .env.example .env
```

### Required

| Variable | Description |
|---|---|
| `AI_BACKEND` | AI provider: `openai`, `anthropic`, or `ollama` |
| `OPENAI_API_KEY` | Required when `AI_BACKEND=openai` |
| `ANTHROPIC_API_KEY` | Required when `AI_BACKEND=anthropic` |

### Optional / defaults

| Variable | Default | Description |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model name |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | Anthropic model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `minicpm-v` | Ollama vision model |
| `MANGADEX_CLIENT_ID` | *(empty)* | Enables authenticated MangaDex requests |
| `MANGADEX_CLIENT_SECRET` | *(empty)* | Enables authenticated MangaDex requests |
| `KEYCLOAK_URL` | `http://localhost:8080` | Keycloak base URL |
| `KEYCLOAK_REALM` | `manga-ai` | Keycloak realm name |
| `KEYCLOAK_AUDIENCE` | `manga-ai-api` | JWT audience claim |
| `MANGA_DB_URL` | `sqlite:///./manga_cache.db` | SQLAlchemy database URL |
| `MANGA_STORAGE_DIR` | `./cache/translated` | Directory for translated page files |

---

## Development setup

Development uses **uv** to manage the monorepo workspace. All packages are
installed as editable sources so code changes take effect immediately.

### 1 — Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2 — Install all workspace packages

```bash
# From the repository root
uv sync
```

This creates a `.venv` virtual environment and installs all three packages
(`ai_translate`, `manga_dex`, `api`) plus every dev dependency in editable mode.

### 3 — Activate the virtual environment

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 4 — Configure environment variables

```bash
cp .env.example .env
# Edit .env and set at least AI_BACKEND + the matching API key
```

### 5 — Start Keycloak (identity provider)

The API validates JWT tokens issued by Keycloak.  For local development the
easiest way is to run only the Keycloak service via Docker Compose:

```bash
docker compose up keycloak -d
```

Keycloak will be available at `http://localhost:8080`.  The `manga-ai` realm
and the `manga-ai-api` client are imported automatically from
`infra/keycloak-realm.json`.

Admin console: `http://localhost:8080/admin` (user: `admin`, password: `admin`).

### 6 — Run the API with hot-reload

```bash
uvicorn api.main:app --reload --port 8000
```

The API is now reachable at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`.

### 7 — Install pre-commit hooks (recommended)

```bash
uv run pre-commit install
```

Ruff linting and formatting checks will now run automatically on every commit.

---

## Production setup (Docker Compose)

The `docker-compose.yml` file defines three services:

| Service | Port | Description |
|---|---|---|
| `keycloak` | 8080 | Keycloak identity provider |
| `api` | 8000 | FastAPI back-end |
| `ui` | 80 | Static UI served by nginx |

### 1 — Configure environment variables

```bash
cp .env.example .env
# Edit .env — set AI_BACKEND and the matching API key at minimum
```

> **Note:** `KEYCLOAK_URL` is automatically overridden to
> `http://keycloak:8080` inside the compose network. The value in `.env` is
> only used when running services outside Docker.

### 2 — Build and start all services

```bash
docker compose up --build -d
```

On first start Docker will build the `api` and `ui` images and pull the
Keycloak image.  Subsequent starts skip the build if no files have changed:

```bash
docker compose up -d
```

### 3 — Verify the deployment

```bash
# Health check
curl http://localhost:8000/health
# → {"status":"ok"}

# UI
open http://localhost:80
```

### 4 — View logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f api
```

### 5 — Tear down

```bash
# Stop containers (keep volumes)
docker compose down

# Stop containers and delete the manga_data volume (removes cache)
docker compose down -v
```

---

## Optional: local LLM with Ollama

To use an on-device vision model instead of a cloud API:

1. Uncomment the `ollama` service block in `docker-compose.yml`.
2. In `.env` set:
   ```
   AI_BACKEND=ollama
   OLLAMA_BASE_URL=http://ollama:11434
   OLLAMA_MODEL=minicpm-v
   ```
3. Start the stack:
   ```bash
   docker compose up --build -d
   ```
4. Pull the vision model (first time only):
   ```bash
   docker compose exec ollama ollama pull minicpm-v
   ```

For GPU acceleration (NVIDIA), uncomment the `deploy.resources` block inside
the `ollama` service definition in `docker-compose.yml`.

---

## Running tests

```bash
# From the repository root (uv virtual environment must be active)
python -m pytest -q
```

The `[tool.pytest.ini_options]` section in `pyproject.toml` automatically adds
all package `src` directories to `PYTHONPATH`, so no extra configuration is
needed.

---

## Building the documentation

The project uses [Sphinx](https://www.sphinx-doc.org/) with autodoc.

```bash
cd docs
make html
# Output: docs/_build/html/index.html

# Live-reload server (requires sphinx-autobuild, included in dev deps)
make livehtml
```
