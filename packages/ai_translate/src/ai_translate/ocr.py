"""Manga-OCR wrapper for specialised Japanese text recognition.

This module provides :class:`MangaOCRWrapper`, a thin, lazily-loaded adapter
around the ``manga-ocr`` library.  The model is only downloaded and
instantiated the first time :meth:`~MangaOCRWrapper.read_text` is called, so
importing this module is always safe even when ``manga-ocr`` is not installed.

Install the optional extra to enable this feature::

    pip install "ai-translate[manga-ocr]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


class MangaOCRWrapper:
    """Lazily-loaded wrapper around the ``manga-ocr`` OCR model.

    The underlying :class:`manga_ocr.MangaOcr` instance is created on the
    first call to :meth:`read_text`.  Subsequent calls reuse the already-
    loaded model, so the expensive model-download step only happens once per
    process.

    Parameters
    ----------
    pretrained_model_name_or_path:
        HuggingFace model identifier (or local path) forwarded to
        :class:`manga_ocr.MangaOcr`.  Defaults to the upstream model
        ``"kha-white/manga-ocr-base"``.
    force_cpu:
        When *True*, forces CPU inference even if CUDA is available.

    Raises
    ------
    ImportError
        If the ``manga-ocr`` package is not installed when
        :meth:`read_text` is first called.

    Examples
    --------
    >>> from PIL import Image
    >>> ocr = MangaOCRWrapper()
    >>> text = ocr.read_text(Image.open("panel.png"))
    """

    def __init__(
        self,
        pretrained_model_name_or_path: str = "kha-white/manga-ocr-base",
        *,
        force_cpu: bool = False,
    ) -> None:
        self._model_name = pretrained_model_name_or_path
        self._force_cpu = force_cpu
        self._ocr: object | None = None

    def _load(self) -> None:
        """Instantiate the MangaOcr model (called lazily on first use)."""
        if self._ocr is not None:
            return
        try:
            from manga_ocr import MangaOcr  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "The manga-ocr package is required for MangaOCRWrapper. "
                'Install it with: pip install "ai-translate[manga-ocr]"'
            ) from exc

        self._ocr = MangaOcr(
            pretrained_model_name_or_path=self._model_name,
            force_cpu=self._force_cpu,
        )

    def read_text(self, image: "Image") -> str:
        """Extract Japanese text from a PIL image using manga-ocr.

        Parameters
        ----------
        image:
            A cropped :class:`~PIL.Image.Image` containing a single text
            region (speech bubble, narration box, sound effect, etc.).

        Returns
        -------
        str
            The recognised text string.  Returns an empty string if the model
            produces no output.
        """
        self._load()
        # MangaOcr is callable: ocr(image) -> str
        result: str = self._ocr(image)  # type: ignore[operator]
        return result or ""
