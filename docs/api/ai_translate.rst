ai_translate
============

The ``ai_translate`` package provides manga page translation via two backends:

* :class:`~ai_translate.LangChainImageTranslator` — single-stage vision LLM that
  detects text regions, reads the text, and translates it in one pass.
* :class:`~ai_translate.MangaOCRTranslator` — two-stage pipeline that uses a
  vision LLM for region detection, :class:`~ai_translate.MangaOCRWrapper` for
  high-accuracy Japanese OCR, and a text LLM for translation.

Use the :func:`~ai_translate.create_translator` factory to construct either
backend without having to wire up the dependencies manually.

Factory
-------

.. autofunction:: ai_translate.translator.create_translator

Translators
-----------

.. autoclass:: ai_translate.translator.ImageTranslator
   :members:

.. autoclass:: ai_translate.translator.LangChainImageTranslator
   :members:

.. autoclass:: ai_translate.translator.MangaOCRTranslator
   :members:

OCR
---

.. autoclass:: ai_translate.ocr.MangaOCRWrapper
   :members:

Backends
--------

.. autofunction:: ai_translate.backends.create_llm

Schema
------

.. automodule:: ai_translate.schema
   :members:

Image Utilities
---------------

.. automodule:: ai_translate.image_utils
   :members:
