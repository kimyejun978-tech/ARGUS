(function () {
  "use strict";

  var els = {
    mode: document.getElementById("mode"),
    score: document.getElementById("score"),
    aiBest: document.getElementById("ai-best"),
    siteBest: document.getElementById("site-best"),
    version: document.getElementById("version"),
    episodes: document.getElementById("episodes"),
    states: document.getElementById("states"),
    canvas: document.getElementById("canvas"),
    scoreReadable: document.getElementById("score-readable"),
    epsilon: document.getElementById("epsilon"),
    epsilonValue: document.getElementById("epsilon-value"),
    message: document.getElementById("message"),
    learn: document.getElementById("learn"),
    play: document.getElementById("play"),
    stop: document.getElementById("stop"),
    exportBtn: document.getElementById("export"),
    updateBtn: document.getElementById("update"),
    importInput: document.getElementById("import"),
  };

  function setMessage(text) {
    els.message.textContent = text || "";
  }

  function activeTab(callback) {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      var tab = tabs && tabs[0];
      if (!tab || !tab.id) {
        setMessage("활성 탭을 찾지 못했습니다.");
        return;
      }
      callback(tab.id);
    });
  }

  function send(type, payload, callback) {
    activeTab(function (tabId) {
      chrome.tabs.sendMessage(tabId, Object.assign({ type: type }, payload || {}), function (response) {
        if (chrome.runtime.lastError) {
          setMessage("classic 페이지에서 확장을 열어 주세요.");
          return;
        }
        response = response || {};
        if (response.error) {
          setMessage(response.error);
          return;
        }
        if (callback) callback(response);
      });
    });
  }

  function render(status) {
    status = status || {};
    els.mode.textContent = modeLabel(status.mode);
    els.score.textContent = status.scoreLabel || String(status.score || 0);
    els.aiBest.textContent = String(status.aiBestScore || 0);
    els.siteBest.textContent = String(status.siteBestScore || 0);
    els.version.textContent = "v" + String(status.version || chrome.runtime.getManifest().version);
    els.episodes.textContent = String(status.episodes || 0);
    els.states.textContent = String(status.states || 0);
    els.canvas.textContent = status.canvasReady ? "감지" : "미감지";
    els.scoreReadable.textContent = status.scoreReadable ? "정상" : "대기/깜빡임";
    if (typeof status.epsilon === "number") {
      els.epsilon.value = String(status.epsilon);
      els.epsilonValue.textContent = status.epsilon.toFixed(2);
    }
  }

  function modeLabel(mode) {
    if (mode === "learning") return "학습 중";
    if (mode === "play") return "실행 중";
    return "대기";
  }

  function refresh() {
    send("DINO_AI_STATUS", null, render);
  }

  els.epsilon.addEventListener("input", function () {
    var epsilon = Number(els.epsilon.value);
    els.epsilonValue.textContent = epsilon.toFixed(2);
    send("DINO_AI_SET_EPSILON", { epsilon: epsilon }, render);
  });

  els.learn.addEventListener("click", function () {
    send("DINO_AI_START", { learning: true, epsilon: Number(els.epsilon.value) }, function (status) {
      setMessage("학습을 시작했습니다.");
      render(status);
    });
  });

  els.play.addEventListener("click", function () {
    send("DINO_AI_START", { learning: false, epsilon: 0 }, function (status) {
      setMessage("정책 실행만 시작했습니다.");
      render(status);
    });
  });

  els.stop.addEventListener("click", function () {
    send("DINO_AI_STOP", null, function (status) {
      setMessage("중지했습니다.");
      render(status);
    });
  });

  els.updateBtn.addEventListener("click", function () {
    setMessage("업데이트를 확인하는 중...");
    send("DINO_AI_CHECK_UPDATE", null, function (info) {
      if (info.updateAvailable) {
        setMessage("새 버전 v" + info.latestVersion + "이 있습니다. dino-site-ai\\update.cmd 실행 후 chrome://extensions에서 확장을 다시 로드하세요.");
      } else {
        setMessage("현재 최신 버전입니다. v" + info.currentVersion);
      }
    });
  });

  els.exportBtn.addEventListener("click", function () {
    send("DINO_AI_EXPORT", null, function (response) {
      if (!response.policy) {
        setMessage("내보낼 정책이 없습니다.");
        return;
      }
      var blob = new Blob([JSON.stringify(response.policy, null, 2)], { type: "application/json" });
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url;
      link.download = "dino-policy.json";
      link.click();
      URL.revokeObjectURL(url);
      setMessage("정책을 내보냈습니다.");
    });
  });

  els.importInput.addEventListener("change", function () {
    var file = els.importInput.files && els.importInput.files[0];
    if (!file) return;
    file.text().then(function (text) {
      var policy = JSON.parse(text);
      send("DINO_AI_IMPORT", { policy: policy }, function (status) {
        setMessage("정책을 가져왔습니다.");
        render(status);
      });
    }).catch(function () {
      setMessage("정책 JSON을 읽지 못했습니다.");
    });
  });

  refresh();
  window.setInterval(refresh, 1000);
})();
