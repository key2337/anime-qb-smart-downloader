const state = {
  lastExpandedQueries: [],
  lastExpandedQueryDetails: [],
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
  batchOnly: document.getElementById("batch-only"),
  releaseMode: document.getElementById("release-mode"),
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
  elements.results.addEventListener("click", (event) => {
    const button = event.target.closest(".toggle-details");
    if (!button) {
      return;
    }
    toggleCandidateDetails(button);
  });
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

async function handleResolveTitle() {
  clearFormError();
  const query = elements.query.value.trim();
  if (!query) {
    showFormError("请先输入动漫标题，再解析标题。");
    return;
  }

  setLoading(true, "正在解析标题...");
  try {
    const payload = await apiRequest("/api/resolve-title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    state.lastExpandedQueries = payload.expanded_queries || [];
    state.lastExpandedQueryDetails = payload.expanded_query_details || [];
    renderExpandedQueries(state.lastExpandedQueries, state.lastExpandedQueryDetails);
    renderDiagnostics({
      original_query: query,
      expanded_queries: payload.expanded_queries || [],
      expanded_query_details: payload.expanded_query_details || [],
      resolution_status: payload.resolution_status || "unresolved",
      needs_review: Boolean(payload.needs_review),
      sources: payload.sources || [],
      active_filters: {},
      candidate_count_before_filter: null,
      candidate_count_after_filter: null,
      suggestions: ["可先确认这里的标题扩展\u662f\u5426符合预期。"],
      resolved_subject: payload.resolved_subject || null,
      candidate_subjects: payload.candidate_subjects || [],
      rejected_subjects: payload.rejected_subjects || [],
    });
  } catch (error) {
    showFormError(`解析标题失败：${error.message}`);
  } finally {
    setLoading(false);
  }
}

async function handleSearch() {
  clearFormError();
  const payload = buildSearchPayload();
  if (!payload.query) {
    showFormError("请先输入动漫标题，再执行搜索。");
    return;
  }

  setLoading(true, "正在搜索...");
  elements.results.innerHTML = "";
  try {
    const response = await apiRequest("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.lastExpandedQueries = response.expanded_queries || [];
    state.lastExpandedQueryDetails = (response.diagnostics && response.diagnostics.expanded_query_details) || [];
    renderExpandedQueries(state.lastExpandedQueries, state.lastExpandedQueryDetails);
    renderResults(response.candidates || []);
    renderDiagnostics(response.diagnostics || null, response.candidates || []);
  } catch (error) {
    renderResults([]);
    renderDiagnostics(null, []);
    showFormError(`搜索失败：${error.message}`);
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
    batch_only: elements.batchOnly.checked,
    release_mode: elements.batchOnly.checked ? "batch" : (normalizeOptionalText(elements.releaseMode.value) || "any"),
    limit: normalizeLimit(elements.limit.value),
  };
}

function renderHealth(payload) {
  const qb = payload.qbittorrent || {};
  const sources = payload.sources || {};
  const metadataSources = payload.metadata_sources || {};
  const anilist = payload.anilist || metadataSources.anilist || {};
  const bangumi = payload.bangumi || metadataSources.bangumi || {};
  const qbLabel = qb.reachable ? "可连接" : "不可连接";
  const qbError = qb.error ? `（${escapeHtml(qb.error)}）` : "";

  elements.health.innerHTML = `
    <div><strong>qBittorrent：</strong>${qbLabel}${qbError}</div>
    <ul class="status-list">
      <li>RSS：${boolLabel(sources.rss)}</li>
      <li>Nyaa：${boolLabel(sources.nyaa)}</li>
      <li>Torznab：${boolLabel(sources.torznab)}</li>
      <li>Bangumi：${metadataStatusLabel(bangumi)}</li>
      <li>AniList：${metadataStatusLabel(anilist)}</li>
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

  elements.results.innerHTML = candidates
    .map((candidate, index) => {
      const parsed = candidate.parsed || {};
      const detailId = `candidate-details-${index + 1}`;
      return `
        <article class="candidate-card">
          <div class="candidate-header">
            <div>
              <div class="candidate-title">#${candidate.rank} ${escapeHtml(candidate.title || "-")}</div>
              <div class="candidate-summary">
                <span><strong>评分：</strong>${formatValue(candidate.score)}</span>
                <span><strong>来源：</strong>${escapeHtml(candidate.source || "-")}</span>
                <span><strong>做种数：</strong>${formatValue(candidate.seeders)}</span>
                <span><strong>发布时间：</strong>${escapeHtml(formatDate(candidate.published_at))}</span>
                <span><strong>集数：</strong>${escapeHtml(formatValue(parsed.episode))}</span>
                <span><strong>分辨率：</strong>${escapeHtml(formatValue(parsed.resolution))}</span>
                <span><strong>字幕组：</strong>${escapeHtml(formatValue(parsed.group))}</span>
                <span><strong>字幕类型：</strong>${escapeHtml(formatSubtitleType(parsed.subtitle_type))}</span>
                <span><strong>合集：</strong>${boolOrUnknown(parsed.is_batch)}</span>
                <span><strong>RAW：</strong>${boolOrUnknown(parsed.is_raw)}</span>
                <span><strong>Magnet：</strong>${candidate.magnet ? "有" : "无"}</span>
                <span><strong>URL：</strong>${candidate.url ? "有" : "无"}</span>
              </div>
            </div>
            <button type="button" class="button toggle-details" data-target="${detailId}" aria-expanded="false">展开详情</button>
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
  return value ? "已启用" : "未启用";
}

function metadataStatusLabel(value) {
  if (!value || typeof value.enabled !== "boolean") {
    return "未知";
  }
  return value.enabled ? "启用" : "未启用";
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
