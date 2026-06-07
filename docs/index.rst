Manga AI Documentation
======================

**Manga AI** is a monorepo that combines a MangaDex API client, an AI-powered
manga image translator, and a FastAPI service for end-to-end manga translation.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   setup
   api/ai_translate
   api/manga_dex
   api/api

Overview
--------

The project is structured as three Python packages:

* :mod:`ai_translate` — Vision-LLM and manga-ocr based manga page translator.
* :mod:`manga_dex` — Async MangaDex client with SQLite caching.
* :mod:`api` — FastAPI service that wires the two packages together.

Quick Start
-----------

.. code-block:: python

   from ai_translate import create_translator

   # Standard LLM-only translator (default)
   translator = create_translator(backend="openai")

   # High-accuracy translator with manga-ocr pre-processing
   translator = create_translator(backend="openai", use_manga_ocr=True)

   # Translate a page
   translated_bytes = await translator.translate_image(
       image_bytes=open("page.jpg", "rb").read(),
       source_language="ja",
       target_language="en",
   )

Indices and Tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
