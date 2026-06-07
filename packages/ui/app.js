const API_BASE = window.API_BASE || "http://localhost:8000";
const NO_AUTH = window.NO_AUTH === true || window.NO_AUTH === "true";

// ── Auth state ───────────────────────────────────────────────────────────────
let authToken = sessionStorage.getItem("manga_ai_token") || "";

function authHeaders() {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (resp.status === 401) {
    showAuthError("Token rejected (401). Please provide a valid token.");
    throw new Error("Unauthorized");
  }
  return resp;
}

function applyToken() {
  const input = document.getElementById("token-input");
  authToken = input.value.trim();
  if (!authToken) {
    showAuthError("Please paste a token.");
    return;
  }
  sessionStorage.setItem("manga_ai_token", authToken);
  document.getElementById("auth-error").textContent = "";
  document.getElementById("auth-section").style.display = "none";
  document.getElementById("main-section").style.display = "block";
  refreshJobs();
}

function showAuthError(msg) {
  document.getElementById("auth-error").textContent = msg;
}

// Show main section if auth is disabled or a token is already present
if (NO_AUTH || authToken) {
  document.getElementById("auth-section").style.display = "none";
  document.getElementById("main-section").style.display = "block";
  if (NO_AUTH) refreshJobs();
}

// ── Search ───────────────────────────────────────────────────────────────────
const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const mangaResults = document.getElementById("manga-results");
const chapterResults = document.getElementById("chapter-results");
const chapterImages = document.getElementById("chapter-images");

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;

  const response = await apiFetch(`/manga/search?query=${encodeURIComponent(query)}`);
  const data = await response.json();
  mangaResults.innerHTML = "";
  chapterResults.innerHTML = "";
  chapterImages.innerHTML = "";

  data.results.forEach((manga) => {
    const li = document.createElement("li");
    li.className = "manga-item";

    const btn = document.createElement("button");
    btn.textContent = `${manga.title} (${manga.id})`;
    btn.onclick = () => loadChapters(manga.id);

    const enqueueBtn = document.createElement("button");
    enqueueBtn.textContent = "⏳ Enqueue";
    enqueueBtn.className = "enqueue-btn";
    enqueueBtn.title = "Enqueue all chapters for background translation";
    enqueueBtn.onclick = () => enqueueManga(manga.id, manga.title, enqueueBtn);

    li.appendChild(btn);
    li.appendChild(enqueueBtn);
    mangaResults.appendChild(li);
  });
});

// ── Chapters ─────────────────────────────────────────────────────────────────
async function loadChapters(mangaId) {
  const response = await apiFetch(`/manga/${mangaId}/chapters`);
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
  const response = await apiFetch(`/chapters/${chapterId}`);
  const data = await response.json();
  chapterImages.innerHTML = "";

  data.images.forEach((img) => {
    const image = document.createElement("img");
    image.className = "page-img";
    // Include auth token as query param is not ideal; use in-browser fetch + blob URL instead
    apiFetch(img.endpoint).then((r) => r.blob()).then((blob) => {
      image.src = URL.createObjectURL(blob);
    });
    chapterImages.appendChild(image);
  });
}

// ── Translation queue ─────────────────────────────────────────────────────────
async function enqueueManga(mangaId, mangaTitle, btn) {
  btn.disabled = true;
  btn.textContent = "Queuing…";
  try {
    const resp = await apiFetch(`/manga/${mangaId}/enqueue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manga_title: mangaTitle, target_language: "en" }),
    });
    if (resp.ok) {
      const data = await resp.json();
      btn.textContent = `✅ Job #${data.job_id}`;
      refreshJobs();
    } else {
      btn.textContent = "⚠️ Error";
      btn.disabled = false;
    }
  } catch {
    btn.textContent = "⚠️ Error";
    btn.disabled = false;
  }
}

async function refreshJobs() {
  const jobList = document.getElementById("job-list");
  try {
    const resp = await apiFetch("/jobs");
    const data = await resp.json();
    if (!data.jobs || data.jobs.length === 0) {
      jobList.innerHTML = "<em>No jobs yet.</em>";
      return;
    }
    jobList.innerHTML = data.jobs
      .map((j) => {
        const pct = j.total_chapters > 0
          ? Math.round((j.processed_chapters / j.total_chapters) * 100)
          : 0;
        return `<div class="job-row">
          <span><strong>#${j.job_id}</strong> ${escHtml(j.manga_title || j.manga_id)}</span>
          <span class="status-${j.status}">${j.status}</span>
          <span>${j.processed_chapters}/${j.total_chapters} chapters${j.total_chapters > 0 ? ` (${pct}%)` : ""}</span>
        </div>`;
      })
      .join("");
  } catch {
    jobList.innerHTML = "<em>Could not load jobs.</em>";
  }
}

function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Auto-refresh queue every 10 seconds if there are running jobs
setInterval(async () => {
  const jobList = document.getElementById("job-list");
  if (jobList && jobList.querySelector(".status-running, .status-pending")) {
    await refreshJobs();
  }
}, 10000);

