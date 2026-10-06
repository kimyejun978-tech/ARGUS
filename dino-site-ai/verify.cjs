const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const folder = path.join(__dirname, 'extension');
const learnerApi = require(path.join(folder, 'learner.js'));
const pixelApi = require(path.join(folder, 'site-agent.js'));

// Q-learning cold start / terminal update / roundtrip.
const learner = new learnerApi.QLearner({ alpha: 0.5, gamma: 0.9 });
assert.equal(Object.keys(learner.q).length, 0);
assert.equal(learnerApi.DinoEnv, undefined);
assert.equal(learner.trainEpisode, undefined);
const qState = learnerApi.encodeObservation({ distance: 100, speed: 7, obstacleTop: 75, obstacleBottom: 115, grounded: true });
assert.equal(learner.act(qState, 0), 0);
learner.update(qState, 2, 10, qState, true);
assert.equal(learner.act(qState, 0), 2);
learner.update(qState, 2, -20, qState, true);
assert.equal(learner.act(qState, 0), 0);
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
assert.equal(manifest.version, '0.3.0');
assert.deepEqual(manifest.permissions, ['storage']);
assert.deepEqual(manifest.host_permissions, ['https://chrome-dino.org/ko/classic/*']);
assert.deepEqual(manifest.content_scripts[0].js, ['learner.js', 'site-agent.js']);
assert(!JSON.stringify(manifest).includes('pretrained'));
const allowedFiles = new Set(['learner.js', 'site-agent.js', 'manifest.json', 'popup.html', 'popup.js', 'popup.css']);
for (const name of fs.readdirSync(folder)) assert(allowedFiles.has(name), `unexpected extension file: ${name}`);

// Syntax + regressions that the previous static test missed.
for (const file of ['learner.js', 'site-agent.js', 'popup.js']) {
  new vm.Script(fs.readFileSync(path.join(folder, file), 'utf8'), { filename: file });
}
const adapter = fs.readFileSync(path.join(folder, 'site-agent.js'), 'utf8');
assert(adapter.includes('function applyPolicyMetadata(policy)'));
assert(adapter.includes('dinoAi.actualSitePolicy.v2'));
assert(adapter.includes('isGameOverImage'));
assert(adapter.includes('GAME_OVER_MIN_INK = 320'));
assert((adapter.match(/if \(!state\.running\)/g) || []).length >= 3, 'restart/loop paths must re-check running');

// Non-target pages must return before touching the DOM.
for (const location of [
  { origin: 'http://127.0.0.1:8766', pathname: '/ko/classic/' },
  { origin: 'https://chrome-dino.org', pathname: '/ko/faster/' },
  { origin: 'https://example.com', pathname: '/ko/classic/' },
]) {
  const document = new Proxy({}, { get() { throw new Error('Non-target page was accessed'); } });
  vm.runInNewContext(adapter, { window: { location }, document });
}

// Cross-check against the captured real-site engine when it is available.
const siteEnginePath = path.join(__dirname, '..', '..', 'work', 'site-game.js');
if (fs.existsSync(siteEnginePath)) {
  const siteEngine = fs.readFileSync(siteEnginePath, 'utf8');
  assert(siteEngine.includes('textSprite:{x:655,y:2}'));
  assert(siteEngine.includes('this.x=t-11*(this.maxScoreUnits+1)'));
  assert(siteEngine.includes('this.crashed=!0'));
  assert(siteEngine.includes('drawGameOverText'));
}

console.log('PASS: site-only scope, Q-learning, score/crash helpers, import metadata, stop guards, permissions, syntax, real-site engine invariants.');
