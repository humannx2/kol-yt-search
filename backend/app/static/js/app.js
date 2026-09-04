const form = document.getElementById("search-form");
const input = document.getElementById("search-input");
const button = document.getElementById("search-button");
const exportButton = document.getElementById("export-button");
const sortSelect = document.getElementById("sort-select");
const limitSelect = document.getElementById("limit-select");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

let lastQuery = "";
let allCreators = [];
let resultCount = 0;
let enrichToken = 0;

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

exportButton.addEventListener("click", () => {
  if (!allCreators.length || !lastQuery) {
    return;
  }
  downloadClientCsv();
});

async function runSearch(query) {
  setLoading(true);
  showStatus("Searching YouTube…");
  resultsEl.hidden = true;
  resultsEl.innerHTML = "";
  exportButton.disabled = true;
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
    exportButton.disabled = allCreators.length === 0;
  } catch (error) {
    lastQuery = "";
    allCreators = [];
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
  const needIds = visible
    .filter(
      (c) =>
        !c.email ||
        !c.phone ||
        !c.socials ||
        c.socials.length === 0
    )
    .map((c) => c.channel_id)
    .filter(Boolean);

  // #region agent log
  fetch("http://127.0.0.1:7909/ingest/64ba1ad6-78b7-4e0c-89f8-7fe1a6d84a5a", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Debug-Session-Id": "6b9c45",
    },
    body: JSON.stringify({
      sessionId: "6b9c45",
      hypothesisId: "D",
      location: "app.js:enrichVisible:start",
      message: "enrich_visible_start",
      data: {
        visible: visible.length,
        needIds: needIds.length,
        sampleIds: needIds.slice(0, 5),
      },
      timestamp: Date.now(),
    }),
  }).catch(() => {});
  // #endregion

  if (needIds.length === 0) {
    return;
  }

  const token = ++enrichToken;
  showEnrichHint(true);
  try {
    const params = new URLSearchParams({ ids: needIds.join(",") });
    const response = await fetch(`/api/enrich?${params.toString()}`);
    if (!response.ok || token !== enrichToken) {
      // #region agent log
      fetch("http://127.0.0.1:7909/ingest/64ba1ad6-78b7-4e0c-89f8-7fe1a6d84a5a", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Debug-Session-Id": "6b9c45",
        },
        body: JSON.stringify({
          sessionId: "6b9c45",
          hypothesisId: "E",
          location: "app.js:enrichVisible:response",
          message: "enrich_response_skipped",
          data: { ok: response.ok, status: response.status, tokenMatch: token === enrichToken },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      return;
    }
    const data = await response.json();
    if (token !== enrichToken) {
      return;
    }
    const channels = data.channels || {};
    let changed = false;
    let matched = 0;
    let withAnyContact = 0;
    for (const creator of allCreators) {
      const payload = channels[creator.channel_id];
      if (!payload) {
        continue;
      }
      matched += 1;
      if (payload.email || payload.phone || (payload.socials && payload.socials.length)) {
        withAnyContact += 1;
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
    // #region agent log
    fetch("http://127.0.0.1:7909/ingest/64ba1ad6-78b7-4e0c-89f8-7fe1a6d84a5a", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Debug-Session-Id": "6b9c45",
      },
      body: JSON.stringify({
        sessionId: "6b9c45",
        hypothesisId: "D",
        location: "app.js:enrichVisible:merge",
        message: "enrich_merge_result",
        data: {
          channelKeys: Object.keys(channels).length,
          matched,
          withAnyContact,
          changed,
          willRerender: changed && token === enrichToken,
        },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    if (changed && token === enrichToken) {
      const sort = sortSelect.value;
      const limit = Number(limitSelect.value) || 5;
      const nextVisible = sortCreators(allCreators, sort).slice(0, limit);
      renderResults(lastQuery, resultCount, sort, nextVisible, allCreators.length);
    }
  } finally {
    if (token === enrichToken) {
      showEnrichHint(false);
    }
  }
}

function showEnrichHint(show) {
  let hint = document.getElementById("enrich-hint");
  if (!show) {
    if (hint) {
      hint.remove();
    }
    return;
  }
  if (!hint) {
    hint = document.createElement("p");
    hint.id = "enrich-hint";
    hint.className = "enrich-hint";
    hint.textContent = "Loading contacts…";
    resultsEl.prepend(hint);
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

function renderResults(query, videosAnalyzed, sort, visible, poolSize) {
  hideStatus();
  resultsEl.hidden = false;
  resultsEl.innerHTML = `
    <h2 class="results-heading">Results for “${escapeHtml(query)}”</h2>
    <p class="results-meta">
      Top creators (India or unknown country) · ${videosAnalyzed} videos analyzed ·
      pool ${poolSize} · sort: ${escapeHtml(sort)} · showing ${visible.length}
    </p>
    <div class="creator-list">
      ${visible.map(renderCreator).join("")}
    </div>
  `;
}

function renderCreator(creator) {
  const subscribers =
    creator.subscribers == null
      ? "Subscribers hidden"
      : `${formatCompactNumber(creator.subscribers)} subscribers`;

  const countryLabel = creator.country || "Unknown";
  const avatar = creator.thumbnail
    ? `<img class="creator-avatar" src="${escapeAttr(creator.thumbnail)}" alt="" />`
    : `<div class="avatar-placeholder" aria-hidden="true"></div>`;

  const contactBits = [];
  if (creator.email) {
    contactBits.push(
      `<p>Email: <a href="mailto:${escapeAttr(creator.email)}">${escapeHtml(
        creator.email
      )}</a></p>`
    );
  }
  if (creator.phone) {
    contactBits.push(`<p>Phone: ${escapeHtml(creator.phone)}</p>`);
  }
  if (creator.socials && creator.socials.length > 0) {
    const allowed = new Set(["x", "telegram", "instagram"]);
    const labels = { x: "X", telegram: "Telegram", instagram: "Instagram" };
    const links = creator.socials
      .filter((s) => allowed.has(String(s.platform || "").toLowerCase()))
      .map((s) => {
        const platform = String(s.platform || "").toLowerCase();
        const label = labels[platform] || platform;
        const href = s.value.startsWith("http") ? s.value : null;
        if (href) {
          return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
            label
          )}</a>`;
        }
        return `<span>${escapeHtml(label)}: ${escapeHtml(s.value)}</span>`;
      })
      .join(" · ");
    if (links) {
      contactBits.push(`<p class="socials">Socials: ${links}</p>`);
    }
  }

  return `
    <article class="creator-card" data-channel-id="${escapeAttr(creator.channel_id)}">
      <div class="creator-header">
        ${avatar}
        <div class="creator-info">
          <div class="title-row">
            <h3>${escapeHtml(creator.channel_name)}</h3>
            <span class="badge">${escapeHtml(countryLabel)}</span>
          </div>
          <p>${subscribers}</p>
          <p>${creator.relevant_video_count} relevant video${
            creator.relevant_video_count === 1 ? "" : "s"
          }</p>
          <p>${formatCompactNumber(creator.combined_views)} combined views</p>
          ${contactBits.join("")}
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
