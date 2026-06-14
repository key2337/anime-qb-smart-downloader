const state = {
  lastExpandedQueries: [],
  lastExpandedQueryDetails: [],
  lastQuery: "",
  allCandidates: [],
  carts: [],
};

const elements = {
  health: document.getElementById("health-status"),
  formError: document.getElementById("form-error"),
  loading: document.getElementById("loading"),
  expandedQueries: document.getElementById("expanded-queries"),
  results: document.getElementById("results"),
  diagnostics: document.getElementById("diagnostics"),
  searchForm: document.getElementById("search-form"),

  query: document.getElementById("query"),
  episode: document.getElementById("episode"),
  resolution: document.getElementById("resolution"),
  subtitle: document.getElementById("subtitle"),
  group: document.getElementById("group"),
  season: document.getElementById("season"),
  releaseMode: document.getElementById("release-mode"),
  limit: document.getElementById("limit"),
  carts: document.getElementById("carts"),
};

document.addEventListener("DOMContentLoaded", () => {
  void loadHealth();
  void loadCarts();

  elements.searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void handleSearch();
  });
  elements.results.addEventListener("click", (event) => {
    const button = event.target.closest(".toggle-details");
    if (button) {
      toggleCandidateDetails(button);
      return;
    }
    const downloadBtn = event.target.closest(".download-button");
    if (downloadBtn) {
      void handleDownload(downloadBtn);
    }
  });
  elements.carts.addEventListener("click", (event) => {
    const startBtn = event.target.closest(".cart-start-button");
    if (startBtn) {
      void handleStartCart(startBtn);
      return;
    }
    const deleteBtn = event.target.closest(".cart-delete-button");
    if (deleteBtn) {
      void handleDeleteCart(deleteBtn);
      return;
    }
  });
  setInterval(() => { void loadCarts(); }, 30000);
});

async function loadHealth() {
  elements.health.textContent = "正在读取运行状态...";
  try {
    const payload = await apiRequest("/api/health", { method: "GET" });
    renderHealth(payload);
  } catch (error) {
    elements.health.innerHTML = `<div class="error message">读取运行状态失败：${escapeHtml(error.message)}</div>`;
  }
}


async function handleSearch() {
  clearFormError();
  const currentQuery = elements.query.value.trim();
  if (!currentQuery) {
    showFormError("请先输入动漫标题，再执行搜索。");
    return;
  }

  const queryChanged = currentQuery !== state.lastQuery;

  if (queryChanged) {
    setLoading(true, "正在搜索...");
    elements.results.innerHTML = "";
    state.lastQuery = currentQuery;
    try {
      const payload = buildSearchPayload();
      const response = await apiRequest("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.allCandidates = response.candidates || [];
      state.lastExpandedQueries = response.expanded_queries || [];
      state.lastExpandedQueryDetails = (response.diagnostics && response.diagnostics.expanded_query_details) || [];
      renderExpandedQueries(state.lastExpandedQueries, state.lastExpandedQueryDetails);
    } catch (error) {
      state.allCandidates = [];
      renderResults([]);
      renderDiagnostics(null, []);
      showFormError(`搜索失败：${error.message}`);
      return;
    } finally {
      setLoading(false);
    }
  }

  const filters = readFilters();
  const { filtered, dropReasons } = applyFilters(state.allCandidates, filters);
  const limited = filtered.slice(0, filters.limit);
  const diagnostics = buildClientDiagnostics(state.allCandidates.length, filtered.length, limited.length, dropReasons, filters);

  renderResults(limited);
  renderDiagnostics(diagnostics, limited);
}

function buildSearchPayload() {
  return {
    query: elements.query.value.trim(),
    limit: 100,
  };
}

function readFilters() {
  return {
    season: normalizeOptionalInt(elements.season.value),
    episode: normalizeOptionalText(elements.episode.value),
    resolution: normalizeOptionalText(elements.resolution.value),
    subtitle: normalizeOptionalText(elements.subtitle.value),
    group: normalizeOptionalText(elements.group.value),
    releaseMode: normalizeOptionalText(elements.releaseMode.value) || "any",
    limit: normalizeLimit(elements.limit.value),
  };
}

function applyFilters(candidates, filters) {
  const filtered = [];
  const dropReasons = {};

  for (const c of candidates) {
    const p = c.parsed || {};

    if (filters.season !== null) {
      const actualSeason = p.season != null && p.season !== "" ? Number(p.season) : 1;
      if (actualSeason !== filters.season) {
        dropReasons.season = (dropReasons.season || 0) + 1;
        continue;
      }
    }

    if (filters.episode && !episodeMatchesFilter(p.episode, filters.episode, p.is_batch, filters.releaseMode)) {
      dropReasons.episode = (dropReasons.episode || 0) + 1;
      continue;
    }

    if (filters.resolution && (p.resolution || "").toLowerCase() !== filters.resolution.toLowerCase()) {
      dropReasons.resolution = (dropReasons.resolution || 0) + 1;
      continue;
    }

    if (filters.group && normalizeText(p.group) !== normalizeText(filters.group)) {
      dropReasons.group = (dropReasons.group || 0) + 1;
      continue;
    }

    if (filters.subtitle && (p.subtitle_type || "").toLowerCase() !== filters.subtitle.toLowerCase()) {
      dropReasons.subtitle = (dropReasons.subtitle || 0) + 1;
      continue;
    }

    if (filters.releaseMode === "episode" && p.is_batch) {
      dropReasons.release_mode = (dropReasons.release_mode || 0) + 1;
      continue;
    }
    if (filters.releaseMode === "batch" && !p.is_batch) {
      dropReasons.release_mode = (dropReasons.release_mode || 0) + 1;
      continue;
    }

    filtered.push(c);
  }

  return { filtered, dropReasons };
}

function buildClientDiagnostics(totalCount, afterFilterCount, afterLimitCount, dropReasons, filters) {
  const beforeCount = totalCount;
  const afterCount = afterFilterCount;
  const noCandidates = afterLimitCount === 0;
  const filteredOut = beforeCount > 0 && afterCount === 0;

  const suggestions = [];
  if (dropReasons.subtitle && noCandidates) {
    suggestions.push("没有找到符合字幕条件的结果，可尝试改为“不限字幕”。");
  }
  if (dropReasons.group && noCandidates) {
    suggestions.push("可尝试去掉字幕组限制。");
  }
  if (dropReasons.resolution) {
    suggestions.push("可尝试放宽分辨率条件，例如改为 1080p、720p 或不限制。");
  }
  if (dropReasons.episode && filteredOut) {
    suggestions.push("可能是集数解析失败，可尝试清空集数后查看候选，或尝试合集 / 整季资源。");
  }
  if (filters.releaseMode !== "any" && noCandidates) {
    suggestions.push("可尝试改为不限资源类型。");
  }
  if (filters.releaseMode !== "batch" && noCandidates) {
    suggestions.push("也可尝试搜索合集 / 整季资源。");
  }
  if (filters.season !== null && noCandidates) {
    suggestions.push("可尝试去掉季度限制。");
  }

  const activeFilters = { release_mode: filters.releaseMode };
  if (filters.season !== null) activeFilters.season = filters.season;
  if (filters.episode) activeFilters.episode = filters.episode;
  if (filters.resolution) activeFilters.resolution = filters.resolution;
  if (filters.group) activeFilters.group = filters.group;
  if (filters.subtitle) activeFilters.subtitle = filters.subtitle;
  if (filters.limit) activeFilters.limit = filters.limit;

  return {
    original_query: state.lastQuery,
    expanded_queries: state.lastExpandedQueries,
    expanded_query_details: state.lastExpandedQueryDetails,
    resolution_status: "unresolved",
    needs_review: false,
    sources: ["RSS"],
    active_filters: activeFilters,
    candidate_count_before_filter: beforeCount,
    candidate_count_after_filter: afterCount,
    stage_counts: {},
    filter_drop_reasons: dropReasons,
    suggestions: suggestions.slice(0, 6),
    resolved_subject: null,
    candidate_subjects: [],
    rejected_subjects: [],
  };
}

function renderHealth(payload) {
  const qb = payload.qbittorrent || {};
  const sources = payload.sources || {};
  const qbLabel = qb.reachable ? "可连接" : "不可连接";
  const qbError = qb.error ? `（${escapeHtml(qb.error)}）` : "";

  elements.health.innerHTML = `
    <div><strong>qBittorrent：</strong>${qbLabel}${qbError}</div>
    <ul class="status-list">
      <li>RSS：${boolLabel(sources.rss)}</li>
    </ul>
  `;
}

function renderExpandedQueries(queries, details = []) {
  if ((!queries || queries.length === 0) && (!details || details.length === 0)) {
    elements.expandedQueries.textContent = "还没有解析过标题。";
    return;
  }

  if (details && details.length > 0) {
    elements.expandedQueries.innerHTML = `
      <ul class="simple-list">
        ${details
          .map(
            (item) => `
              <li>
                <strong>${escapeHtml(item.text)}</strong>
                <span class="muted">来源：${escapeHtml(item.source || "-")} / 语言：${escapeHtml(item.language || "unknown")} / 置信度：${formatConfidence(item.confidence)} / 搜索：${item.search_eligible ? "使用" : "仅展示"}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
    `;
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
    elements.results.innerHTML = `<div class="muted">没有可显示的候选资源。</div>`;
    return;
  }

  const toolbar = `
    <div class="add-to-cart-bar hidden" id="add-to-cart-bar">
      <button type="button" class="button button-primary" id="add-to-cart-button">加入下载队列</button>
      <span class="muted" id="cart-selection-count"></span>
    </div>
  `;

  elements.results.innerHTML = toolbar + candidates
    .map((candidate, index) => {
      const parsed = candidate.parsed || {};
      const detailId = `candidate-details-${index + 1}`;
      const itemId = `candidate-select-${index}`;
      return `
        <article class="candidate-card">
          <div class="candidate-header">
            <div class="candidate-title-row">
              <input type="checkbox" class="candidate-select" id="${itemId}" data-candidate-index="${index}">
              <label for="${itemId}" class="candidate-title">#${candidate.rank} ${escapeHtml(candidate.title || "-")}</label>
            </div>
            <div class="candidate-actions">
              <button type="button" class="button toggle-details" data-target="${detailId}" aria-expanded="false">展开详情</button>
              <button type="button" class="button download-button" data-url="${escapeAttr(candidate.magnet || candidate.url || "")}" data-title="${escapeAttr(candidate.title || "")}"${!candidate.magnet && !candidate.url ? " disabled" : ""}>单独下载</button>
            </div>
          </div>
          <div class="candidate-summary">
            <span><strong>评分：</strong>${formatValue(candidate.score)}</span>
            <span><strong>来源：</strong>${escapeHtml(candidate.source || "-")}</span>
            <span><strong>发布时间：</strong>${escapeHtml(formatDate(candidate.published_at))}</span>
            <span><strong>季度：</strong>${formatSeason(parsed.season)}</span>
            <span><strong>集数：</strong>${escapeHtml(formatValue(parsed.episode))}</span>
            <span><strong>分辨率：</strong>${escapeHtml(formatValue(parsed.resolution))}</span>
            <span><strong>字幕组：</strong>${escapeHtml(formatValue(parsed.group))}</span>
            <span><strong>字幕类型：</strong>${escapeHtml(formatSubtitleType(parsed.subtitle_type))}</span>
            <span><strong>合集：</strong>${boolOrUnknown(parsed.is_batch)}</span>
            <span><strong>RAW：</strong>${boolOrUnknown(parsed.is_raw)}</span>
            <span><strong>Magnet：</strong>${candidate.magnet ? "有" : "无"}</span>
          </div>
          <div id="${detailId}" class="candidate-details hidden">
            <div class="section-label">命中证据</div>
            <div class="parsed-grid">
              <div>matched_query: ${escapeHtml(formatValue(candidate.matched_query))}</div>
              <div>matched_query_source: ${escapeHtml(formatValue(candidate.matched_query_source))}</div>
              <div>matched_query_subject_id: ${escapeHtml(formatValue(candidate.matched_query_subject_id))}</div>
              <div>matched_query_confidence: ${escapeHtml(formatValue(candidate.matched_query_confidence))}</div>
              <div>title_evidence.type: ${escapeHtml(formatValue(candidate.title_evidence && candidate.title_evidence.type))}</div>
              <div>title_evidence.reason: ${escapeHtml(formatValue(candidate.title_evidence && candidate.title_evidence.reason))}</div>
            </div>
            <div class="section-label">评分原因</div>
            ${renderReasons(candidate.breakdown)}
            <div class="section-label">解析信息</div>
            <div class="parsed-grid">
              <div>episode: ${escapeHtml(formatValue(parsed.episode))}</div>
              <div>resolution: ${escapeHtml(formatValue(parsed.resolution))}</div>
              <div>group: ${escapeHtml(formatValue(parsed.group))}</div>
              <div>subtitle_type: ${escapeHtml(formatValue(parsed.subtitle_type))}</div>
              <div>is_batch: ${boolOrUnknown(parsed.is_batch)}</div>
              <div>is_raw: ${boolOrUnknown(parsed.is_raw)}</div>
            </div>
            <div class="section-label">其他信息</div>
            <div class="parsed-grid">
              <div>score: ${escapeHtml(formatValue(candidate.score))}</div>
              <div>source: ${escapeHtml(formatValue(candidate.source))}</div>
              <div>seeders: ${escapeHtml(formatValue(candidate.seeders))}</div>
              <div>published_at: ${escapeHtml(formatValue(candidate.published_at))}</div>
              <div>magnet: ${candidate.magnet ? escapeHtml(candidate.magnet) : "-"}</div>
              <div>url: ${candidate.url ? escapeHtml(candidate.url) : "-"}</div>
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  const bar = document.getElementById("add-to-cart-bar");
  if (bar) {
    const button = document.getElementById("add-to-cart-button");
    if (button) {
      button.addEventListener("click", () => void handleAddToCart());
    }
  }
  document.querySelectorAll(".candidate-select").forEach((checkbox) => {
    checkbox.addEventListener("change", updateAddToCartBar);
  });
}

function renderReasons(reasons) {
  if (!reasons || reasons.length === 0) {
    return `<div class="muted">没有可显示的评分原因。</div>`;
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
    elements.diagnostics.innerHTML = `<div class="muted">诊断信息会在搜索后显示。</div>`;
    return;
  }

  const beforeCount = diagnostics.candidate_count_before_filter;
  const afterCount = diagnostics.candidate_count_after_filter;
  const noCandidates = Array.isArray(candidates) && candidates.length === 0;
  const filteredOut = beforeCount !== null && beforeCount > 0 && (afterCount || 0) === 0;

  elements.diagnostics.innerHTML = `
    <div class="diagnostic-block">
      ${noCandidates ? `<div class="message warning">当前没有可直接使用的结果。</div>` : ""}
      ${filteredOut ? `<div class="message warning strong-warning">已找到资源，但全部被当前过滤条件排除了。</div>` : ""}
      <div class="count-grid">
        <div class="count-card">
          <div class="count-label">找到候选数</div>
          <div class="count-value">${escapeHtml(formatValue(beforeCount))}</div>
        </div>
        <div class="count-card">
          <div class="count-label">过滤后候选数</div>
          <div class="count-value">${escapeHtml(formatValue(afterCount))}</div>
        </div>
      </div>
      ${filteredOut ? renderRelaxHints() : ""}
      ${renderResolutionStatus(diagnostics)}
      ${renderResolvedSubject(diagnostics.resolved_subject)}
      ${renderRejectedSubjects("候选 / 歧义 subject", diagnostics.candidate_subjects)}
      ${renderKeyValueList("尝试过的标题", diagnostics.expanded_queries)}
      ${renderExpandedQueryDetailList("标题扩展详情", diagnostics.expanded_query_details)}
      ${renderRejectedSubjects("已拒绝的 subject", diagnostics.rejected_subjects)}
      ${renderKeyValueList("搜索来源", diagnostics.sources)}
      ${renderObjectList("当前过滤条件", diagnostics.active_filters)}
      ${renderKeyValueList("建议", diagnostics.suggestions)}
    </div>
  `;
}

function renderResolutionStatus(diagnostics) {
  const status = diagnostics && diagnostics.resolution_status ? diagnostics.resolution_status : "unresolved";
  const needsReview = Boolean(diagnostics && diagnostics.needs_review);
  const needsReviewLabel = needsReview ? "\u662f" : "\u5426";
  return `
    <div class="section-label">解析状态</div>
    <div class="parsed-grid">
      <div>resolution_status: ${escapeHtml(formatValue(status))}</div>
      <div>needs_review: ${needsReviewLabel}</div>
    </div>
  `;
}

function renderResolvedSubject(subject) {
  if (!subject) {
    return `<div class="section-label">已解析作品</div><div class="muted">当前没有选中的 subject。</div>`;
  }
  return `
    <div class="section-label">已解析作品</div>
    <div class="parsed-grid">
      <div>source: ${escapeHtml(formatValue(subject.source))}</div>
      <div>subject_id: ${escapeHtml(formatValue(subject.subject_id))}</div>
      <div>canonical: ${escapeHtml(formatValue(subject.canonical))}</div>
      <div>confidence: ${escapeHtml(formatConfidence(subject.confidence))}</div>
      <div>reason: ${escapeHtml(formatValue(subject.reason))}</div>
    </div>
  `;
}

function renderExpandedQueryDetailList(title, details) {
  const values = Array.isArray(details) && details.length > 0 ? details : [];
  if (values.length === 0) {
    return "";
  }
  return `
    <div class="section-label">${escapeHtml(title)}</div>
    <ul class="kv-list">
      ${values
        .map(
          (item) => `
            <li>
              ${escapeHtml(item.text)}
              <span class="muted">（${escapeHtml(item.source || "-")} / ${escapeHtml(item.language || "unknown")} / ${item.search_eligible ? "用于搜索" : "仅展示"} / 置信度 ${formatConfidence(item.confidence)}）</span>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderRejectedSubjects(title, values) {
  const items = Array.isArray(values) ? values : [];
  if (items.length === 0) {
    return "";
  }
  return `
    <div class="section-label">${escapeHtml(title)}</div>
    <ul class="kv-list">
      ${items
        .map(
          (item) => `
            <li>${escapeHtml(formatValue(item.canonical))} <span class="muted">（id=${escapeHtml(formatValue(item.subject_id))} / 置信度 ${formatConfidence(item.confidence)} / ${escapeHtml(formatValue(item.reason))}）</span></li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderRelaxHints() {
  return `
    <div class="relax-box">
      <div class="section-label">可优先尝试放宽这些条件</div>
      <ul class="kv-list">
        <li>清空集数</li>
        <li>改为不限字幕</li>
        <li>去掉字幕组限制</li>
        <li>改为不限资源类型</li>
        <li>尝试合集 / 整季资源</li>
      </ul>
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
      ${entries.map(([key, value]) => `<li>${escapeHtml(formatFilterKey(key))}：${escapeHtml(formatFilterValue(key, value))}</li>`).join("")}
    </ul>
  `;
}

function toggleCandidateDetails(button) {
  const targetId = button.getAttribute("data-target");
  const details = document.getElementById(targetId);
  if (!details) {
    return;
  }
  const isHidden = details.classList.toggle("hidden");
  const expanded = !isHidden;
  button.setAttribute("aria-expanded", expanded ? "true" : "false");
  button.textContent = expanded ? "收起详情" : "展开详情";
}

async function apiRequest(url, options, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    const payload = isJson ? await response.json() : await response.text();
    if (!response.ok) {
      if (isJson && payload && typeof payload.detail === "string") {
        throw new Error(payload.detail);
      }
      throw new Error(typeof payload === "string" ? payload : `HTTP ${response.status}`);
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("请求超时，请稍后重试。");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function setLoading(enabled, text = "正在加载...") {
  elements.loading.textContent = text;
  elements.loading.classList.toggle("hidden", !enabled);

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

function normalizeOptionalInt(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return null;
  const num = Number.parseInt(trimmed, 10);
  return Number.isNaN(num) ? null : num;
}

function normalizeText(value) {
  return (value || "").toLowerCase().replace(/[\s_-]+/g, " ").trim();
}

function episodeMatchesFilter(candidateEpisode, filterEpisode, isBatch, releaseMode) {
  if (isBatch && releaseMode === "batch") return true;
  if (!candidateEpisode) return false;
  if (candidateEpisode === filterEpisode) return true;
  const a = String(candidateEpisode).replace(/^0+/, "") || "0";
  const b = String(filterEpisode).replace(/^0+/, "") || "0";
  return a === b;
}

function normalizeLimit(value) {
  const parsed = Number.parseInt(String(value || "20"), 10);
  if (Number.isNaN(parsed)) {
    return 20;
  }
  return Math.max(1, Math.min(parsed, 100));
}

function boolLabel(value) {
  return value ? "已启用" : "未启用";
}


function boolOrUnknown(value) {
  if (value === true) {
    return "\u662f";
  }
  if (value === false) {
    return "\u5426";
  }
  return "未知";
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

function formatSeason(value) {
  if (value == null || value === "") {
    return "未知";
  }
  const numeric = Number(value);
  if (!Number.isNaN(numeric) && numeric > 0) {
    return `第${numeric}季`;
  }
  return String(value);
}

function formatSubtitleType(value) {
  const mapping = {
    embedded: "内嵌字幕",
    external: "外挂字幕",
    none: "RAW / 无字幕",
    unknown: "未知",
  };
  return mapping[value] || formatValue(value);
}

function formatFilterKey(key) {
  const mapping = {
    season: "季度",
    episode: "集数",
    resolution: "分辨率",
    group: "字幕组",
    subtitle: "字幕类型",
    raw_only: "只看 RAW",
    exclude_batch: "排除合集",
    min_seeders: "最少做种数",
    limit: "结果数量",
    release_mode: "资源类型",
  };
  return mapping[key] || key;
}

function formatFilterValue(key, value) {
  if (key === "subtitle") {
    return formatSubtitleType(value);
  }
  if (key === "release_mode") {
    return {
      any: "不限",
      episode: "单集",
      batch: "合集 / 整季",
    }[value] || String(value);
  }
  if (typeof value === "boolean") {
    return value ? "\u662f" : "\u5426";
  }
  return formatValue(value);
}

function formatConfidence(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return String(value);
  }
  return numeric.toFixed(2).replace(/0$/, "").replace(/\.$/, "");
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
  return String(value).replaceAll('"', "&quot;").replaceAll("&", "&amp;");
}

async function handleDownload(button) {
  const url = button.getAttribute("data-url");
  const title = button.getAttribute("data-title");
  if (!url) return;

  button.disabled = true;
  button.textContent = "添加中...";

  try {
    const response = await apiRequest("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, title }),
    });
    if (response.ok) {
      button.textContent = "已添加";
      button.classList.add("button-downloaded");
    } else {
      button.textContent = "失败";
      button.disabled = false;
    }
  } catch (error) {
    button.textContent = "失败";
    button.disabled = false;
    console.error("Download failed:", error);
  }
}

// ── cart functions ──────────────────────────────────────

function getSelectedCandidates() {
  const checked = document.querySelectorAll(".candidate-select:checked");
  return Array.from(checked).map((cb) => {
    const index = parseInt(cb.getAttribute("data-candidate-index"), 10);
    return state.allCandidates[index];
  }).filter(Boolean);
}

function updateAddToCartBar() {
  const bar = document.getElementById("add-to-cart-bar");
  const count = document.getElementById("cart-selection-count");
  if (!bar || !count) return;
  const selected = document.querySelectorAll(".candidate-select:checked").length;
  if (selected > 0) {
    bar.classList.remove("hidden");
    count.textContent = `已选 ${selected} 个候选`;
  } else {
    bar.classList.add("hidden");
  }
}

async function handleAddToCart() {
  const candidates = getSelectedCandidates();
  if (!candidates.length) return;

  const animeName = state.lastQuery || "未命名";
  const firstParsed = candidates[0].parsed || {};
  const episode = firstParsed.episode || "";

  try {
    const response = await apiRequest("/api/carts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ anime_name: animeName, episode, items: candidates }),
    });
    if (response.cart_id) {
      document.querySelectorAll(".candidate-select:checked").forEach((cb) => { cb.checked = false; });
      updateAddToCartBar();
      await loadCarts();
    }
  } catch (error) {
    console.error("Create cart failed:", error);
    alert(`创建下载队列失败：${error.message}`);
  }
}

async function loadCarts() {
  try {
    const response = await apiRequest("/api/carts", { method: "GET" });
    state.carts = response.carts || [];
    renderCarts();
  } catch (error) {
    console.error("Load carts failed:", error);
  }
}

function renderCarts() {
  const carts = state.carts;
  if (!carts || carts.length === 0) {
    elements.carts.innerHTML = `<div class="muted">暂无下载任务。搜索后勾选候选，点击"加入下载队列"。</div>`;
    return;
  }

  elements.carts.innerHTML = carts
    .map((cart) => {
      const statusLabels = { idle: "待启动", probing: "探测中", downloading: "下载中", done: "已完成", exhausted: "已放弃" };
      const statusLabel = statusLabels[cart.status] || cart.status;
      const itemCount = (cart.items || []).length;
      const recentEvents = (cart.events || []).slice(-3);
      const canStart = cart.status === "idle" || cart.status === "exhausted";

      return `
        <div class="cart-item">
          <div class="cart-header">
            <div>
              <strong>${escapeHtml(cart.anime_name)}</strong>
              ${cart.episode ? `<span class="cart-meta"> 第${escapeHtml(cart.episode)}集</span>` : ""}
              <span class="cart-status status-${cart.status}">${statusLabel}</span>
              ${cart.active_title ? `<span class="cart-meta"> | 当前：${escapeHtml(cart.active_title)}</span>` : ""}
            </div>
            <div>
              ${canStart ? `<button type="button" class="button button-primary cart-start-button" data-cart-id="${escapeAttr(cart.cart_id)}">开始下载</button>` : ""}
              <button type="button" class="button button-muted cart-delete-button" data-cart-id="${escapeAttr(cart.cart_id)}">删除</button>
            </div>
          </div>
          <div class="cart-meta">${itemCount} 个候选 | 回退 ${cart.fallback_count}/${cart.max_fallbacks} | 创建于 ${escapeHtml(formatDate(cart.created_at))}</div>
          ${recentEvents.length ? `
            <div class="cart-events">
              <ul>
                ${recentEvents.map((e) => `<li>${escapeHtml(formatDate(e.timestamp))}：${escapeHtml(e.message)}</li>`).join("")}
              </ul>
            </div>
          ` : ""}
        </div>
      `;
    })
    .join("");
}

async function handleStartCart(button) {
  const cartId = button.getAttribute("data-cart-id");
  if (!cartId) return;
  button.disabled = true;
  button.textContent = "启动中...";
  try {
    await apiRequest(`/api/carts/${cartId}/start`, { method: "POST" });
    await loadCarts();
  } catch (error) {
    console.error("Start cart failed:", error);
    button.disabled = false;
    button.textContent = "开始下载";
  }
}

async function handleDeleteCart(button) {
  const cartId = button.getAttribute("data-cart-id");
  if (!cartId) return;
  const cart = (state.carts || []).find((c) => c.cart_id === cartId);
  const active = cart && (cart.status === "downloading" || cart.status === "probing");
  if (!confirm(`确定删除此下载队列？${active ? "qB 中的对应任务也会被删除。" : ""}`)) return;
  try {
    await apiRequest(`/api/carts/${cartId}`, { method: "DELETE" });
    await loadCarts();
  } catch (error) {
    console.error("Delete cart failed:", error);
  }
}
