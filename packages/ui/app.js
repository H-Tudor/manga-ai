const API_BASE = window.API_BASE || "http://localhost:8000";

const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const mangaResults = document.getElementById("manga-results");
const chapterResults = document.getElementById("chapter-results");
const chapterImages = document.getElementById("chapter-images");

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;

  const response = await fetch(`${API_BASE}/manga/search?query=${encodeURIComponent(query)}`);
  const data = await response.json();
  mangaResults.innerHTML = "";
  chapterResults.innerHTML = "";
  chapterImages.innerHTML = "";

  data.results.forEach((manga) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = `${manga.title} (${manga.id})`;
    button.onclick = () => loadChapters(manga.id);
    li.appendChild(button);
    mangaResults.appendChild(li);
  });
});

async function loadChapters(mangaId) {
  const response = await fetch(`${API_BASE}/manga/${mangaId}/chapters`);
  const data = await response.json();
  chapterResults.innerHTML = "";
  chapterImages.innerHTML = "";

  data.chapters.forEach((chapter) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = `Chapter ${chapter.chapter || "?"} (${chapter.language})`;
    button.onclick = () => loadChapterImages(chapter.id);
    li.appendChild(button);
    chapterResults.appendChild(li);
  });
}

async function loadChapterImages(chapterId) {
  const response = await fetch(`${API_BASE}/chapters/${chapterId}`);
  const data = await response.json();
  chapterImages.innerHTML = "";

  data.images.forEach((img) => {
    const image = document.createElement("img");
    image.src = `${API_BASE}${img.endpoint}`;
    image.style.maxWidth = "800px";
    image.style.display = "block";
    image.style.marginBottom = "1rem";
    chapterImages.appendChild(image);
  });
}
