const form = document.getElementById("search-form");
const input = document.getElementById("search-input");
const button = document.getElementById("search-button");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = input.value.trim();
  if (!query) {
    return;
  }
  await runSearch(query);
});

async function runSearch(query) {
  setLoading(true);
  showStatus("Searching YouTube…");
  resultsEl.hidden = true;
  resultsEl.innerHTML = "";

  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    if (!response.ok) {
      let detail = "Unable to retrieve YouTube results.";
      try {
        const body = await response.json();
        if (typeof body?.detail === "string") {
          detail = body.detail;
        }
      } catch {
        // ignore
      }
      throw new Error(detail);
    }

    const data = await response.json();
    renderResults(data);
  } catch (error) {
    showStatus(error instanceof Error ? error.message : "Something went wrong.", true);
  } finally {
    setLoading(false);
  }
}

function setLoading(isLoading) {
  button.disabled = isLoading;
  input.disabled = isLoading;
  button.textContent = isLoading ? "Searching…" : "Search";
}

function showStatus(message, isError = false) {
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function hideStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
  statusEl.classList.remove("error");
}

function renderResults(data) {
  if (!data.creators || data.creators.length === 0) {
    showStatus("No relevant creators found.");
    resultsEl.hidden = true;
    return;
  }

  hideStatus();
  resultsEl.hidden = false;
  resultsEl.innerHTML = `
    <h2 class="results-heading">Results for “${escapeHtml(data.query)}”</h2>
    <p class="results-meta">Top creators · ${data.result_count} videos analyzed</p>
    <div class="creator-list">
      ${data.creators.map(renderCreator).join("")}
    </div>
  `;
}

function renderCreator(creator) {
  const subscribers =
    creator.subscribers == null
      ? "Subscribers hidden"
      : `${formatCompactNumber(creator.subscribers)} subscribers`;

  const avatar = creator.thumbnail
    ? `<img class="creator-avatar" src="${escapeAttr(creator.thumbnail)}" alt="" />`
    : `<div class="avatar-placeholder" aria-hidden="true"></div>`;

  return `
    <article class="creator-card">
      <div class="creator-header">
        ${avatar}
        <div class="creator-info">
          <h3>${escapeHtml(creator.channel_name)}</h3>
          <p>${subscribers}</p>
          <p>${creator.relevant_video_count} relevant video${
            creator.relevant_video_count === 1 ? "" : "s"
          }</p>
          <p>${formatCompactNumber(creator.combined_views)} combined views</p>
          <a class="channel-link" href="${escapeAttr(
            creator.channel_url
          )}" target="_blank" rel="noopener noreferrer">View Channel →</a>
        </div>
      </div>
      <ul class="video-list">
        ${(creator.videos || []).map(renderVideo).join("")}
      </ul>
    </article>
  `;
}

function renderVideo(video) {
  const thumb = video.thumbnail
    ? `<img class="video-thumb" src="${escapeAttr(video.thumbnail)}" alt="" />`
    : `<div class="thumb-placeholder" aria-hidden="true"></div>`;

  return `
    <li class="video-item">
      ${thumb}
      <div class="video-meta">
        <a href="${escapeAttr(video.url)}" target="_blank" rel="noopener noreferrer">
          ${escapeHtml(video.title)}
        </a>
        <p>${formatCompactNumber(video.views)} views · ${formatRelativeDate(
          video.published_at
        )}</p>
      </div>
    </li>
  `;
}

function formatCompactNumber(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "—";
  }
  const n = Number(value);
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000_000) return `${sign}${trimDecimal(abs / 1_000_000_000)}B`;
  if (abs >= 1_000_000) return `${sign}${trimDecimal(abs / 1_000_000)}M`;
  if (abs >= 1_000) return `${sign}${trimDecimal(abs / 1_000)}K`;
  return String(n);
}

function trimDecimal(n) {
  const rounded = Math.round(n * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

function formatRelativeDate(iso) {
  if (!iso) return "Unknown date";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown date";

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  const intervals = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];

  for (const [label, size] of intervals) {
    const count = Math.floor(seconds / size);
    if (count >= 1) {
      return `${count} ${label}${count === 1 ? "" : "s"} ago`;
    }
  }
  return "just now";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
