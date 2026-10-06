(function (root, factory) {
  var api = factory();
  root.DinoAI = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ENCODER_VERSION = "chrome-dino-classic-profile-v2";
  var STATE_SCHEMA = "kind|profile|timeBucket|distanceBucket|motion|speedBucket";

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
    var obstacleTop = input.obstacleTop == null ? groundY : Number(input.obstacleTop) || groundY;
    var obstacleBottom = input.obstacleBottom == null ? groundY : Number(input.obstacleBottom) || groundY;
    var obstacleHeight = Math.max(1, obstacleBottom - obstacleTop);
    var time = distance / Math.max(1, speed);
    var kind = "none";
    var profile = "none";

    if (distance < 900) {
      if (obstacleBottom <= 95) {
        kind = "none";
        profile = "birdHigh";
      } else if (obstacleTop < 90 && obstacleBottom <= 122) {
        kind = "duck";
        profile = "birdMid";
      } else {
        kind = "jump";
        if (obstacleTop >= 95 && obstacleBottom >= 135 && obstacleHeight >= 38) {
          profile = "birdLow";
        } else if (obstacleTop <= 95 && obstacleHeight >= 45) {
          profile = "cactusLarge";
        } else {
          profile = "cactusSmall";
        }
      }
    }

    var motion = "g";
    if (!grounded) {
      motion = vy < -5 ? "upFast" : vy < 0 ? "up" : vy < 5 ? "fall" : "fallFast";
    } else if (ducking) {
      motion = "duck";
    }

    return [
      kind,
      profile,
      bucket(time, [5, 8, 11, 15, 20, 28, 40, 58]),
      bucket(distance, [22, 45, 70, 105, 145, 200, 280, 390]),
      motion,
      bucket(speed, [7, 8.5, 10, 11.5, 13]),
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
      this.q[state] = [0, 0, 0];
    }
    return this.q[state];
  };

  QLearner.prototype.act = function (state, epsilon, rng) {
    epsilon = epsilon == null ? 0 : epsilon;
    rng = rng || Math;

    var random = typeof rng.next === "function" ? rng.next.bind(rng) : rng.random.bind(rng);
    if (random() < epsilon) {
      return this.actions[Math.floor(random() * this.actions.length)];
    }

    var row = this._row(state);
    var best = 0;
    for (var i = 1; i < row.length; i += 1) {
      if (row[i] > row[best]) {
        best = i;
      }
    }
    return best;
  };

  QLearner.prototype.actObservation = function (observation, epsilon, rng) {
    return this.act(encodeObservation(observation), epsilon, rng);
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
