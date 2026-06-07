api
===

The ``api`` package exposes a FastAPI application that ties the
:mod:`manga_dex` client and :mod:`ai_translate` translator together behind
an HTTP interface.

Endpoints
---------

.. automodule:: api.main
   :members:

``GET /health``
   Returns ``{"status": "ok"}`` when the service is running.

``GET /manga/search?query=<title>``
   Full-text search for manga titles on MangaDex.

``GET /manga/{manga_id}/chapters``
   List available chapters for a manga, sorted by language priority and
   chapter number.

``GET /chapters/{chapter_id}``
   Return page metadata for a chapter, including pre-signed image endpoints.

``GET /chapters/{chapter_id}/images/{page_index}``
   Fetch (and optionally translate) a single manga page image.
