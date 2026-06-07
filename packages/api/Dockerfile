FROM python:3.14-slim

WORKDIR /app

# Install packages in dependency order so local inter-package deps resolve correctly.
COPY packages/ai_translate packages/ai_translate
COPY packages/manga_dex packages/manga_dex
COPY packages/api packages/api

RUN pip install --no-cache-dir \
    ./packages/ai_translate \
    ./packages/manga_dex \
    ./packages/api

# Pre-create cache directory
RUN mkdir -p /app/cache/translated

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
