from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from manga_dex import MangaDexClient

app = FastAPI(title="Manga AI API")


@lru_cache(maxsize=1)
def get_client() -> MangaDexClient:
    return MangaDexClient()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/manga/search")
async def search_manga(
    query: str = Query(..., min_length=1),
    client: MangaDexClient = Depends(get_client),
) -> dict[str, object]:
    results = await client.search_manga(query)
    return {"results": results}


@app.get("/manga/{manga_id}/chapters")
async def manga_chapters(
    manga_id: str,
    client: MangaDexClient = Depends(get_client),
) -> dict[str, object]:
    chapters = await client.get_chapters(manga_id)
    return {"chapters": chapters}


@app.get("/chapters/{chapter_id}")
async def chapter_images(
    chapter_id: str,
    target_language: str = "en",
    client: MangaDexClient = Depends(get_client),
) -> dict[str, object]:
    images = await client.get_chapter_images(chapter_id, target_language)
    for page in images:
        page["endpoint"] = f"/chapters/{chapter_id}/images/{page['page_index']}?target_language={target_language}"
    return {"chapter_id": chapter_id, "images": images}


@app.get("/chapters/{chapter_id}/images/{page_index}")
async def chapter_image(
    chapter_id: str,
    page_index: int,
    target_language: str = "en",
    client: MangaDexClient = Depends(get_client),
) -> Response:
    try:
        content = await client.get_page_bytes(chapter_id, page_index, target_language=target_language)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=content, media_type="image/jpeg")
