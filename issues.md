# Implementation Issues

## AI Translation

- **Pass-through stub**: The base `ImageTranslator` class returns the image
  unmodified. Use `create_translator()` from `ai_translate` to get the real
  LangChain-powered `LangChainImageTranslator`.

- **Bounding-box accuracy**: Vision LLMs produce approximate bounding boxes.
  For pixel-perfect accuracy a dedicated manga OCR layer (e.g., `manga-ocr`)
  combined with the LLM used purely for translation would give better results.
  This is noted as a future improvement.

- **Ollama structured output**: Ollama's JSON mode is enabled via
  `format="json"`. Complex Pydantic schemas with nested lists work on recent
  Ollama builds (≥ 0.3) but may silently fail on older versions; the
  translator falls back to returning the original image in that case.

- **Font availability in Docker**: The image editing step tries `DejaVuSans.ttf`
  then `Arial.ttf` then PIL's built-in bitmap font. For best results install
  `fonts-dejavu-core` in the API Docker image.

---

## MangaDex API Usage Policy Compliance

The following issues were identified by reviewing the current codebase against
the [MangaDex API documentation](https://api.mangadex.org/docs/) and the
[MangaDex usage policies](https://mangadex.org/about/usage-policy).
**None of these are addressed in code yet** — they are recorded here for
prioritisation.

### 🔴 High Priority

- **Missing At-Home report-back** (`POST /at-home/report`): MangaDex's Terms of
  Service require that every image fetched through the At-Home CDN network
  (`/at-home/server/{chapter_id}`) be followed by a report call to
  `POST https://api.mangadex.org/at-home/report` within 30 seconds of the
  download completing (success *or* failure). The current `_fetch_and_cache_chapter_content`
  and `get_chapter_images` methods download images without ever sending this
  report. Violating this requirement results in API access being revoked.
  See: https://api.mangadex.org/docs/#tag/AtHome/operation/post-at-home-report

- **At-Home URL expiry / caching**: At-Home `baseUrl` values are session-scoped
  (valid for ~15 minutes). The current `ChapterContentCache` stores the full
  image URLs (including `baseUrl`) indefinitely in SQLite. Serving stale
  At-Home URLs will produce broken images and constitutes a policy violation.
  The cache should store only the `chapter_hash` and `page_filenames`, and
  the `baseUrl` should be fetched fresh each time images are requested.

- **Rate limiting — no implementation**: MangaDex enforces a rate limit of
  ~5 requests/second per IP address. The client makes no attempt to throttle
  requests. Background processing of entire manga titles (many chapters,
  many pages) will trigger rate-limit errors (HTTP 429) and may lead to IP
  bans. A token-bucket or `asyncio.sleep` throttle must be added.

### 🟡 Medium Priority

- **User-Agent header not set**: MangaDex requires that API consumers identify
  themselves via the `User-Agent` header (e.g., `manga-ai/0.1.0`). The current
  `httpx.AsyncClient` uses the default `python-httpx/...` user-agent. This
  should be overridden to allow MangaDex to contact the operator if needed.

- **Authentication via OAuth2 / Personal API Key**: The code currently passes
  `X-Client-Id` / `X-Client-Secret` in request headers, which corresponds to
  an older client-credentials flow. MangaDex has migrated to OAuth2 personal
  API keys and a token endpoint (`POST https://auth.mangadex.org/realms/mangadex/...`).
  The current approach may stop working and should be updated.

- **Explicit content / content rating filter absent**: The `/manga` search
  endpoint defaults to returning only `safe` and `suggestive` content.
  However, the chapter list endpoint (`/chapter`) does not explicitly set a
  `contentRating` filter, meaning explicit/pornographic chapters could be
  returned. A whitelist filter should be applied.

- **Attribution requirement**: MangaDex requires that translated content clearly
  credits the original scanlation groups. Chapter metadata includes `relationships`
  with `type: scanlation_group`. These group names are not surfaced in the API
  response or UI, which may violate attribution obligations.

### 🟢 Low Priority

- **Pagination not implemented**: The `/chapter` query uses a hard-coded
  `limit=100`. Long-running series (e.g., One Piece, Naruto) have far more
  than 100 chapters. The client should paginate using the `offset` parameter
  until all results are retrieved.

- **NSFW cover art**: The current UI renders covers via the MangaDex CDN.
  MangaDex cover artwork can be explicit/NSFW. No content-rating filter or
  blur is applied.

---

## Model Recommendations

Research evaluated models across: vision capability, translation quality
(especially CJK → English), structured-output reliability, and cost.

### Best by Performance

| Rank | Model | Provider | Notes |
|------|-------|----------|-------|
| ⭐ 1 | **GPT-4o** (`gpt-4o`) | OpenAI | Best-in-class vision + translation accuracy; highest structured JSON reliability; excellent CJK understanding |
| 2 | **Claude 3.5 Sonnet** (`claude-3-5-sonnet-20241022`) | Anthropic | Near-identical quality to GPT-4o; slightly more conservative with bounding-box estimates |
| 3 | **Claude 3.5 Haiku** (`claude-3-5-haiku-20241022`) | Anthropic | Good quality at lower cost; slightly weaker on dense-panel pages |

**Recommended for performance**: `gpt-4o` — best vision reasoning and most
reliable structured output for the multi-region JSON schema required.

### Best by Price

| Rank | Model | Provider | Input cost* | Notes |
|------|-------|----------|-------------|-------|
| ⭐ 1 | **GPT-4o-mini** (`gpt-4o-mini`) | OpenAI | ~$0.15 / 1M tokens | Vision-capable; acceptable translation quality for less complex pages |
| 2 | **Claude 3 Haiku** (`claude-3-haiku-20240307`) | Anthropic | ~$0.25 / 1M tokens | Very fast; good for high-volume pipelines |
| 3 | **minicpm-v** (via Ollama) | Local / free | $0 (GPU required) | Best free option; runs on consumer GPUs (≥ 8 GB VRAM); decent CJK support |

**Recommended for price**: `gpt-4o-mini` — lowest cost among API providers that
still support multimodal input with reliable JSON structured output.

**Recommended for zero ongoing cost (self-hosted)**: `minicpm-v` via Ollama — a
compact (< 9 GB) multimodal model with reasonable Japanese text recognition.
Enable it by uncommenting the `ollama` service in `docker-compose.yml` and
setting `AI_BACKEND=ollama` + `OLLAMA_MODEL=minicpm-v` in `.env`.

> \* Approximate list prices as of mid-2025. Image tokens are billed separately
> by most providers (typically $0.001–$0.003 per image at 1024×1024).


Research evaluated models across: vision capability, translation quality
(especially CJK → English), structured-output reliability, and cost.

### Best by Performance

| Rank | Model | Provider | Notes |
|------|-------|----------|-------|
| ⭐ 1 | **GPT-4o** (`gpt-4o`) | OpenAI | Best-in-class vision + translation accuracy; highest structured JSON reliability; excellent CJK understanding |
| 2 | **Claude 3.5 Sonnet** (`claude-3-5-sonnet-20241022`) | Anthropic | Near-identical quality to GPT-4o; slightly more conservative with bounding-box estimates |
| 3 | **Claude 3.5 Haiku** (`claude-3-5-haiku-20241022`) | Anthropic | Good quality at lower cost; slightly weaker on dense-panel pages |

**Recommended for performance**: `gpt-4o` — best vision reasoning and most
reliable structured output for the multi-region JSON schema required.

### Best by Price

| Rank | Model | Provider | Input cost* | Notes |
|------|-------|----------|-------------|-------|
| ⭐ 1 | **GPT-4o-mini** (`gpt-4o-mini`) | OpenAI | ~$0.15 / 1M tokens | Vision-capable; acceptable translation quality for less complex pages |
| 2 | **Claude 3 Haiku** (`claude-3-haiku-20240307`) | Anthropic | ~$0.25 / 1M tokens | Very fast; good for high-volume pipelines |
| 3 | **minicpm-v** (via Ollama) | Local / free | $0 (GPU required) | Best free option; runs on consumer GPUs (≥ 8 GB VRAM); decent CJK support |

**Recommended for price**: `gpt-4o-mini` — lowest cost among API providers that
still support multimodal input with reliable JSON structured output.

**Recommended for zero ongoing cost (self-hosted)**: `minicpm-v` via Ollama — a
compact (< 9 GB) multimodal model with reasonable Japanese text recognition.
Enable it by uncommenting the `ollama` service in `docker-compose.yml` and
setting `AI_BACKEND=ollama` + `OLLAMA_MODEL=minicpm-v` in `.env`.

> \* Approximate list prices as of mid-2025. Image tokens are billed separately
> by most providers (typically $0.001–$0.003 per image at 1024×1024).
