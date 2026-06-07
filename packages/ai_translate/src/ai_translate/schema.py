from __future__ import annotations

from pydantic import BaseModel, Field


class TextRegion(BaseModel):
    x1: int = Field(..., description="Left pixel coordinate of the bounding box")
    y1: int = Field(..., description="Top pixel coordinate of the bounding box")
    x2: int = Field(..., description="Right pixel coordinate of the bounding box")
    y2: int = Field(..., description="Bottom pixel coordinate of the bounding box")
    original_text: str = Field(..., description="Exact text as it appears in the image")
    translation: str = Field(..., description="Translated text in the target language")
    background_color: str = Field(
        ...,
        description=(
            "Background fill color of the text area as a hex string (#RRGGBB), "
            "e.g. '#ffffff' for white, '#000000' for black"
        ),
    )
    text_color: str = Field(
        ...,
        description=(
            "Foreground text color as a hex string (#RRGGBB), "
            "e.g. '#000000' for black, '#ffffff' for white"
        ),
    )


class PageTranslation(BaseModel):
    regions: list[TextRegion] = Field(
        default_factory=list,
        description="All text regions found on the manga page",
    )


class RegionBounds(BaseModel):
    """Bounding box and color metadata for a single text region, without the text itself.

    Used as the output schema for the region-detection stage of
    :class:`~ai_translate.translator.MangaOCRTranslator` so that a separate,
    specialised OCR model can handle the actual text extraction.
    """

    x1: int = Field(..., description="Left pixel coordinate of the bounding box")
    y1: int = Field(..., description="Top pixel coordinate of the bounding box")
    x2: int = Field(..., description="Right pixel coordinate of the bounding box")
    y2: int = Field(..., description="Bottom pixel coordinate of the bounding box")
    background_color: str = Field(
        ...,
        description=(
            "Dominant background fill color inside the text area as a hex string "
            "(#RRGGBB), e.g. '#ffffff' for white"
        ),
    )
    text_color: str = Field(
        ...,
        description=(
            "Foreground text color as a hex string (#RRGGBB), "
            "e.g. '#000000' for black"
        ),
    )


class PageRegions(BaseModel):
    """All detected text-region bounding boxes on a manga page."""

    regions: list[RegionBounds] = Field(
        default_factory=list,
        description="All text regions found on the manga page (no OCR text)",
    )


class TranslationBatch(BaseModel):
    """Ordered list of translations produced by the text-translation stage."""

    translations: list[str] = Field(
        default_factory=list,
        description=(
            "Translations in the same order as the input texts. "
            "Each entry is a concise, natural-sounding translation."
        ),
    )
