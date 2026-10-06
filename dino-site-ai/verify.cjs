const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const folder = path.join(__dirname, 'extension');
const learnerApi = require(path.join(folder, 'learner.js'));
const pixelApi = require(path.join(folder, 'site-agent.js'));

// Q-learning cold start / compact state / guided bootstrap / roundtrip.
const learner = new learnerApi.QLearner({ alpha: 0.5, gamma: 0.9 });
assert.equal(Object.keys(learner.q).length, 0);
assert.equal(learnerApi.DinoEnv, undefined);
assert.equal(learner.trainEpisode, undefined);

const cactusState = learnerApi.encodeObservation({
  distance: 90,
  speed: 7,
  obstacleType: 'cactusSmall',
  grounded: true,
});
assert.equal(cactusState.split('|').length, 4);
assert.equal(learner.act(cactusState, 0), 1, 'close cactus should bootstrap toward jump');

const noObstacleState = learnerApi.encodeObservation({
  distance: 999,
  speed: 7,
  obstacleType: 'none',
  grounded: true,
});
assert.equal(learner.act(noObstacleState, 0), 0, 'clear road should bootstrap toward run');

learner.update(cactusState, 1, 10, cactusState, true);
assert.equal(learner.act(cactusState, 0), 1);
learner.update(cactusState, 1, -30, cactusState, true);
const zeroRng = { random: () => 0 };
assert.equal(learner.act(cactusState, 0, zeroRng), 0);
assert.deepEqual(learnerApi.QLearner.import(learner.export()).q, learner.q);

// Pixel crash detector: blank canvas must be safe; GAME OVER-sized ink must trip it.
function makeImage() {
  const width = 600;
  const height = 150;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) {
    data[i] = 255;
    data[i + 1] = 255;
    data[i + 2] = 255;
    data[i + 3] = 255;
  }
  return { width, height, data };
}
function paintDark(image, x, y) {
  const i = (y * image.width + x) * 4;
  image.data[i] = 83;
  image.data[i + 1] = 83;
  image.data[i + 2] = 83;
  image.data[i + 3] = 255;
}
const blank = makeImage();
assert.equal(pixelApi.isGameOverImage(blank), false);
const gameOver = makeImage();
let painted = 0;
for (let y = 42; y < 53 && painted < 330; y += 1) {
  for (let x = 205; x < 396 && painted < 330; x += 1) {
    paintDark(gameOver, x, y);
    painted += 1;
  }
}
assert.equal(pixelApi.isGameOverImage(gameOver), true);

// Manifest / package scope.
const manifest = JSON.parse(fs.readFileSync(path.join(folder, 'manifest.json'), 'utf8'));
assert.equal(manifest.version, '0.4.0');
assert.deepEqual(manifest.permissions, ['storage']);
assert(manifest.host_permissions.includes('https://chrome-dino.org/ko/classic/*'));
assert(manifest.host_permissions.includes('https://raw.githubusercontent.com/*'));
assert.deepEqual(manifest.content_scripts[0].matches, ['https://chrome-dino.org/ko/classic/*']);
assert.deepEqual(manifest.content_scripts[0].js, ['learner.js', 'site-agent.js']);
assert(!JSON.stringify(manifest).includes('pretrained'));

const allowedFiles = new Set(['learner.js', 'site-agent.js', 'manifest.json', 'popup.html', 'popup.js', 'popup.css']);
for (const name of fs.readdirSync(folder)) {
  assert(allowedFiles.has(name), `unexpected extension file: ${name}`);
}

// Syntax + v0.4 regressions.
for (const file of ['learner.js', 'site-agent.js', 'popup.js']) {
  new vm.Script(fs.readFileSync(path.join(folder, file), 'utf8'), { filename: file });
}
const adapter = fs.readFileSync(path.join(folder, 'site-agent.js'), 'utf8');
const popup = fs.readFileSync(path.join(folder, 'popup.js'), 'utf8');

assert(adapter.includes('dinoAi.actualSitePolicy.v3'));
assert(adapter.includes('var EPSILON_MIN = 0.05'));
assert(adapter.includes('var EPSILON_DECAY = 0.992'));
assert(adapter.includes('var CRASH_TRACE_STEPS = 14'));
assert(adapter.includes('function allowedActions(obs)'));
assert(adapter.includes('function punishRecentCrash()'));
assert(adapter.includes('state.aiBestScore'));
assert(adapter.includes('siteBestScore: pageBestScore()'));
assert(adapter.includes('DINO_AI_CHECK_UPDATE'));
assert(adapter.includes('raw.githubusercontent.com/kimyejun978-tech/ARGUS'));
assert((adapter.match(/if \(!state\.running\)/g) || []).length >= 3, 'restart/loop paths must re-check running');

assert.equal(learnerApi.stateSchema, 'profile|distanceBucket|motion|speedBucket');
assert.equal(learnerApi.encoderVersion, 'chrome-dino-classic-profile-v3');
assert(popup.includes('DINO_AI_CHECK_UPDATE'));
assert(popup.includes('aiBestScore'));
assert(popup.includes('siteBestScore'));

// Non-target pages must return before touching the DOM.
for (const location of [
  { origin: 'http://127.0.0.1:8766', pathname: '/ko/classic/' },
  { origin: 'https://chrome-dino.org', pathname: '/ko/faster/' },
  { origin: 'https://example.com', pathname: '/ko/classic/' },
]) {
  const document = new Proxy({}, { get() { throw new Error('Non-target page was accessed'); } });
  vm.runInNewContext(adapter, { window: { location }, document });
}

console.log('PASS: Dino AI v0.4 learning efficiency, AI/site best split, updater, target scope, crash detection, permissions, syntax.');
