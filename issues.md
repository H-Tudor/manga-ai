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
