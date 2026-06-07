from __future__ import annotations

import base64
import io
import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from .ocr import MangaOCRWrapper

# ---------------------------------------------------------------------------
# Shared system / human prompts
# ---------------------------------------------------------------------------

# Manga-specific system prompt for the vision LLM (full OCR + translation).
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

# ---------------------------------------------------------------------------
# Prompts used by MangaOCRTranslator (region detection only, no OCR)
# ---------------------------------------------------------------------------

_REGION_DETECTION_SYSTEM_PROMPT = """\
You are a manga text-region detector.

Your ONLY task is to locate every text region on the manga page and return its
bounding box and colour information.  Do NOT attempt to read or translate any text.

Identify: speech bubbles, thought bubbles, sound effects, narration boxes, signs,
labels, and any other region that contains text.

For each region return:
  - Pixel bounding box (x1, y1, x2, y2) measured from the top-left corner of the full image.
  - The dominant background fill colour inside the bubble as a CSS hex string (#RRGGBB).
  - The text foreground colour as a CSS hex string (#RRGGBB).

Return ONLY a JSON object that strictly conforms to the schema provided.
Do NOT include any markdown fences, prose, or commentary outside the JSON.
"""

_REGION_DETECTION_HUMAN_PROMPT = """\
Please locate every text region on this manga page and return its bounding box
and colour information.  Do not read or translate the text.

For every region provide:
  x1, y1, x2, y2  — pixel bounding box
  background_color — dominant bubble fill color (#RRGGBB)
  text_color       — text foreground color (#RRGGBB)
"""

_TRANSLATION_SYSTEM_PROMPT = """\
You are a professional manga translator.

Translate the provided source-language text snippets into natural, concise
{target_language}.  Preserve each speaker's emotional tone, register
(formal / casual / childlike / gruff), and speech patterns.
Translate sound effects into a natural target-language equivalent, or provide a
transliteration in parentheses when no good equivalent exists.

Return ONLY a JSON object that strictly conforms to the schema provided.
Do NOT include markdown fences, prose, or commentary outside the JSON.
"""

_TRANSLATION_HUMAN_TEMPLATE = """\
Translate the following {source_language} manga text snippets into {target_language}.
Return the translations in the same order as the input.

{texts}
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


class MangaOCRTranslator(ImageTranslator):
    """Two-stage translator that combines manga-ocr with a LangChain LLM.

    This translator improves OCR accuracy for Japanese manga by delegating
    text recognition to the specialised ``manga-ocr`` model instead of relying
    solely on a general-purpose vision LLM.

    **Pipeline**

    1. **Region detection** — a vision LLM locates every text region and returns
       bounding boxes plus colour metadata (no OCR/translation at this stage).
    2. **OCR** — each detected region is cropped from the image and passed to
       :class:`~ai_translate.ocr.MangaOCRWrapper`, which returns the recognised
       Japanese text.
    3. **Translation** — all recognised texts are sent in a single batch to a
       text LLM for translation.
    4. **Rendering** — translated text is drawn back onto the image via
       :func:`~ai_translate.image_utils.apply_translations`.

    Parameters
    ----------
    llm:
        A LangChain chat model used for both region detection (vision) and
        translation (text).  Must support multimodal / vision input for the
        region-detection step.
    ocr:
        An :class:`~ai_translate.ocr.MangaOCRWrapper` instance.  If *None*,
        one is created lazily on first use.

    Notes
    -----
    Install the ``manga-ocr`` optional extra before using this class::

        pip install "ai-translate[manga-ocr]"
    """

    def __init__(
        self,
        llm: "BaseChatModel",
        ocr: "MangaOCRWrapper | None" = None,
    ) -> None:
        from .schema import PageRegions, TranslationBatch

        self._region_chain = llm.with_structured_output(PageRegions)
        self._translation_chain = llm.with_structured_output(TranslationBatch)
        if ocr is None:
            from .ocr import MangaOCRWrapper

            ocr = MangaOCRWrapper()
        self._ocr = ocr

    async def translate_image(
        self,
        image_bytes: bytes,
        source_language: str,
        target_language: str = "en",
    ) -> bytes:
        """Translate all text regions in a manga page image.

        Parameters
        ----------
        image_bytes:
            Raw bytes of the manga page (JPEG, PNG, or WebP).
        source_language:
            BCP-47 language tag of the source text (e.g. ``"ja"``).
        target_language:
            BCP-47 language tag for the desired output (default ``"en"``).

        Returns
        -------
        bytes
            Modified image bytes with all detected text replaced by its
            translation, or the original bytes if translation is skipped or
            fails.
        """
        if source_language.lower().startswith(target_language.lower()):
            return image_bytes

        # ------------------------------------------------------------------
        # Stage 1: Detect text regions (bounding boxes + colours)
        # ------------------------------------------------------------------
        from langchain_core.messages import HumanMessage, SystemMessage

        from .image_utils import apply_translations
        from .schema import TextRegion

        _mime, data_url = _image_to_data_url(image_bytes)

        region_messages = [
            SystemMessage(content=_REGION_DETECTION_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": _REGION_DETECTION_HUMAN_PROMPT},
                ]
            ),
        ]

        try:
            page_regions = await self._region_chain.ainvoke(region_messages)
        except Exception:  # pragma: no cover – network / model errors
            return image_bytes

        if not page_regions.regions:
            return image_bytes

        # ------------------------------------------------------------------
        # Stage 2: OCR each cropped region with manga-ocr
        # ------------------------------------------------------------------
        try:
            from PIL import Image

            pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:  # pragma: no cover – PIL errors
            return image_bytes

        ocr_texts: list[str] = []
        for region in page_regions.regions:
            x1 = max(0, min(region.x1, pil_img.width - 1))
            y1 = max(0, min(region.y1, pil_img.height - 1))
            x2 = max(x1 + 1, min(region.x2, pil_img.width))
            y2 = max(y1 + 1, min(region.y2, pil_img.height))
            crop = pil_img.crop((x1, y1, x2, y2))
            try:
                text = self._ocr.read_text(crop)
            except Exception:  # pragma: no cover – OCR errors
                text = ""
            ocr_texts.append(text)

        # Skip regions where OCR returned nothing
        non_empty = [(i, t) for i, t in enumerate(ocr_texts) if t.strip()]
        if not non_empty:
            return image_bytes

        # ------------------------------------------------------------------
        # Stage 3: Batch-translate the OCR texts
        # ------------------------------------------------------------------
        indices, texts = zip(*non_empty)
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))

        translation_messages = [
            SystemMessage(
                content=_TRANSLATION_SYSTEM_PROMPT.format(target_language=target_language)
            ),
            HumanMessage(
                content=_TRANSLATION_HUMAN_TEMPLATE.format(
                    source_language=source_language,
                    target_language=target_language,
                    texts=numbered,
                )
            ),
        ]

        try:
            batch_result = await self._translation_chain.ainvoke(translation_messages)
        except Exception:  # pragma: no cover – network / model errors
            return image_bytes

        translations = batch_result.translations

        # ------------------------------------------------------------------
        # Stage 4: Assemble TextRegion list and render
        # ------------------------------------------------------------------
        text_regions: list[TextRegion] = []
        for list_idx, orig_idx in enumerate(indices):
            region = page_regions.regions[orig_idx]
            translation = translations[list_idx] if list_idx < len(translations) else ""
            if not translation:
                continue
            text_regions.append(
                TextRegion(
                    x1=region.x1,
                    y1=region.y1,
                    x2=region.x2,
                    y2=region.y2,
                    original_text=ocr_texts[orig_idx],
                    translation=translation,
                    background_color=region.background_color,
                    text_color=region.text_color,
                )
            )

        return apply_translations(image_bytes, text_regions)


def create_translator(
    backend: str | None = None,
    llm: "BaseChatModel | None" = None,
    use_manga_ocr: bool = False,
    manga_ocr: "MangaOCRWrapper | None" = None,
) -> LangChainImageTranslator | MangaOCRTranslator:
    """Convenience factory that wires up an image translator.

    Parameters
    ----------
    backend:
        Backend name (``"openai"``, ``"anthropic"``, ``"ollama"``).
        Falls back to the ``AI_BACKEND`` env var, then ``"openai"``.
    llm:
        Provide a pre-built LangChain LLM to skip the :func:`~backends.create_llm`
        call entirely (useful for tests).
    use_manga_ocr:
        When *True*, returns a :class:`MangaOCRTranslator` that uses
        ``manga-ocr`` for OCR and the LLM only for region detection and
        translation.  Requires the ``manga-ocr`` optional extra::

            pip install "ai-translate[manga-ocr]"
    manga_ocr:
        A pre-built :class:`~ai_translate.ocr.MangaOCRWrapper` instance.
        Only used when *use_manga_ocr* is *True*.  If *None*, one is created
        automatically.

    Returns
    -------
    LangChainImageTranslator | MangaOCRTranslator
        A ready-to-use translator instance.
    """
    load_dotenv()
    if llm is None:
        from .backends import create_llm

        llm = create_llm(backend)

    if use_manga_ocr:
        return MangaOCRTranslator(llm, ocr=manga_ocr)
    return LangChainImageTranslator(llm)

