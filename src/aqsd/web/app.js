const state = {
  lastExpandedQueries: [],
};

const elements = {
  health: document.getElementById("health-status"),
  formError: document.getElementById("form-error"),
  loading: document.getElementById("loading"),
  expandedQueries: document.getElementById("expanded-queries"),
  results: document.getElementById("results"),
  diagnostics: document.getElementById("diagnostics"),
  searchForm: document.getElementById("search-form"),
  resolveButton: document.getElementById("resolve-button"),
  query: document.getElementById("query"),
  episode: document.getElementById("episode"),
  resolution: document.getElementById("resolution"),
  subtitle: document.getElementById("subtitle"),
  group: document.getElementById("group"),
  rawOnly: document.getElementById("raw-only"),
  excludeBatch: document.getElementById("exclude-batch"),
  limit: document.getElementById("limit"),
};

document.addEventListener("DOMContentLoaded", () => {
  void loadHealth();
  elements.resolveButton.addEventListener("click", () => {
    void handleResolveTitle();
  });
  elements.searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void handleSearch();
  });
});

async function loadHealth() {
  elements.health.textContent = "Loading health status...";
  try {
    const payload = await apiRequest("/api/health", { method: "GET" });
    renderHealth(payload);
  } catch (error) {
    elements.health.innerHTML = `<div class="error message">Failed to load health: ${escapeHtml(error.message)}</div>`;
  }
}

async function handleResolveTitle() {
  clearFormError();
  const query = elements.query.value.trim();
  if (!query) {
    showFormError("Please enter an anime title before resolving.");
    return;
  }

  setLoading(true, "Resolving title...");
  try {
    const payload = await apiRequest("/api/resolve-title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    state.lastExpandedQueries = payload.expanded_queries || [];
    renderExpandedQueries(state.lastExpandedQueries);
    renderDiagnostics({
      original_query: query,
      expanded_queries: payload.expanded_queries || [],
      sources: payload.sources || [],
      active_filters: {},
      candidate_count_before_filter: null,
      candidate_count_after_filter: null,
      suggestions: [],
    });
  } catch (error) {
    showFormError(`Resolve title failed: ${error.message}`);
  } finally {
    setLoading(false);
  }
}

async function handleSearch() {
  clearFormError();
  const payload = buildSearchPayload();
  if (!payload.query) {
    showFormError("Please enter an anime title before searching.");
    return;
  }

  setLoading(true, "Searching...");
  elements.results.innerHTML = "";
  try {
    const response = await apiRequest("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.lastExpandedQueries = response.expanded_queries || [];
    renderExpandedQueries(state.lastExpandedQueries);
    renderResults(response.candidates || []);
    renderDiagnostics(response.diagnostics || null, response.candidates || []);
  } catch (error) {
    renderResults([]);
    renderDiagnostics(null, []);
    showFormError(`Search failed: ${error.message}`);
  } finally {
    setLoading(false);
  }
}

function buildSearchPayload() {
  return {
    query: elements.query.value.trim(),
    episode: normalizeOptionalText(elements.episode.value),
    resolution: normalizeOptionalText(elements.resolution.value),
    subtitle: normalizeOptionalText(elements.subtitle.value),
    group: normalizeOptionalText(elements.group.value),
    raw_only: elements.rawOnly.checked,
    exclude_batch: elements.excludeBatch.checked,
    limit: normalizeLimit(elements.limit.value),
  };
}

function renderHealth(payload) {
  const qb = payload.qbittorrent || {};
  const sources = payload.sources || {};
  const anilist = payload.anilist || {};
  const qbLabel = qb.reachable ? "reachable" : "unreachable";
  const qbError = qb.error ? ` (${escapeHtml(qb.error)})` : "";

  elements.health.innerHTML = `
    <div><strong>qBittorrent:</strong> ${qbLabel}${qbError}</div>
    <ul class="status-list">
      <li>RSS: ${boolLabel(sources.rss)}</li>
      <li>Nyaa: ${boolLabel(sources.nyaa)}</li>
      <li>Torznab: ${boolLabel(sources.torznab)}</li>
      <li>AniList: ${boolLabel(anilist.enabled)}</li>
    </ul>
  `;
}

function renderExpandedQueries(queries) {
  if (!queries || queries.length === 0) {
    elements.expandedQueries.textContent = "No queries resolved yet.";
    return;
  }
  elements.expandedQueries.innerHTML = `
    <ul class="simple-list">
      ${queries.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
}

function renderResults(candidates) {
  if (!candidates || candidates.length === 0) {
    elements.results.innerHTML = `<div class="muted">No candidates to display.</div>`;
    return;
  }

  elements.results.innerHTML = candidates
    .map((candidate) => {
      const parsed = candidate.parsed || {};
      const breakdown = Array.isArray(candidate.breakdown) ? candidate.breakdown : [];
      return `
        <article class="candidate-card">
          <div class="candidate-title">#${candidate.rank} ${escapeHtml(candidate.title || "-")}</div>
          <div class="meta-line">
            <div><strong>Score:</strong> ${formatValue(candidate.score)}</div>
            <div><strong>Source:</strong> ${escapeHtml(candidate.source || "-")}</div>
            <div><strong>Seeders:</strong> ${formatValue(candidate.seeders)}</div>
            <div><strong>Published:</strong> ${escapeHtml(formatDate(candidate.published_at))}</div>
            <div><strong>Magnet:</strong> ${candidate.magnet ? "yes" : "no"}</div>
            <div><strong>URL:</strong> ${candidate.url ? "yes" : "no"}</div>
          </div>
          <div class="section-label">Parsed</div>
          <div class="parsed-grid">
            <div>episode: ${escapeHtml(formatValue(parsed.episode))}</div>
            <div>resolution: ${escapeHtml(formatValue(parsed.resolution))}</div>
            <div>group: ${escapeHtml(formatValue(parsed.group))}</div>
            <div>subtitle: ${escapeHtml(formatValue(parsed.subtitle_type))}</div>
            <div>is_batch: ${boolOrUnknown(parsed.is_batch)}</div>
            <div>is_raw: ${boolOrUnknown(parsed.is_raw)}</div>
          </div>
          <div class="section-label">Reasons</div>
          ${renderReasons(breakdown)}
        </article>
      `;
    })
    .join("");
}

function renderReasons(reasons) {
  if (!reasons || reasons.length === 0) {
    return `<div class="muted">No breakdown reasons available.</div>`;
  }
  return `
    <ul class="reason-list">
      ${reasons
        .map((reason) => `<li>${formatDelta(reason.delta)} ${escapeHtml(reason.message || "")}</li>`)
        .join("")}
    </ul>
  `;
}

function renderDiagnostics(diagnostics, candidates = []) {
  if (!diagnostics) {
    elements.diagnostics.innerHTML = `<div class="muted">Search diagnostics will appear here when available.</div>`;
    return;
  }

  const beforeCount = diagnostics.candidate_count_before_filter;
  const afterCount = diagnostics.candidate_count_after_filter;
  const noCandidatesNotice =
    Array.isArray(candidates) && candidates.length === 0
      ? `<p><strong>No good candidates found.</strong></p>`
      : "";
  const filteredNotice =
    beforeCount !== null && beforeCount > 0 && (afterCount || 0) === 0
      ? `<p>Candidates were found, but all were filtered out.</p>`
      : "";

  elements.diagnostics.innerHTML = `
    <div class="diagnostic-block">
      ${noCandidatesNotice}
      ${filteredNotice}
      ${renderKeyValueList("Tried queries", diagnostics.expanded_queries)}
      ${renderKeyValueList("Sources", diagnostics.sources)}
      ${renderObjectList("Active filters", diagnostics.active_filters)}
      ${renderCountBlock(beforeCount, afterCount)}
      ${renderKeyValueList("Suggestions", diagnostics.suggestions)}
    </div>
  `;
}

function renderKeyValueList(title, items) {
  const values = Array.isArray(items) && items.length > 0 ? items : ["-"];
  return `
    <div class="section-label">${escapeHtml(title)}</div>
    <ul class="kv-list">
      ${values.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}
    </ul>
  `;
}

function renderObjectList(title, values) {
  const entries = values && Object.keys(values).length > 0 ? Object.entries(values) : [["none", "-"]];
  return `
    <div class="section-label">${escapeHtml(title)}</div>
    <ul class="kv-list">
      ${entries.map(([key, value]) => `<li>${escapeHtml(key)}: ${escapeHtml(String(value))}</li>`).join("")}
    </ul>
  `;
}

function renderCountBlock(beforeCount, afterCount) {
  if (beforeCount === null && afterCount === null) {
    return "";
  }
  return `
    <div class="section-label">Candidate counts</div>
    <ul class="kv-list">
      <li>before filter: ${escapeHtml(formatValue(beforeCount))}</li>
      <li>after filter: ${escapeHtml(formatValue(afterCount))}</li>
    </ul>
  `;
}

async function apiRequest(url, options) {
  const response = await fetch(url, options);
  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    if (isJson && payload && typeof payload.detail === "string") {
      throw new Error(payload.detail);
    }
    throw new Error(typeof payload === "string" ? payload : `HTTP ${response.status}`);
  }
  return payload;
}

function setLoading(enabled, text = "Loading...") {
  elements.loading.textContent = text;
  elements.loading.classList.toggle("hidden", !enabled);
  elements.resolveButton.disabled = enabled;
  elements.searchForm.querySelector("#search-button").disabled = enabled;
}

function showFormError(message) {
  elements.formError.textContent = message;
  elements.formError.classList.remove("hidden");
}

function clearFormError() {
  elements.formError.textContent = "";
  elements.formError.classList.add("hidden");
}

function normalizeOptionalText(value) {
  const trimmed = String(value || "").trim();
  return trimmed || null;
}

function normalizeLimit(value) {
  const parsed = Number.parseInt(String(value || "20"), 10);
  if (Number.isNaN(parsed)) {
    return 20;
  }
  return Math.max(1, Math.min(parsed, 100));
}

function boolLabel(value) {
  return value ? "enabled" : "disabled";
}

function boolOrUnknown(value) {
  if (value === true) {
    return "yes";
  }
  if (value === false) {
    return "no";
  }
  return "unknown";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  return String(value).replace("T", " ").replace(/:\d{2}(?:\.\d+)?(?:\+.*|Z)?$/, "");
}

function formatDelta(value) {
  const numeric = Number(value || 0);
  const rounded = Number.isInteger(numeric) ? numeric.toString() : numeric.toFixed(1).replace(/\.0$/, "");
  return numeric >= 0 ? `+${rounded}` : rounded;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
