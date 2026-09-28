const $ = (id) => document.getElementById(id);
let apiReady = false;
let lastState = null;
let activeDetail = null;
let lastFocusedElement = null;
let pollInFlight = false;
let pollTimer = null;

const els = {
  target: $("targetInput"), start: $("startButton"), cancel: $("cancelButton"),
  file: $("fileButton"), form: $("formMessage"), metricStatus: $("metricStatus"),
  attempted: $("attemptedCount"), completed: $("completedCount"),
  findings: $("findingCount"), elapsed: $("elapsedText"), currentUrl: $("currentUrl"),
  autotune: $("autotuneText"), discovered: $("discoveredText"),
  auxMetric: $("auxCountText"), liveTitle: $("liveTitle"), progress: $("progressTrack"),
  warning: $("warningBox"), folder: $("openFolderButton"),
  officialCount: $("officialTabCount"), auxCount: $("auxTabCount"),
  confirmed: $("confirmedCount"), suspicious: $("suspiciousCount"), benign: $("benignCount"),
  officialBody: $("officialBody"), auxBody: $("auxBody"),
  officialEmpty: $("officialEmpty"), auxEmpty: $("auxEmpty"), logs: $("logOutput"),
  modal: $("detailModal"), detailTitle: $("detailTitle"), detailList: $("detailList")
};

function fmtNumber(value) {
  return Number(value || 0).toLocaleString("ko-KR");
}
function fmtElapsed(sec) {
  sec = Number(sec || 0);
  if (sec < 60) return sec.toFixed(1) + "초";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m + "분 " + String(s).padStart(2, "0") + "초";
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]));
}
function setFormMessage(message="") {
  els.form.textContent = message;
}
function setBusy(running) {
  els.start.disabled = running || !apiReady;
  els.file.disabled = running || !apiReady;
  els.cancel.disabled = !running || !apiReady;
  els.target.disabled = running;
}
function renderRows(state) {
  const results = state.results || [];
  els.officialBody.innerHTML = results.map((item, idx) => `
    <tr data-kind="official" data-index="${idx}" tabindex="0" role="button" aria-label="${escapeHtml(item.technique || "탐지")} 상세 보기">
      <td class="tech-${escapeHtml(item.technique || "")}">${escapeHtml(item.technique || "-")}</td>
      <td title="${escapeHtml(item.evidence_text || "")}">${escapeHtml(item.evidence_text || "-")}</td>
      <td title="${escapeHtml(item.url || "")}">${escapeHtml(item.url || "-")}</td>
      <td title="${escapeHtml(item.location || "")}">${escapeHtml(item.location || "-")}</td>
    </tr>`).join("");
  els.officialEmpty.classList.toggle("hidden", results.length > 0);

  const aux = state.aux_results || [];
  els.auxBody.innerHTML = aux.map((item, idx) => {
    const isDomainRisk = item.type === "DOMAIN_IMPERSONATION_RISK";
    const typeLabel = isDomainRisk ? "URL 사칭 위험" : (item.type === "AUTO_DOWNLOAD_ATTEMPT" ? "자동 다운로드" : (item.type || "보조 진단"));
    const target = isDomainRisk ? (item.display_hostname || item.hostname) : (item.download_url || item.page_url);
    const detail = isDomainRisk ? item.reason : (item.suggested_filename || item.page_url);
    return `
      <tr data-kind="aux" data-index="${idx}" tabindex="0" role="button" aria-label="${escapeHtml(typeLabel)} 상세 보기">
        <td>${escapeHtml(typeLabel)}</td>
        <td title="${escapeHtml(target || "")}">${escapeHtml(target || "-")}</td>
        <td title="${escapeHtml(detail || "")}">${escapeHtml(detail || "-")}</td>
        <td class="${item.risk === "SUSPICIOUS" ? "risk-suspicious" : "risk-info"}">${escapeHtml(item.risk || "INFO")}</td>
      </tr>`;
  }).join("");
  els.auxEmpty.classList.toggle("hidden", aux.length > 0);
}
function renderState(state) {
  lastState = state;
  const running = state.status === "running";
  els.metricStatus.textContent = state.status_text || "대기";
  els.attempted.textContent = fmtNumber(state.attempted);
  els.completed.textContent = fmtNumber(state.completed);
  els.findings.textContent = fmtNumber(state.findings);
  els.elapsed.textContent = fmtElapsed(state.elapsed_sec);
  els.currentUrl.textContent = state.current_url || "점검할 주소를 입력해 주세요.";
  els.autotune.textContent = state.autotune || "Auto-Tune 대기";
  els.discovered.textContent = state.discovered ? "발견 URL " + fmtNumber(state.discovered) + "개" : "발견 URL 집계 대기";
  els.auxMetric.textContent = "보조 위험 " + fmtNumber(state.aux_downloads) + "건";
  els.liveTitle.textContent = running ? "자동 탐색 및 정밀 분석 진행 중" : (state.status === "complete" ? "점검 완료" : "점검 대기");
  els.progress.classList.toggle("running", running);
  els.progress.setAttribute("aria-busy", String(running));
  els.confirmed.textContent = fmtNumber(state.confirmed);
  els.suspicious.textContent = fmtNumber(state.suspicious);
  els.benign.textContent = fmtNumber(state.benign);
  els.officialCount.textContent = fmtNumber(state.findings);
  els.auxCount.textContent = fmtNumber(state.aux_downloads);
  els.warning.textContent = state.warning || state.error || "";
  els.warning.classList.toggle("hidden", !(state.warning || state.error));
  els.folder.disabled = state.status !== "complete";
  setBusy(running);
  renderRows(state);
  const logs = state.logs || [];
  els.logs.textContent = logs.length ? logs.join("\n") : "ARGUS 시스템 로그 대기 중";
  els.logs.scrollTop = els.logs.scrollHeight;
}
async function poll() {
  if (!apiReady || pollInFlight) return;
  pollInFlight = true;
  try {
    const state = await window.pywebview.api.get_state();
    renderState(state);
    if (els.form.textContent.startsWith("상태를 불러오지 못했습니다:")) {
      setFormMessage("");
    }
  } catch (err) {
    setFormMessage("상태를 불러오지 못했습니다: " + err);
  } finally {
    pollInFlight = false;
  }
}
async function callApi(method, ...args) {
  if (!apiReady) return null;
  try {
    return await window.pywebview.api[method](...args);
  } catch (err) {
    setFormMessage("데스크톱 API 호출에 실패했습니다: " + err);
    return null;
  }
}
window.addEventListener("pywebviewready", () => {
  apiReady = true;
  setBusy(false);
  poll();
  pollTimer = window.setInterval(poll, 500);
});
window.addEventListener("beforeunload", () => {
  if (pollTimer !== null) window.clearInterval(pollTimer);
});
els.start.addEventListener("click", async () => {
  setFormMessage("");
  const result = await callApi("start_scan", els.target.value);
  if (result && !result.ok) setFormMessage(result.message || "점검을 시작하지 못했습니다.");
  await poll();
});
els.cancel.addEventListener("click", async () => {
  const result = await callApi("cancel_scan");
  if (result && !result.ok) setFormMessage(result.message || "점검을 중지하지 못했습니다.");
  await poll();
});
els.file.addEventListener("click", async () => {
  const result = await callApi("choose_file");
  if (!result) return;
  if (result.ok && result.path) els.target.value = result.path;
  else if (!result.cancelled && result.message) setFormMessage(result.message);
});
els.folder.addEventListener("click", async () => {
  const result = await callApi("open_result_folder");
  if (result && !result.ok) setFormMessage(result.message || "결과 폴더를 열지 못했습니다.");
});
els.target.addEventListener("keydown", e => {
  if (e.key === "Enter" && !els.start.disabled) els.start.click();
});
const tabs = Array.from(document.querySelectorAll(".tab"));
function activateTab(tab, focus=false) {
  tabs.forEach(item => {
    const selected = item === tab;
    item.classList.toggle("active", selected);
    item.setAttribute("aria-selected", String(selected));
    item.tabIndex = selected ? 0 : -1;
    const panel = $(item.dataset.tab + "Panel");
    panel.classList.toggle("active", selected);
    panel.hidden = !selected;
  });
  if (focus) tab.focus();
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => activateTab(tab));
  tab.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let nextIndex = index;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    activateTab(tabs[nextIndex], true);
  });
});
function showDetail(kind, index) {
  if (!lastState) return;
  const item = kind === "official" ? (lastState.results || [])[index] : (lastState.aux_results || [])[index];
  if (!item) return;
  activeDetail = item;
  lastFocusedElement = document.activeElement;
  els.detailTitle.textContent = kind === "official" ? (item.technique || "탐지 결과") : (item.type || "보조 위험 진단");
  const entries = kind === "official" ? [
    ["기법", item.technique], ["탐지 문구", item.evidence_text], ["페이지", item.url], ["위치", item.location]
  ] : item.type === "DOMAIN_IMPERSONATION_RISK" ? [
    ["판정", item.risk], ["진단 유형", "URL 사칭 위험"], ["입력 주소", item.page_url],
    ["표시 도메인", item.display_hostname || item.hostname], ["유사 브랜드", item.brand],
    ["탐지 신호", item.signal], ["판단 근거", item.reason],
    ["공식 도메인", (item.official_domains || []).join(", ")], ["확신도", item.confidence]
  ] : [
    ["판정", item.risk], ["발생 페이지", item.page_url], ["다운로드 요청", item.download_url], ["파일명", item.suggested_filename], ["차단 여부", item.blocked ? "차단됨" : "미차단"]
  ];
  els.detailList.innerHTML = entries.map(([k,v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v || "-")}</dd>`).join("");
  els.modal.classList.remove("hidden");
  $("closeModal").focus();
}
[els.officialBody, els.auxBody].forEach(body => {
  body.addEventListener("click", e => {
    const row = e.target.closest("tr");
    if (row) showDetail(row.dataset.kind, Number(row.dataset.index));
  });
  body.addEventListener("keydown", e => {
    if (!['Enter', ' '].includes(e.key)) return;
    const row = e.target.closest("tr");
    if (!row) return;
    e.preventDefault();
    showDetail(row.dataset.kind, Number(row.dataset.index));
  });
});
function closeDetail() {
  els.modal.classList.add("hidden");
  activeDetail = null;
  if (lastFocusedElement) lastFocusedElement.focus();
  lastFocusedElement = null;
}
$("closeModal").addEventListener("click", closeDetail);
els.modal.addEventListener("click", e => { if (e.target === els.modal) closeDetail(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !els.modal.classList.contains("hidden")) closeDetail();
});
$("copyDetailButton").addEventListener("click", async () => {
  if (!activeDetail) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(activeDetail, null, 2));
    setFormMessage("상세 정보를 클립보드에 복사했습니다.");
  } catch (err) {
    setFormMessage("상세 정보를 복사하지 못했습니다: " + err);
  }
});
setBusy(false);
