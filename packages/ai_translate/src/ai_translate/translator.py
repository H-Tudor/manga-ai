from __future__ import annotations


class ImageTranslator:
    """Agnostic image translator interface with a default pass-through behavior."""

    async def translate_image(
        self,
        image_bytes: bytes,
        source_language: str,
        target_language: str = "en",
    ) -> bytes:
        if source_language.lower().startswith(target_language.lower()):
            return image_bytes
        return image_bytes
