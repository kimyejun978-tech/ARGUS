(function () {
  "use strict";

  var STORAGE_KEY = "dinoAi.actualSitePolicy.v2";
  var SETTINGS_KEY = "dinoAi.actualSiteSettings.v1";
  var TICK_MS = 1000 / 60;
  var ACTION_HOLD_FRAMES = 4;
  var SAVE_EVERY_MS = 2500;
  var CANVAS_WIDTH = 600;
  var CANVAS_HEIGHT = 150;
  var DINO_LEFT = 50;
  var DINO_RIGHT = 92;
  var DINO_X = 50;
  var GROUND_Y = 140;
  var HIT_SCAN_LEFT = 95;
  var ACTIONS = ["run", "jump", "duck"];
  var TARGET_ORIGIN = "https://chrome-dino.org";
  var TARGET_PATH = "/ko/classic/";
  var GAME_OVER_TEXT_BOX = { x: 205, y: 42, width: 191, height: 11 };
  var GAME_OVER_MIN_INK = 320;

  function isDarkPixel(data, width, x, y) {
    if (x < 0 || y < 0 || x >= width) return false;
    var index = (y * width + x) * 4;
    var alpha = data[index + 3];
    if (alpha <= 40) return false;
    return data[index] < 140 && data[index + 1] < 140 && data[index + 2] < 140;
  }

  function findPixelBounds(image, x1, x2, y1, y2, ignoreHorizon) {
    var data = image.data;
    var width = image.width || CANVAS_WIDTH;
    var height = image.height || CANVAS_HEIGHT;
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    var count = 0;
    for (var y = y1; y <= y2 && y < height; y += 1) {
      if (ignoreHorizon && y >= 124 && y <= 132) continue;
      for (var x = x1; x <= x2 && x < width; x += 1) {
        if (!isDarkPixel(data, width, x, y)) continue;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
        count += 1;
      }
    }
    if (!count) return null;
    return {
      x: minX,
      y: minY,
      right: maxX,
      bottom: maxY,
      width: maxX - minX + 1,
      height: maxY - minY + 1,
      count: count,
    };
  }

  function darkColumnCount(image, x) {
    var data = image.data;
    var width = image.width || CANVAS_WIDTH;
    var height = image.height || CANVAS_HEIGHT;
    var count = 0;
    for (var y = 45; y <= 139 && y < height; y += 1) {
      if (y >= 124 && y <= 132) continue;
      if (isDarkPixel(data, width, x, y)) count += 1;
    }
    return count;
  }

  function findObstacleInImage(image) {
    var groups = [];
    var group = null;
    var gap = 0;
    var width = image.width || CANVAS_WIDTH;

    for (var x = HIT_SCAN_LEFT; x < width - 4; x += 1) {
      var count = darkColumnCount(image, x);
      if (count >= 4) {
        if (!group) {
          group = { x1: x, x2: x, columns: 1 };
        } else {
          group.x2 = x;
          group.columns += 1;
        }
        gap = 0;
      } else if (group) {
        gap += 1;
        if (gap > 3) {
          groups.push(group);
          group = null;
          gap = 0;
        }
      }
    }
    if (group) groups.push(group);

    for (var i = 0; i < groups.length; i += 1) {
      var g = groups[i];
      if (g.x2 < DINO_X) continue;
      var bounds = findPixelBounds(image, g.x1, g.x2, 45, 139, true);
      if (!bounds || bounds.width < 4 || bounds.height < 8 || bounds.count < 18) continue;
      if (bounds.x < 120 && bounds.y < 70 && bounds.height < 20) continue;
      var profile = normalizeObstacleProfile(bounds);
      return {
        x: bounds.x,
        y: profile.top,
        width: bounds.width,
        height: profile.bottom - profile.top,
        bottom: profile.bottom,
        type: profile.type,
        pixelTop: bounds.y,
        pixelBottom: bounds.bottom,
      };
    }
    return null;
  }

  function normalizeObstacleProfile(bounds) {
    if (bounds.width >= 30 && bounds.height <= 35 && bounds.y < 115) {
      if (bounds.y <= 60) return { type: "birdHigh", top: 50, bottom: 90 };
      if (bounds.y <= 90) return { type: "birdMid", top: 75, bottom: 115 };
      return { type: "birdLow", top: 100, bottom: 140 };
    }
    if (bounds.y < 100 || bounds.height >= 42) {
      return { type: "cactusLarge", top: 90, bottom: 140 };
    }
    return { type: "cactusSmall", top: 105, bottom: 140 };
  }

  function readPixelObservation(image, tracker, encoder) {
    tracker = tracker || {};
    var speed = Math.min(13, 6 + (tracker.frames || 0) * 0.001);
    var dino = image ? findPixelBounds(image, DINO_LEFT, DINO_RIGHT, 45, 145, true) : null;
    var obstacle = image ? findObstacleInImage(image) : null;
    var score = readCanvasScore(image);
    var dinoY = dino ? dino.y : tracker.lastDinoY || 93;
    var dinoHeight = dino ? dino.height : 47;
    var grounded = dino ? dino.bottom >= 136 || dino.y >= 104 : true;
    var ducking = !!(dino && dino.y >= 108 && dino.height <= 34);
    var obs = {
      distance: obstacle ? Math.max(0, obstacle.x - (DINO_X + (ducking ? 59 : 44))) : 999,
      obstacleWidth: obstacle ? obstacle.width : 0,
      obstacleTop: obstacle ? obstacle.y : GROUND_Y,
      obstacleBottom: obstacle ? obstacle.bottom : GROUND_Y,
      obstacleType: obstacle ? obstacle.type : "none",
      speed: speed,
      score: score,
      dinoY: dinoY,
      dinoHeight: dinoHeight,
      vy: dinoY - (tracker.lastDinoY || dinoY),
      grounded: grounded,
      ducking: ducking,
      groundY: GROUND_Y,
    };
    if (encoder) obs.state = encoder(obs);
    return obs;
  }

  function scoreDigitBoxes() {
    var boxes = [];
    for (var i = 0; i < 5; i += 1) {
      boxes.push({ x: 534 + i * 11, y: 10, width: 10, height: 13 });
    }
    return boxes;
  }

  function countDarkPixels(image, x, y, width, height) {
    if (!image || !image.data) return 0;
    var total = 0;
    var maxX = Math.min(image.width || CANVAS_WIDTH, x + width);
    var maxY = Math.min(image.height || CANVAS_HEIGHT, y + height);
    for (var yy = Math.max(0, y); yy < maxY; yy += 1) {
      for (var xx = Math.max(0, x); xx < maxX; xx += 1) {
        if (isDarkPixel(image.data, image.width || CANVAS_WIDTH, xx, yy)) total += 1;
      }
    }
    return total;
  }

  function isGameOverImage(image) {
    return countDarkPixels(
      image,
      GAME_OVER_TEXT_BOX.x,
      GAME_OVER_TEXT_BOX.y,
      GAME_OVER_TEXT_BOX.width,
      GAME_OVER_TEXT_BOX.height
    ) >= GAME_OVER_MIN_INK;
  }

  function matchDigitMask(actual, templateMasks, options) {
    options = options || {};
    var minInk = options.minInk == null ? 6 : options.minInk;
    var maxDiff = options.maxDiff == null ? 45 : options.maxDiff;
    var ink = 0;
    for (var i = 0; i < actual.length; i += 1) ink += actual[i] ? 1 : 0;
    if (ink < minInk) return null;
    var bestDigit = 0;
    var bestDiff = Infinity;
    for (var digit = 0; digit < templateMasks.length; digit += 1) {
      var expected = templateMasks[digit];
      var diff = 0;
      for (var j = 0; j < actual.length; j += 1) {
        if (actual[j] !== expected[j]) diff += 1;
      }
      if (diff < bestDiff) {
        bestDiff = diff;
        bestDigit = digit;
      }
    }
    return bestDiff <= maxDiff ? bestDigit : null;
  }

  var pixelHelpers = {
    isDarkPixel: isDarkPixel,
    findPixelBounds: findPixelBounds,
    findObstacleInImage: findObstacleInImage,
    readPixelObservation: readPixelObservation,
    matchDigitMask: matchDigitMask,
    scoreDigitBoxes: scoreDigitBoxes,
    countDarkPixels: countDarkPixels,
    isGameOverImage: isGameOverImage,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = pixelHelpers;
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  window.DinoSiteAgentPixelHelpers = pixelHelpers;

  if (window.__dinoAiSiteAgent) return;
  window.__dinoAiSiteAgent = true;

  if (window.location.origin !== TARGET_ORIGIN || window.location.pathname !== TARGET_PATH) {
    return;
  }

  var api = window.DinoAI || window.globalDinoAI;
  if (!api || !api.QLearner || !api.encodeObservation) {
    console.warn("DinoAI learner was not found; load learner.js before site-agent.js.");
    return;
  }

  var memoryStore = {};
  var state = {
    learner: new api.QLearner(),
    running: false,
    learning: false,
    epsilon: 0.08,
    episodes: 0,
    score: 0,
    bestScore: 0,
    frames: 0,
    mode: "idle",
    lastSave: 0,
    lastObs: null,
    prevObs: null,
    prevAction: 0,
    prevScore: 0,
    lastDinoY: 93,
    lastPressed: null,
    holdFrames: 0,
    pendingRestart: 0,
    crashedLastTick: false,
    timer: 0,
    canvasReady: false,
    scoreReadable: false,
    scoreBaselineSet: false,
    lastScoreAcceptedAt: 0,
    needsGameStart: false,
  };
  var scoreTemplates = null;
  var scoreTemplatePromise = null;

  var scanCanvas = document.createElement("canvas");
  scanCanvas.width = CANVAS_WIDTH;
  scanCanvas.height = CANVAS_HEIGHT;
  var scanCtx = scanCanvas.getContext("2d", { willReadFrequently: true });
  var digitCanvas = document.createElement("canvas");
  digitCanvas.width = 10;
  digitCanvas.height = 13;
  var digitCtx = digitCanvas.getContext("2d", { willReadFrequently: true });

  var widget = createWidget();
  document.documentElement.appendChild(widget.root);

  function loadScoreTemplates() {
    if (scoreTemplates) return Promise.resolve(scoreTemplates);
    if (scoreTemplatePromise) return scoreTemplatePromise;
    scoreTemplatePromise = new Promise(function (resolve) {
      var ratio = window.devicePixelRatio > 1 ? 2 : 1;
      var image = new Image();
      image.onload = function () {
        var templates = [];
        var sourceX = ratio > 1 ? 1294 : 655;
        var sourceY = 2;
        for (var digit = 0; digit < 10; digit += 1) {
          digitCtx.clearRect(0, 0, 10, 13);
          digitCtx.drawImage(image, sourceX + digit * 10 * ratio, sourceY, 10 * ratio, 13 * ratio, 0, 0, 10, 13);
          templates[digit] = digitCtx.getImageData(0, 0, 10, 13).data;
        }
        scoreTemplates = templates;
        resolve(scoreTemplates);
      };
      image.onerror = function () {
        scoreTemplates = [];
        resolve(scoreTemplates);
      };
      image.src = ratio > 1 ? "/assets/200-offline-sprite.png" : "/assets/100-offline-sprite.png";
    });
    return scoreTemplatePromise;
  }

  function digitMaskFromImage(image, x, y) {
    var mask = [];
    for (var yy = 0; yy < 13; yy += 1) {
      for (var xx = 0; xx < 10; xx += 1) {
        mask.push(isDarkPixel(image.data, image.width || CANVAS_WIDTH, x + xx, y + yy) ? 1 : 0);
      }
    }
    return mask;
  }

  function templateMask(data) {
    var mask = [];
    for (var i = 0; i < data.length; i += 4) {
      mask.push(data[i + 3] > 40 && data[i] < 140 && data[i + 1] < 140 && data[i + 2] < 140 ? 1 : 0);
    }
    return mask;
  }

  function readScoreDigit(image, x, y) {
    if (!scoreTemplates || scoreTemplates.length < 10) return null;
    var actual = digitMaskFromImage(image, x, y);
    var templates = [];
    for (var digit = 0; digit < 10; digit += 1) {
      templates[digit] = templateMask(scoreTemplates[digit]);
    }
    return matchDigitMask(actual, templates);
  }

  function readCanvasScore(image) {
    if (!image || !scoreTemplates || scoreTemplates.length < 10) return null;
    var digits = [];
    var boxes = scoreDigitBoxes();
    for (var i = 0; i < boxes.length; i += 1) {
      var digit = readScoreDigit(image, boxes[i].x, boxes[i].y);
      if (digit == null) return null;
      digits.push(String(digit));
    }
    return Number(digits.join(""));
  }

  function storageGet(key, fallback) {
    return new Promise(function (resolve) {
      try {
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
          chrome.storage.local.get(key, function (items) {
            resolve(items && items[key] != null ? items[key] : fallback);
          });
          return;
        }
      } catch (error) {
        // Fall through to local storage.
      }
      try {
        var raw = localStorage.getItem(key);
        resolve(raw == null ? fallback : JSON.parse(raw));
      } catch (error) {
        resolve(memoryStore[key] == null ? fallback : memoryStore[key]);
      }
    });
  }

  function storageSet(key, value) {
    return new Promise(function (resolve) {
      try {
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
          var item = {};
          item[key] = value;
          chrome.storage.local.set(item, resolve);
          return;
        }
      } catch (error) {
        // Fall through to local storage.
      }
      try {
        localStorage.setItem(key, JSON.stringify(value));
      } catch (error) {
        memoryStore[key] = value;
      }
      resolve();
    });
  }

  function load() {
    loadScoreTemplates();
    Promise.all([storageGet(STORAGE_KEY, null), storageGet(SETTINGS_KEY, null)]).then(function (items) {
      var policy = items[0];
      var settings = items[1];
      var normalized = normalizePolicy(policy);
      if (normalized) {
        state.learner = api.QLearner.import(normalized);
        applyPolicyMetadata(policy);
      }
      if (settings && typeof settings.epsilon === "number") {
        state.epsilon = settings.epsilon;
      }
      updateWidget();
    });
  }

  function normalizePolicy(policy) {
    if (!policy) return null;
    if (policy.model && policy.model.q) return validatePolicy(policy.model);
    if (policy.q) return validatePolicy(policy);
    return null;
  }

  function validatePolicy(policy) {
    var q = policy && policy.q;
    if (policy.version !== 3 || policy.source !== "chrome-dino.org/ko/classic") return null;
    if (policy.encoderVersion !== api.encoderVersion || policy.stateSchema !== api.stateSchema) return null;
    if (!q || typeof q !== "object") return null;
    var keys = Object.keys(q);
    for (var i = 0; i < keys.length; i += 1) {
      if (keys[i].split("|").length !== 6) return null;
      var row = q[keys[i]];
      if (!Array.isArray(row) || row.length < 3) return null;
      for (var j = 0; j < 3; j += 1) {
        if (!Number.isFinite(Number(row[j]))) return null;
      }
    }
    return policy;
  }

  function applyPolicyMetadata(policy) {
    if (!policy) return;
    var model = policy.model && policy.model.q ? policy.model : policy;
    var episodes = policy.episodes != null ? policy.episodes : model.episodes;
    var best = policy.actualSiteBest != null ? policy.actualSiteBest : model.actualSiteBest;
    if (Number.isFinite(Number(episodes))) state.episodes = Math.max(0, Math.floor(Number(episodes)));
    if (Number.isFinite(Number(best))) state.bestScore = Math.max(0, Number(best));
  }

  function exportPolicy() {
    var policy = state.learner.export();
    policy.version = 3;
    policy.source = "chrome-dino.org/ko/classic";
    policy.encoderVersion = api.encoderVersion;
    policy.stateSchema = api.stateSchema;
    policy.episodes = state.episodes;
    policy.actualSiteBest = state.bestScore;
    policy.history = policy.history || [];
    return policy;
  }

  function savePolicy(force) {
    var now = Date.now();
    if (!force && now - state.lastSave < SAVE_EVERY_MS) return;
    state.lastSave = now;
    storageSet(STORAGE_KEY, exportPolicy());
    storageSet(SETTINGS_KEY, { epsilon: state.epsilon });
  }

  function getCanvas() {
    return document.querySelector("canvas.runner-canvas");
  }

  function getContainer() {
    return document.querySelector(".runner-container");
  }

  function isCrashed(image) {
    if (document.querySelector(".runner-container.crashed")) return true;
    return isGameOverImage(image || drawNormalizedCanvas(getCanvas()));
  }

  function pageBestScore() {
    try {
      var raw = localStorage.getItem("dino:highScore:classic");
      var distance = raw == null ? 0 : Number(raw);
      return Number.isFinite(distance) ? Math.round(distance * 0.025) : 0;
    } catch (error) {
      return 0;
    }
  }

  function drawNormalizedCanvas(canvas) {
    if (!canvas || !scanCtx) return null;
    scanCtx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    try {
      scanCtx.drawImage(canvas, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      return scanCtx.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    } catch (error) {
      return null;
    }
  }

  function isDark(data, x, y) {
    return isDarkPixel(data, CANVAS_WIDTH, x, y);
  }

  function findBounds(image, x1, x2, y1, y2, ignoreHorizon) {
    return findPixelBounds(image, x1, x2, y1, y2, ignoreHorizon);
  }

  function columnCount(data, x) {
    var count = 0;
    for (var y = 45; y <= 139; y += 1) {
      if (y >= 124 && y <= 132) continue;
      if (isDark(data, x, y)) count += 1;
    }
    return count;
  }

  function findObstacle(image) {
    return findObstacleInImage(image);
  }

  function observe(image) {
    if (!image) image = drawNormalizedCanvas(getCanvas());
    var obs = readPixelObservation(image, { frames: state.frames, lastDinoY: state.lastDinoY }, api.encodeObservation);

    state.lastDinoY = obs.dinoY;

    return obs;
  }

  function acceptObservedScore(rawScore) {
    if (rawScore == null || !Number.isFinite(Number(rawScore))) return null;
    var score = Number(rawScore);
    var now = Date.now();
    if (!state.scoreBaselineSet) {
      state.scoreBaselineSet = true;
      state.lastScoreAcceptedAt = now;
      return score;
    }
    if (score < state.score) return null;
    var elapsed = Math.max(16, now - (state.lastScoreAcceptedAt || now));
    var maxIncrease = Math.max(3, Math.ceil(elapsed * 0.05));
    if (score - state.score > maxIncrease) return null;
    state.lastScoreAcceptedAt = now;
    return score;
  }

  function keyEvent(type, keyCode) {
    var key = keyCode === 38 ? "ArrowUp" : keyCode === 40 ? "ArrowDown" : keyCode === 13 ? "Enter" : " ";
    var event = new KeyboardEvent(type, {
      bubbles: true,
      cancelable: true,
      key: key,
      code: key,
      keyCode: keyCode,
      which: keyCode,
    });
    try {
      Object.defineProperty(event, "keyCode", { get: function () { return keyCode; } });
      Object.defineProperty(event, "which", { get: function () { return keyCode; } });
    } catch (error) {
      // Some browsers already honor the constructor values.
    }
    document.dispatchEvent(event);
  }

  function releaseKeys() {
    if (state.lastPressed === "jump") keyEvent("keyup", 38);
    if (state.lastPressed === "duck") keyEvent("keyup", 40);
    state.lastPressed = null;
    state.holdFrames = 0;
  }

  function applyAction(action, obs) {
    if (action === 1) {
      if (state.lastPressed !== "jump" || obs.grounded) {
        releaseKeys();
        keyEvent("keydown", 38);
        state.lastPressed = "jump";
      }
      state.holdFrames = ACTION_HOLD_FRAMES;
      return;
    }

    if (action === 2) {
      if (state.lastPressed !== "duck") {
        releaseKeys();
        keyEvent("keydown", 40);
        state.lastPressed = "duck";
      }
      state.holdFrames = ACTION_HOLD_FRAMES;
      return;
    }

    if (state.lastPressed === "jump" && !obs.grounded) {
      state.holdFrames = Math.max(state.holdFrames, 1);
      return;
    }

    if (state.holdFrames > 0) {
      state.holdFrames -= 1;
      return;
    }
    releaseKeys();
  }

  function updateLearner(obs, crashed) {
    if (!state.prevObs || !state.learning) return;
    var score = obs.score != null && Number.isFinite(Number(obs.score)) ? Number(obs.score) : state.prevScore;
    var reward = 0.04 + Math.max(0, score - state.prevScore) * 0.1;
    if (state.prevObs.distance < 25 && obs.distance > 120) reward += 3;
    if (String(state.prevObs.obstacleType).indexOf("bird") === 0 && state.prevAction === 2 && state.prevObs.distance < 120) reward += 0.4;
    if (crashed) reward -= 35;
    state.learner.update(state.prevObs.state, state.prevAction, reward, obs.state, crashed);
    state.prevScore = score;
  }

  function restartSoon() {
    if (!state.running) return;
    releaseKeys();
    state.pendingRestart = window.setTimeout(function () {
      if (!state.running) {
        state.pendingRestart = 0;
        return;
      }
      keyEvent("keydown", 13);
      keyEvent("keyup", 13);
      window.setTimeout(function () {
        if (!state.running) {
          state.pendingRestart = 0;
          return;
        }
        state.pendingRestart = 0;
        var restartImage = drawNormalizedCanvas(getCanvas());
        if (isCrashed(restartImage)) {
          restartSoon();
          return;
        }
        state.frames = 0;
        state.score = 0;
        state.prevObs = null;
        state.prevScore = 0;
        state.scoreBaselineSet = false;
        state.lastScoreAcceptedAt = 0;
        state.crashedLastTick = false;
      }, 150);
    }, 1000);
  }

  function tick() {
    if (!state.running) return;

    var canvas = getCanvas();
    var image = drawNormalizedCanvas(canvas);
    state.canvasReady = !!image;
    if (!image) {
      state.scoreReadable = false;
      state.lastObs = null;
      if (state.frames % 12 === 0) updateWidget();
      return;
    }

    if (state.needsGameStart) {
      state.needsGameStart = false;
      keyEvent("keydown", 38);
      keyEvent("keyup", 38);
    }

    var crashed = isCrashed(image);
    var obs = observe(image);
    var acceptedScore = acceptObservedScore(obs.score);
    state.scoreReadable = acceptedScore != null;
    obs.score = acceptedScore;
    state.lastObs = obs;
    if (acceptedScore != null) {
      state.score = acceptedScore;
      state.bestScore = Math.max(state.bestScore, state.score, pageBestScore());
    } else {
      state.bestScore = Math.max(state.bestScore, pageBestScore());
    }

    if (crashed) {
      if (!state.crashedLastTick) {
        updateLearner(obs, true);
        if (state.learning) state.episodes += 1;
        savePolicy(true);
        restartSoon();
      }
      state.crashedLastTick = true;
      updateWidget();
      return;
    }

    state.crashedLastTick = false;
    state.frames += 1;
    updateLearner(obs, false);

    var action = state.learner.act(obs.state, state.learning ? state.epsilon : 0);
    applyAction(action, obs);
    state.prevObs = obs;
    state.prevAction = action;
    state.prevScore = state.score;

    savePolicy(false);
    if (state.frames % 12 === 0) updateWidget();
  }

  function loop() {
    if (!state.running) return;
    tick();
    state.timer = window.setTimeout(loop, TICK_MS);
  }

  function start(learning, epsilon) {
    if (typeof epsilon === "number") state.epsilon = epsilon;
    state.running = true;
    state.learning = !!learning;
    state.mode = state.learning ? "learning" : "play";
    state.frames = 0;
    state.score = 0;
    state.prevObs = null;
    state.prevScore = 0;
    state.scoreBaselineSet = false;
    state.lastScoreAcceptedAt = 0;
    state.scoreReadable = false;
    state.needsGameStart = true;
    releaseKeys();
    if (!state.timer) loop();
    updateWidget();
    savePolicy(true);
    return status();
  }

  function stop() {
    state.running = false;
    state.learning = false;
    state.mode = "idle";
    window.clearTimeout(state.timer);
    state.timer = 0;
    window.clearTimeout(state.pendingRestart);
    state.pendingRestart = 0;
    state.needsGameStart = false;
    releaseKeys();
    savePolicy(true);
    updateWidget();
    return status();
  }

  function status() {
    return {
      mode: state.mode,
      running: state.running,
      learning: state.learning,
      epsilon: state.epsilon,
      score: state.score,
      scoreLabel: String(state.score),
      bestScore: Math.max(state.bestScore, pageBestScore()),
      episodes: state.episodes,
      states: Object.keys(state.learner.q || {}).length,
      lastAction: ACTIONS[state.prevAction] || "run",
      canvasReady: state.canvasReady,
      scoreReadable: state.scoreReadable,
      crashed: state.lastObs ? isCrashed() : false,
      observation: state.lastObs,
    };
  }

  function modeLabel(mode) {
    if (mode === "learning") return "학습 중";
    if (mode === "play") return "실행 중";
    return "대기";
  }

  function setEpsilon(epsilon) {
    if (Number.isFinite(epsilon)) state.epsilon = Math.max(0, Math.min(1, epsilon));
    savePolicy(true);
    updateWidget();
    return status();
  }

  function importPolicy(policy) {
    var normalized = normalizePolicy(policy);
    if (!normalized) throw new Error("Invalid policy");
    state.learner = api.QLearner.import(normalized);
    applyPolicyMetadata(policy);
    savePolicy(true);
    updateWidget();
    return status();
  }

  function createWidget() {
    var style = document.createElement("style");
    style.textContent = [
      "#dino-ai-widget{position:fixed;right:16px;bottom:16px;z-index:2147483647;width:238px;padding:10px;border:1px solid #dadce0;border-radius:8px;background:rgba(255,255,255,.94);box-shadow:0 8px 24px rgba(60,64,67,.25);color:#202124;font:12px/1.35 Arial,sans-serif}",
      "#dino-ai-widget strong{display:block;margin-bottom:6px;font-size:13px}",
      "#dino-ai-widget .row{display:flex;justify-content:space-between;gap:8px;margin:3px 0}",
      "#dino-ai-widget button{min-height:28px;margin:3px 2px 0 0;border:1px solid #3c4043;border-radius:6px;background:#fff;color:#202124;font:12px Arial,sans-serif;cursor:pointer}",
      "#dino-ai-widget button:hover{background:#f1f3f4}",
      "#dino-ai-widget input[type=range]{width:100%}",
      "#dino-ai-widget label{display:block;margin-top:6px;color:#5f6368}",
      "#dino-ai-widget .actions{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}",
    ].join("");
    var root = document.createElement("aside");
    root.id = "dino-ai-widget";
    root.innerHTML = [
      "<strong>Dino AI</strong>",
      "<div class='row'><span>상태</span><b data-field='mode'>대기</b></div>",
      "<div class='row'><span>현재 점수</span><b data-field='score'>0</b></div>",
      "<div class='row'><span>사이트 최고점</span><b data-field='best'>0</b></div>",
      "<div class='row'><span>실제 학습 횟수</span><b data-field='episodes'>0</b></div>",
      "<div class='row'><span>Q 상태 수</span><b data-field='states'>0</b></div>",
      "<div class='row'><span>캔버스</span><b data-field='canvas'>대기</b></div>",
      "<div class='row'><span>점수 판독</span><b data-field='score-read'>대기</b></div>",
      "<label>탐험 비율 <output data-field='epsilon'>0.08</output><input data-action='epsilon' type='range' min='0' max='0.6' step='0.01' value='0.08'></label>",
      "<div class='actions'><button data-action='learn'>학습</button><button data-action='play'>실행</button><button data-action='stop'>중지</button></div>",
      "<div><button data-action='export'>정책 내보내기</button></div>",
    ].join("");
    document.head.appendChild(style);
    root.addEventListener("click", function (event) {
      var action = event.target && event.target.getAttribute("data-action");
      if (action === "learn") start(true, state.epsilon);
      if (action === "play") start(false, 0);
      if (action === "stop") stop();
      if (action === "export") downloadPolicy();
    });
    root.addEventListener("input", function (event) {
      if (event.target && event.target.getAttribute("data-action") === "epsilon") {
        setEpsilon(Number(event.target.value));
      }
    });
    return { root: root };
  }

  function updateWidget() {
    var s = status();
    var root = widget.root;
    var fields = {
      mode: modeLabel(s.mode),
      score: s.scoreLabel,
      best: s.bestScore,
      episodes: s.episodes,
      states: s.states,
      canvas: s.canvasReady ? "감지" : "미감지",
      "score-read": s.scoreReadable ? "정상" : "대기/깜빡임",
      epsilon: s.epsilon.toFixed(2),
    };
    Object.keys(fields).forEach(function (name) {
      var node = root.querySelector("[data-field='" + name + "']");
      if (node) node.textContent = fields[name];
    });
    var slider = root.querySelector("[data-action='epsilon']");
    if (slider && document.activeElement !== slider) slider.value = String(s.epsilon);
  }

  function downloadPolicy() {
    var blob = new Blob([JSON.stringify(exportPolicy(), null, 2)], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "dino-policy.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function handleMessage(message, sender, sendResponse) {
    try {
      if (!message || !message.type) return;
      if (message.type === "DINO_AI_STATUS") sendResponse(status());
      if (message.type === "DINO_AI_START") sendResponse(start(!!message.learning, Number(message.epsilon)));
      if (message.type === "DINO_AI_STOP") sendResponse(stop());
      if (message.type === "DINO_AI_SET_EPSILON") sendResponse(setEpsilon(Number(message.epsilon)));
      if (message.type === "DINO_AI_EXPORT") sendResponse({ policy: exportPolicy(), status: status() });
      if (message.type === "DINO_AI_IMPORT") sendResponse(importPolicy(message.policy));
    } catch (error) {
      sendResponse({ error: String(error && error.message ? error.message : error) });
    }
  }

  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener(handleMessage);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
  });
  window.addEventListener("beforeunload", stop);

  window.DinoSiteAgent = {
    start: start,
    stop: stop,
    status: status,
    observe: observe,
    importPolicy: importPolicy,
    exportPolicy: function () {
      return exportPolicy();
    },
  };

  load();
})();
