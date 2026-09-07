const form = document.getElementById("search-form");
const input = document.getElementById("search-input");
const button = document.getElementById("search-button");
const sortSelect = document.getElementById("sort-select");
const limitSelect = document.getElementById("limit-select");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const idleHint = document.getElementById("idle-hint");

let lastQuery = "";
let allCreators = [];
let resultCount = 0;
let enrichToken = 0;
let enrichActive = false;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = input.value.trim();
  if (!query) {
    return;
  }
  await runSearch(query);
});

sortSelect.addEventListener("change", () => {
  if (!allCreators.length) {
    return;
  }
  applyView();
});

limitSelect.addEventListener("change", () => {
  if (!allCreators.length) {
    return;
  }
  applyView();
});

resultsEl.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) {
    return;
  }
  const exportBtn = target.closest("#export-button");
  if (!exportBtn || exportBtn.hasAttribute("disabled")) {
    return;
  }
  if (!allCreators.length || !lastQuery) {
    return;
  }
  downloadClientCsv();
});

async function runSearch(query) {
  setLoading(true);
  hideStatus();
  if (idleHint) {
    idleHint.hidden = true;
  }
  showSkeletons();
  allCreators = [];

  try {
    const params = new URLSearchParams({ q: query });
    const response = await fetch(`/api/search?${params.toString()}`);
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
    lastQuery = data.query || query;
    resultCount = data.result_count || 0;
    allCreators = Array.isArray(data.creators) ? data.creators : [];
    applyView();
  } catch (error) {
    lastQuery = "";
    allCreators = [];
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    showStatus(error instanceof Error ? error.message : "Something went wrong.", true);
  } finally {
    setLoading(false);
  }
}

function applyView() {
  const sort = sortSelect.value;
  const limit = Number(limitSelect.value) || 5;
  const visible = sortCreators(allCreators, sort).slice(0, limit);

  if (visible.length === 0) {
    showStatus("No relevant creators found.");
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    return;
  }

  renderResults(lastQuery, resultCount, sort, visible, allCreators.length);
  enrichVisible(visible);
}

function sortCreators(creators, sort) {
  const copy = [...creators];
  if (sort === "subscribers") {
    copy.sort((a, b) => {
      const aHas = a.subscribers != null ? 1 : 0;
      const bHas = b.subscribers != null ? 1 : 0;
      if (bHas !== aHas) return bHas - aHas;
      if ((b.subscribers || 0) !== (a.subscribers || 0)) {
        return (b.subscribers || 0) - (a.subscribers || 0);
      }
      if (b.relevant_video_count !== a.relevant_video_count) {
        return b.relevant_video_count - a.relevant_video_count;
      }
      return b.combined_views - a.combined_views;
    });
    return copy;
  }
  if (sort === "views") {
    copy.sort((a, b) => {
      if (b.combined_views !== a.combined_views) {
        return b.combined_views - a.combined_views;
      }
      if (b.relevant_video_count !== a.relevant_video_count) {
        return b.relevant_video_count - a.relevant_video_count;
      }
      return (b.subscribers || 0) - (a.subscribers || 0);
    });
    return copy;
  }
  copy.sort((a, b) => {
    if (b.relevant_video_count !== a.relevant_video_count) {
      return b.relevant_video_count - a.relevant_video_count;
    }
    return b.combined_views - a.combined_views;
  });
  return copy;
}

async function enrichVisible(visible) {
  const need = visible.filter(
    (c) =>
      c.channel_id &&
      (!c.email || !c.phone || !c.socials || c.socials.length === 0)
  );

  if (need.length === 0) {
    return;
  }

  const token = ++enrichToken;
  showEnrichHint(true);
  try {
    const response = await fetch("/api/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channels: need.map((c) => ({
          channel_id: c.channel_id,
          channel_name: c.channel_name || "",
          subscribers: c.subscribers ?? null,
        })),
      }),
    });
    if (!response.ok || token !== enrichToken) {
      return;
    }
    const data = await response.json();
    if (token !== enrichToken) {
      return;
    }
    const channels = data.channels || {};
    let changed = false;
    for (const creator of allCreators) {
      const payload = channels[creator.channel_id];
      if (!payload) {
        continue;
      }
      if (!creator.email && payload.email) {
        creator.email = payload.email;
        changed = true;
      }
      if (!creator.phone && payload.phone) {
        creator.phone = payload.phone;
        changed = true;
      }
      const existing = new Set(
        (creator.socials || []).map((s) => `${s.platform}:${s.value.toLowerCase()}`)
      );
      const merged = [...(creator.socials || [])];
      for (const social of payload.socials || []) {
        const platform = String(social.platform || "").toLowerCase();
        if (!["x", "telegram", "instagram"].includes(platform)) {
          continue;
        }
        const key = `${platform}:${String(social.value).toLowerCase()}`;
        if (existing.has(key)) {
          continue;
        }
        merged.push({ platform, value: social.value });
        existing.add(key);
        changed = true;
      }
      creator.socials = merged;
    }
    if (changed && token === enrichToken) {
      const sort = sortSelect.value;
      const limit = Number(limitSelect.value) || 5;
      const nextVisible = sortCreators(allCreators, sort).slice(0, limit);
      renderResults(lastQuery, resultCount, sort, nextVisible, allCreators.length);
      if (enrichActive) {
        showEnrichHint(true);
      }
    }
  } finally {
    if (token === enrichToken) {
      showEnrichHint(false);
    }
  }
}

function showEnrichHint(show) {
  enrichActive = show;
  let hint = document.getElementById("enrich-hint");
  if (!show) {
    if (hint) {
      hint.remove();
    }
    return;
  }
  if (!hint && !resultsEl.hidden) {
    hint = document.createElement("p");
    hint.id = "enrich-hint";
    hint.className = "enrich-hint";
    hint.textContent = "Finding contacts…";
    const toolbar = resultsEl.querySelector(".results-toolbar");
    if (toolbar) {
      toolbar.insertAdjacentElement("afterend", hint);
    } else {
      resultsEl.prepend(hint);
    }
  }
}

function setLoading(isLoading) {
  button.disabled = isLoading;
  input.disabled = isLoading;
  sortSelect.disabled = isLoading;
  limitSelect.disabled = isLoading;
  button.textContent = isLoading ? "Searching…" : "Search";
}

function showSkeletons() {
  resultsEl.hidden = false;
  resultsEl.innerHTML = `
    <div class="skeleton-list" aria-hidden="true">
      <div class="skeleton-card"></div>
      <div class="skeleton-card"></div>
      <div class="skeleton-card"></div>
    </div>
  `;
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

function renderResults(query, videosAnalyzed, sort, visible, poolSize) {
  hideStatus();
  resultsEl.hidden = false;
  const sortLabel =
    sort === "subscribers" ? "subscribers" : sort === "views" ? "views" : "relevance";

  resultsEl.innerHTML = `
    <div class="results-toolbar">
      <div>
        <h2 class="results-heading">Results for “${escapeHtml(query)}”</h2>
        <p class="results-meta">
          India or unknown country · ${videosAnalyzed} videos analyzed ·
          pool ${poolSize} · ${escapeHtml(sortLabel)} · showing ${visible.length}
        </p>
      </div>
      <button id="export-button" class="btn btn-ghost" type="button">
        Export CSV
      </button>
    </div>
    <div class="creator-list">
      ${visible.map(renderCreator).join("")}
    </div>
  `;
}

function renderCreator(creator) {
  const subsValue =
    creator.subscribers == null
      ? "Hidden"
      : formatCompactNumber(creator.subscribers);
  const countryLabel = creator.country || "Unknown";
  const avatar = creator.thumbnail
    ? `<img class="creator-avatar" src="${escapeAttr(creator.thumbnail)}" alt="" />`
    : `<div class="avatar-placeholder" aria-hidden="true"></div>`;

  return `
    <article class="creator-card" data-channel-id="${escapeAttr(creator.channel_id)}">
      <div class="creator-header">
        ${avatar}
        <div class="creator-info">
          <div class="title-row">
            <h3>${escapeHtml(creator.channel_name)}</h3>
            <span class="badge">${escapeHtml(countryLabel)}</span>
          </div>
          <ul class="metrics">
            <li>
              <span class="label">Subscribers</span>
              <span class="value">${escapeHtml(subsValue)}</span>
            </li>
            <li>
              <span class="label">Relevant videos</span>
              <span class="value">${creator.relevant_video_count}</span>
            </li>
            <li>
              <span class="label">Combined views</span>
              <span class="value">${formatCompactNumber(creator.combined_views)}</span>
            </li>
          </ul>
          ${renderContacts(creator)}
          <a class="channel-link" href="${escapeAttr(
            creator.channel_url
          )}" target="_blank" rel="noopener noreferrer">View channel →</a>
        </div>
      </div>
      <ul class="video-list">
        ${(creator.videos || []).map(renderVideo).join("")}
      </ul>
    </article>
  `;
}

function renderContacts(creator) {
  const chips = [];

  if (creator.email) {
    chips.push(
      `<a class="chip" href="mailto:${escapeAttr(creator.email)}">${escapeHtml(
        creator.email
      )}</a>`
    );
  }
  if (creator.phone) {
    chips.push(`<span class="chip">${escapeHtml(creator.phone)}</span>`);
  }
  if (creator.socials && creator.socials.length > 0) {
    const allowed = new Set(["x", "telegram", "instagram"]);
    const labels = { x: "X", telegram: "Telegram", instagram: "Instagram" };
    for (const s of creator.socials) {
      const platform = String(s.platform || "").toLowerCase();
      if (!allowed.has(platform)) {
        continue;
      }
      const label = labels[platform] || platform;
      if (s.value.startsWith("http")) {
        chips.push(
          `<a class="chip" href="${escapeAttr(
            s.value
          )}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`
        );
      } else {
        chips.push(
          `<span class="chip">${escapeHtml(label)}: ${escapeHtml(s.value)}</span>`
        );
      }
    }
  }

  if (chips.length === 0) {
    return "";
  }
  return `<div class="contacts">${chips.join("")}</div>`;
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

function downloadClientCsv() {
  const sort = sortSelect.value;
  const limit = Number(limitSelect.value) || 5;
  const visible = sortCreators(allCreators, sort).slice(0, limit);
  const header = [
    "query_used",
    "relevant_video_count",
    "subs",
    "views",
    "socials",
    "mobile number",
    "email",
    "country",
  ];
  const rows = visible.map((c) => [
    lastQuery,
    c.relevant_video_count,
    c.subscribers == null ? "" : c.subscribers,
    c.combined_views,
    formatSocialsExport(c.socials || []),
    c.phone || "",
    c.email || "",
    c.country || "",
  ]);
  const csv = [header, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "creators_export.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function formatSocialsExport(socials) {
  const allowed = new Set(["x", "telegram", "instagram"]);
  return socials
    .filter((s) => allowed.has(String(s.platform || "").toLowerCase()))
    .map((s) => `${String(s.platform).toLowerCase()}:${s.value}`)
    .join("; ");
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) {
    return `"${text.replaceAll('"', '""')}"`;
  }
  return text;
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
