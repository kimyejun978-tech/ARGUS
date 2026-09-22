const $ = (id) => document.getElementById(id);
let apiReady = false;
let lastState = null;
let activeDetail = null;

const els = {
  target: $("targetInput"), start: $("startButton"), cancel: $("cancelButton"),
  file: $("fileButton"), form: $("formMessage"), badge: $("statusBadge"),
  statusText: $("statusText"), metricStatus: $("metricStatus"),
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
function statusClass(status) {
  return ["running","complete","error","cancelled"].includes(status) ? status : "idle";
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
    <tr data-kind="official" data-index="${idx}">
      <td class="tech-${escapeHtml(item.technique || "")}">${escapeHtml(item.technique || "-")}</td>
      <td title="${escapeHtml(item.evidence_text || "")}">${escapeHtml(item.evidence_text || "-")}</td>
      <td title="${escapeHtml(item.url || "")}">${escapeHtml(item.url || "-")}</td>
      <td title="${escapeHtml(item.location || "")}">${escapeHtml(item.location || "-")}</td>
    </tr>`).join("");
  els.officialEmpty.classList.toggle("hidden", results.length > 0);

  const aux = state.aux_results || [];
  els.auxBody.innerHTML = aux.map((item, idx) => `
    <tr data-kind="aux" data-index="${idx}">
      <td class="${item.risk === "SUSPICIOUS" ? "risk-suspicious" : "risk-info"}">${escapeHtml(item.risk || "INFO")}</td>
      <td title="${escapeHtml(item.page_url || "")}">${escapeHtml(item.page_url || "-")}</td>
      <td title="${escapeHtml(item.download_url || "")}">${escapeHtml(item.download_url || "-")}</td>
      <td title="${escapeHtml(item.suggested_filename || "")}">${escapeHtml(item.suggested_filename || "-")}</td>
    </tr>`).join("");
  els.auxEmpty.classList.toggle("hidden", aux.length > 0);
}
function renderState(state) {
  lastState = state;
  const running = state.status === "running";
  els.badge.className = "status-badge " + statusClass(state.status);
  els.statusText.textContent = state.status_text || "대기";
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
  if (!apiReady) return;
  try {
    const state = await window.pywebview.api.get_state();
    renderState(state);
  } catch (err) {
    setFormMessage("상태를 불러오지 못했습니다: " + err);
  }
}
window.addEventListener("pywebviewready", () => {
  apiReady = true;
  setBusy(false);
  poll();
  setInterval(poll, 350);
});
els.start.addEventListener("click", async () => {
  setFormMessage("");
  const result = await window.pywebview.api.start_scan(els.target.value);
  if (!result.ok) setFormMessage(result.message || "점검을 시작하지 못했습니다.");
  await poll();
});
els.cancel.addEventListener("click", async () => {
  await window.pywebview.api.cancel_scan();
  await poll();
});
els.file.addEventListener("click", async () => {
  const result = await window.pywebview.api.choose_file();
  if (result.ok && result.path) els.target.value = result.path;
  else if (!result.cancelled && result.message) setFormMessage(result.message);
});
els.folder.addEventListener("click", async () => {
  const result = await window.pywebview.api.open_result_folder();
  if (!result.ok) setFormMessage(result.message || "결과 폴더를 열지 못했습니다.");
});
els.target.addEventListener("keydown", e => {
  if (e.key === "Enter" && !els.start.disabled) els.start.click();
});
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(x => x.classList.remove("active"));
    tab.classList.add("active");
    $(tab.dataset.tab + "Panel").classList.add("active");
  });
});
function showDetail(kind, index) {
  if (!lastState) return;
  const item = kind === "official" ? (lastState.results || [])[index] : (lastState.aux_results || [])[index];
  if (!item) return;
  activeDetail = item;
  els.detailTitle.textContent = kind === "official" ? (item.technique || "탐지 결과") : (item.type || "보조 위험 진단");
  const entries = kind === "official" ? [
    ["기법", item.technique], ["탐지 문구", item.evidence_text], ["페이지", item.url], ["위치", item.location]
  ] : [
    ["판정", item.risk], ["발생 페이지", item.page_url], ["다운로드 요청", item.download_url], ["파일명", item.suggested_filename], ["차단 여부", item.blocked ? "차단됨" : "미차단"]
  ];
  els.detailList.innerHTML = entries.map(([k,v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v || "-")}</dd>`).join("");
  els.modal.classList.remove("hidden");
}
[els.officialBody, els.auxBody].forEach(body => {
  body.addEventListener("click", e => {
    const row = e.target.closest("tr");
    if (row) showDetail(row.dataset.kind, Number(row.dataset.index));
  });
});
$("closeModal").addEventListener("click", () => els.modal.classList.add("hidden"));
els.modal.addEventListener("click", e => { if (e.target === els.modal) els.modal.classList.add("hidden"); });
$("copyDetailButton").addEventListener("click", async () => {
  if (!activeDetail) return;
  await navigator.clipboard.writeText(JSON.stringify(activeDetail, null, 2));
});
setBusy(false);
