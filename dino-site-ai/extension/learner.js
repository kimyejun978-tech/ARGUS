(function (root, factory) {
  var api = factory();
  root.DinoAI = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ENCODER_VERSION = "chrome-dino-classic-profile-v3";
  var STATE_SCHEMA = "profile|distanceBucket|motion|speedBucket";

  function bucket(value, cuts) {
    for (var i = 0; i < cuts.length; i += 1) {
      if (value <= cuts[i]) return i;
    }
    return cuts.length;
  }

  function encodeObservation(input) {
    input = input || {};

    var speed = Number(input.speed) || 6;
    var distance = input.distance == null ? 999 : Math.max(0, Number(input.distance) || 0);
    var dinoY = input.dinoY == null ? 93 : Number(input.dinoY) || 0;
    var groundY = input.groundY == null ? 140 : Number(input.groundY) || 140;
    var dinoHeight = input.dinoHeight == null ? 47 : Number(input.dinoHeight) || 47;
    var vy = Number(input.vy) || 0;
    var grounded = input.grounded == null ? dinoY >= groundY - dinoHeight - 1 : !!input.grounded;
    var ducking = !!input.ducking;
    var profile = input.obstacleType || "none";

    if (distance >= 520) profile = "none";

    var motion = "ground";
    if (!grounded) {
      motion = vy < 0 ? "airUp" : "airDown";
    } else if (ducking) {
      motion = "duck";
    }

    return [
      profile,
      bucket(distance, [35, 60, 90, 125, 170, 230, 320, 520]),
      motion,
      bucket(speed, [7.5, 9.5, 11.5, 13]),
    ].join("|");
  }

  function QLearner(options) {
    options = options || {};
    this.alpha = options.alpha == null ? 0.18 : options.alpha;
    this.gamma = options.gamma == null ? 0.96 : options.gamma;
    this.actions = [0, 1, 2];
    this.q = options.q ? this._copyQ(options.q) : {};
    this.lastEpisodeScore = 0;
  }

  QLearner.prototype._copyQ = function (q) {
    var out = {};
    Object.keys(q).forEach(function (key) {
      out[key] = [Number(q[key][0]) || 0, Number(q[key][1]) || 0, Number(q[key][2]) || 0];
    });
    return out;
  };

  QLearner.prototype._row = function (state) {
    if (!this.q[state]) {
      this.q[state] = this._bootstrapRow(state);
    }
    return this.q[state];
  };

  QLearner.prototype._bootstrapRow = function (state) {
    var parts = String(state || "").split("|");
    var profile = parts[0] || "none";
    var distanceBucket = Number(parts[1]);
    var motion = parts[2] || "ground";
    var row = [0, 0, 0];

    // Small priors prevent a brand-new policy from choosing run forever.
    // Q-learning can still overwrite these values immediately from experience.
    if (motion === "ground" || motion === "duck") {
      if (distanceBucket <= 3) {
        if (profile === "birdMid") row[2] = 0.75;
        else if (profile === "birdHigh") row[0] = 0.35;
        else if (profile !== "none") row[1] = 0.75;
      } else {
        row[0] = 0.12;
      }
    } else {
      row[0] = 0.12;
      row[2] = 0.03;
    }
    return row;
  };

  QLearner.prototype.act = function (state, epsilon, rng, allowedActions) {
    epsilon = epsilon == null ? 0 : epsilon;
    rng = rng || Math;
    allowedActions = allowedActions && allowedActions.length ? allowedActions.slice() : this.actions.slice();

    var random = typeof rng.next === "function" ? rng.next.bind(rng) : rng.random.bind(rng);
    if (random() < epsilon) {
      return allowedActions[Math.floor(random() * allowedActions.length)];
    }

    var row = this._row(state);
    var bestValue = -Infinity;
    var ties = [];
    for (var i = 0; i < allowedActions.length; i += 1) {
      var action = allowedActions[i];
      var value = row[action];
      if (value > bestValue + 1e-9) {
        bestValue = value;
        ties = [action];
      } else if (Math.abs(value - bestValue) <= 1e-9) {
        ties.push(action);
      }
    }
    return ties[Math.floor(random() * ties.length)];
  };

  QLearner.prototype.actObservation = function (observation, epsilon, rng, allowedActions) {
    return this.act(encodeObservation(observation), epsilon, rng, allowedActions);
  };

  QLearner.prototype.update = function (state, action, reward, nextState, done) {
    var row = this._row(state);
    var next = this._row(nextState);
    var maxNext = Math.max(next[0], next[1], next[2]);
    var target = reward + (done ? 0 : this.gamma * maxNext);
    row[action] += this.alpha * (target - row[action]);
    return row[action];
  };

  QLearner.prototype.export = function () {
    return {
      alpha: this.alpha,
      gamma: this.gamma,
      q: this._copyQ(this.q),
      encoderVersion: ENCODER_VERSION,
      stateSchema: STATE_SCHEMA,
    };
  };

  QLearner.import = function (data) {
    return new QLearner(data || {});
  };

  return {
    QLearner: QLearner,
    encodeObservation: encodeObservation,
    encoderVersion: ENCODER_VERSION,
    stateSchema: STATE_SCHEMA,
  };
});
