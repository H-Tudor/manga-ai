from __future__ import annotations

import base64
import io
import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

# Manga-specific system prompt for the vision LLM.
_SYSTEM_PROMPT = """\
You are an expert manga image analyst and professional translator.

=== MANGA READING CONVENTIONS ===
- Japanese (and many East-Asian) manga pages are read RIGHT-TO-LEFT and TOP-TO-BOTTOM.
- Speech bubbles appear in various shapes: oval, rectangular, spiky (shouting/emphasis),
  cloud-shaped (thoughts), or jagged boxes (electronic voices / robots).
- Narration boxes are typically rectangular, often at the top or bottom of a panel.
- Frames / panels themselves can be skewed, overlapping, or arranged non-linearly;
  analyse each text element independently of panel boundaries.

=== TEXT APPEARANCE VARIANTS ===
- Black text on white speech bubble interior (most common).
- White text on black/dark bubble (used for internal monologue or dramatic effect).
- Black text with white outline (frequently used for large sound effects / onomatopoeia
  that are integrated directly into the artwork).
- White text with black outline (less common variant of the above).
- Stylised / hand-lettered fonts for personality / shouting / whispers.
- Vertical text columns are common in Japanese manga; read top-to-bottom in each column,
  columns ordered right-to-left.

=== YOUR TASK ===
1. Identify EVERY text region in the image: speech bubbles, thought bubbles,
   sound effects, narration boxes, signs, labels, and any other text.
2. For each region return:
   - Pixel bounding box (x1, y1, x2, y2) measured from the top-left corner of the full image.
   - The exact original text (preserving line breaks if vertically stacked).
   - A concise, natural-sounding translation to the requested target language.
     * Keep the translated text short enough to fit inside the original bubble area.
     * Preserve the speaker's emotional tone, register (formal/casual/childlike/gruff),
       and speech patterns.
     * Translate sound effects into a natural target-language equivalent or a
       transliteration in parentheses when no good equivalent exists.
   - The dominant background fill colour inside the bubble as a CSS hex string (#RRGGBB).
   - The text foreground colour as a CSS hex string (#RRGGBB).

Return ONLY a JSON object that strictly conforms to the schema provided.
Do NOT include any markdown fences, prose, or commentary outside the JSON.
"""

_HUMAN_PROMPT_TEMPLATE = """\
Please identify and translate every text region on this manga page.
Source language: {source_language}
Target language: {target_language}

For every region provide:
  x1, y1, x2, y2  — pixel bounding box
  original_text    — verbatim text as it appears
  translation      — natural {target_language} translation, concise enough to fit the bubble
  background_color — dominant bubble fill color (#RRGGBB)
  text_color       — text foreground color (#RRGGBB)
"""


def _image_to_data_url(image_bytes: bytes) -> tuple[str, str]:
    """Return (mime_type, base64_data_url) for the image bytes."""
    # Detect format from magic bytes
    if image_bytes[:4] == b"\x89PNG":
        mime = "image/png"
    elif image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode()
    return mime, f"data:{mime};base64,{b64}"


class ImageTranslator:
    """Manga image translator with a pass-through default (no AI backend).

    For real translation use :func:`create_translator` instead.
    """

    async def translate_image(
        self,
        image_bytes: bytes,
        source_language: str,
        target_language: str = "en",
    ) -> bytes:
        """Return *image_bytes* unmodified (pass-through stub)."""
        if source_language.lower().startswith(target_language.lower()):
            return image_bytes
        return image_bytes


class LangChainImageTranslator(ImageTranslator):
    """Translates manga page images using a LangChain vision LLM.

    The LLM is asked to:
    1. Locate every text region and return bounding boxes + translations as JSON.
    2. The translated text is then drawn back onto the image using Pillow,
       replacing the original text while respecting the available space.

    Parameters
    ----------
    llm:
        Any LangChain chat model that supports multimodal (vision) input.
        Create one with :func:`ai_translate.backends.create_llm`.
    """

    def __init__(self, llm: "BaseChatModel") -> None:
        from .schema import PageTranslation

        # with_structured_output wraps the LLM to return a PageTranslation object.
        self._chain = llm.with_structured_output(PageTranslation)

    async def translate_image(
        self,
        image_bytes: bytes,
        source_language: str,
        target_language: str = "en",
    ) -> bytes:
        if source_language.lower().startswith(target_language.lower()):
            return image_bytes

        from langchain_core.messages import HumanMessage, SystemMessage

        from .image_utils import apply_translations

        _mime, data_url = _image_to_data_url(image_bytes)

        human_text = _HUMAN_PROMPT_TEMPLATE.format(
            source_language=source_language,
            target_language=target_language,
        )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": human_text},
                ]
            ),
        ]

        try:
            result = await self._chain.ainvoke(messages)
        except Exception:  # pragma: no cover – network / model errors
            return image_bytes

        return apply_translations(image_bytes, result.regions)


def create_translator(
    backend: str | None = None,
    llm: "BaseChatModel | None" = None,
) -> LangChainImageTranslator:
    """Convenience factory that wires up a :class:`LangChainImageTranslator`.

    Parameters
    ----------
    backend:
        Backend name (``"openai"``, ``"anthropic"``, ``"ollama"``).
        Falls back to the ``AI_BACKEND`` env var, then ``"openai"``.
    llm:
        Provide a pre-built LangChain LLM to skip the :func:`~backends.create_llm`
        call entirely (useful for tests).
    """
    load_dotenv()
    if llm is None:
        from .backends import create_llm

        llm = create_llm(backend)
    return LangChainImageTranslator(llm)

