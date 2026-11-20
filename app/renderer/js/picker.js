// Board selection. The screen is shown dimmed; the board the program found is lit up. Confirm with
// Return, or grab the corners / drag a new rectangle if it guessed wrong.

import { h, icon, piece } from './dom.js';
import { Spring, reducedMotion, springCurve } from './spring.js';

const shot = document.getElementById('shot');
const maskSvg = document.getElementById('mask');
const frame = document.getElementById('frame');
const hud = document.getElementById('hud');
const stage = document.getElementById('stage');
const editor = document.getElementById('editor');

(() => { // the piece sprite, for the identify-your-pieces editor
  const doc = new DOMParser().parseFromString(window.coach.asset('pieces.svg'), 'image/svg+xml');
  const svg = document.importNode(doc.documentElement, true);
  svg.setAttribute('style', 'display:none');
  document.body.prepend(svg);
})();

let info = null; // { width, height, scaleX, scaleY, candidates }
let rect = null; // board rectangle in screenshot pixels: { x, y, size }
let candidateIndex = 0;
let mode = 'idle'; // idle | learning | success | error | none
let message = '';
let lastResult = null;
let reviewMode = false; // open the piece editor even when the reading looks certain
let learningText = ['Learning your board…', 'Checking the starting position and which side you are on.'];

const sx = new Spring(0, { response: 0.45, damping: 0.88 });
const sy = new Spring(0, { response: 0.45, damping: 0.88 });
const ss = new Spring(0, { response: 0.45, damping: 0.88 });

const toDip = (v, axis) => v * (axis === 'x' ? info.scaleX : info.scaleY);
const fromDip = (v, axis) => v / (axis === 'x' ? info.scaleX : info.scaleY);

function paint() {
  if (!info) return;
  const x = toDip(sx.value, 'x');
  const y = toDip(sy.value, 'y');
  const w = toDip(ss.value, 'x');
  const hgt = toDip(ss.value, 'y');
  frame.style.transform = `translate(${x}px, ${y}px)`;
  frame.style.width = `${w}px`;
  frame.style.height = `${hgt}px`;
  const W = innerWidth;
  const H = innerHeight;
  maskSvg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  maskSvg.innerHTML = `<defs><mask id="hole"><rect width="${W}" height="${H}" fill="#fff"/><rect x="${x}" y="${y}" width="${w}" height="${hgt}" rx="6" fill="#000"/></mask></defs>`
    + `<rect width="${W}" height="${H}" fill="rgba(0,0,0,0.62)" mask="url(#hole)"/>`;
  placeHandles(x, y, w, hgt);
}
[sx, sy, ss].forEach((s) => s.on(paint));

let handles = [];
function placeHandles(x, y, w, hgt) {
  if (!handles.length) {
    handles = ['nw', 'ne', 'sw', 'se'].map((corner) => {
      const el = h('div', { class: 'handle', dataset: { corner }, style: { cursor: corner === 'nw' || corner === 'se' ? 'nwse-resize' : 'nesw-resize' } });
      stage.append(el);
      return el;
    });
  }
  const spots = { nw: [x, y], ne: [x + w, y], sw: [x, y + hgt], se: [x + w, y + hgt] };
  handles.forEach((el) => {
    const [px, py] = spots[el.dataset.corner];
    el.style.left = `${px}px`;
    el.style.top = `${py}px`;
    el.style.display = rect && mode !== 'learning' && mode !== 'success' ? 'block' : 'none';
  });
}

function setRect(next, animate = true) {
  rect = next;
  frame.hidden = !next;
  if (!next) { handles.forEach((el) => { el.style.display = 'none'; }); return; }
  if (animate) { sx.to(next.x); sy.to(next.y); ss.to(next.size); } else { sx.set(next.x); sy.set(next.y); ss.set(next.size); }
}

// -------------------------------------------------------------------- HUD
function renderHud() {
  hud.replaceChildren();
  const body = [];
  if (mode === 'learning') {
    body.push(h('div', { class: 'spinner' }), h('div', { class: 'title-2' }, learningText[0]), h('div', { class: 'callout', style: { color: 'rgba(235,235,245,.65)' } }, learningText[1]));
  } else if (mode === 'success') {
    body.push(h('div', { class: 'big-check' }, icon('check')), h('div', { class: 'title-2' }, message.title), h('div', { class: 'callout', style: { color: 'rgba(235,235,245,.65)' } }, message.detail));
  } else if (mode === 'error') {
    body.push(h('div', { class: 'title-2', style: { color: 'var(--red)' } }, 'That didn’t work'), h('div', { class: 'callout', style: { color: 'rgba(235,235,245,.75)' } }, message),
      h('div', { class: 'row' },
        h('button', { class: 'btn', onclick: () => window.picker.retake() }, 'Retake screenshot'),
        lastResult && lastResult.joinable ? h('button', { class: 'btn primary', onclick: startInspect }, 'Join this game…') : h('button', { class: 'btn primary', onclick: () => confirm() }, 'Try again')),
      h('div', { class: 'hint-keys' }, 'Adjust the highlighted square first if needed.'));
  } else {
    const found = rect && info.candidates.length > 0 && mode !== 'none';
    body.push(h('div', { class: 'title-2' }, found ? 'Is this your board?' : 'Show me your board'),
      h('div', { class: 'callout', style: { color: 'rgba(235,235,245,.65)' } },
        found ? 'I found it on your screen. Drag the corners if it is slightly off.' : 'I couldn’t find a board by myself. Drag a rectangle around the 8 × 8 squares.'),
      h('div', { class: 'row' },
        h('button', { class: 'btn', onclick: () => window.picker.cancel() }, 'Cancel'),
        h('button', { class: 'btn', onclick: () => window.picker.retake() }, 'Retake'),
        h('button', { class: 'btn primary', disabled: !rect, onclick: () => confirm() }, 'Use this board')),
      h('div', { class: 'hint-keys' }, h('kbd', {}, 'Return'), ' use this board   ', h('kbd', {}, 'Esc'), ' cancel   ', h('kbd', {}, 'R'), ' retake',
        info.candidates.length > 1 ? [h('span', {}, '   '), h('kbd', {}, 'Tab'), ' next board'] : null));
  }
  hud.append(...body);
  if (!reducedMotion()) hud.animate([{ opacity: 0.0, transform: 'translateX(-50%) translateY(-10px) scale(0.97)' }, { opacity: 1, transform: 'translateX(-50%)' }], { duration: 520, easing: springCurve(0.42, 0.85).easing });
}

function confirm(extra = {}) {
  if (!rect || mode === 'learning') return;
  if (!extra || !extra.fen) learningText = ['Learning your board…', 'Checking the starting position and which side you are on.'];
  else learningText = ['Learning your board…', 'Teaching myself how your pieces look from this position.'];
  mode = 'learning';
  renderHud();
  window.picker.confirm({ x: Math.round(rect.x), y: Math.round(rect.y), size: Math.round(rect.size), ...(extra && extra.fen ? extra : {}) });
}

// ---------------------------------------------------- join a game in progress
const KINDS = ['p', 'n', 'b', 'r', 'q', 'k'];
let inspected = null;
let assigned = {};
let userColor = 'white';
let turn = 'w';

function startInspect() {
  if (!rect) return;
  learningText = ['Reading your game…', 'Looking at every piece and working out whose move it is.'];
  mode = 'learning';
  renderHud();
  window.picker.inspect({ x: Math.round(rect.x), y: Math.round(rect.y), size: Math.round(rect.size) });
}

function renderEditor() {
  editor.replaceChildren();
  editor.classList.add('open');
  const todo = inspected.groups.filter((g) => !assigned[g.id]).length;
  const note = h('div', { class: 'callout', style: { color: 'var(--red)', minHeight: '20px', marginTop: '8px' } });

  const ordered = [...inspected.groups].sort((a, b) => (a.color === b.color ? b.squares.length - a.squares.length : a.color === 'w' ? -1 : 1));
  const tiles = h('div', { class: 'tiles' }, ordered.map((group) => {
    const row = h('div', { class: 'kinds' }, KINDS.map((kind) => {
      const symbol = (group.color === 'w' ? 'w' : 'b') + kind;
      return h('button', { type: 'button', title: kind, 'aria-pressed': String(assigned[group.id] === kind), onclick: () => { assigned[group.id] = kind; renderEditor(); } }, piece(symbol));
    }));
    return h('div', { class: `tile${assigned[group.id] ? '' : ' todo'}` },
      h('div', { class: 'caption', style: { textAlign: 'center', marginBottom: '6px' } }, group.color === 'w' ? 'White piece' : 'Black piece'),
      h('div', { class: 'shot' }, h('img', { src: group.example, alt: '' }), h('b', {}, `×${group.squares.length}`)),
      row);
  }));

  const mini = h('div', { class: 'mini' });
  for (const group of inspected.groups) {
    for (const square of group.squares) {
      const r = Math.floor(square / 8); const c = square % 8;
      const kind = assigned[group.id];
      mini.append(kind
        ? h('div', { class: 'p', style: { left: `${c * 40}px`, top: `${r * 40}px` } }, piece((group.color === 'w' ? 'w' : 'b') + kind))
        : h('div', { class: 'unk', style: { left: `${c * 40}px`, top: `${r * 40}px`, color: 'var(--orange)' } }, '?'));
    }
  }
  const segment = (options, value, onPick) => h('div', { class: 'segmented', style: { background: 'rgba(255,255,255,0.1)' } },
    options.map(([key, label]) => h('button', { type: 'button', style: { color: '#fff', background: key === value ? 'rgba(255,255,255,0.22)' : 'transparent' }, onclick: () => onPick(key) }, label)));

  const apply = h('button', { class: 'btn primary', disabled: todo > 0, onclick: async () => {
    const cells = {};
    for (const group of inspected.groups) for (const square of group.squares) cells[square] = group.color === 'w' ? assigned[group.id].toUpperCase() : assigned[group.id];
    const built = await window.coach.call('fen.build', { cells, userColor, turn, castling: 'auto' });
    if (!built.ok) { note.textContent = built.message; return; }
    editor.classList.remove('open');
    confirm({ fen: built.fen, color: userColor });
  } }, todo > 0 ? `Identify ${todo} more` : 'Start coaching');

  editor.append(h('div', { class: 'editor-card' },
    h('div', { class: 'title-2' }, 'Which pieces are these?'),
    h('div', { class: 'callout', style: { color: 'rgba(235,235,245,.65)' } }, 'I read your pieces and pre-selected what each group is. Fix anything that is wrong - one tap changes every piece in the group.'),
    h('div', { class: 'editor-cols' }, tiles,
      h('div', {},
        h('div', { class: 'overline', style: { marginBottom: '8px' } }, 'What I will use'), mini,
        h('div', { style: { display: 'flex', gap: '14px', marginTop: '14px', alignItems: 'center', flexWrap: 'wrap' } },
          h('div', {}, h('div', { class: 'caption', style: { marginBottom: '4px' } }, 'You are playing'), segment([['white', 'White'], ['black', 'Black']], userColor, (v) => { userColor = v; renderEditor(); })),
          h('div', {}, h('div', { class: 'caption', style: { marginBottom: '4px' } }, 'To move'), segment([['w', 'White'], ['b', 'Black']], turn, (v) => { turn = v; renderEditor(); }))),
        note)),
    h('div', { class: 'row', style: { display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '16px' } },
      h('button', { class: 'btn', onclick: () => { editor.classList.remove('open'); mode = 'error'; renderHud(); } }, 'Back'), apply)));
}

window.picker.onInspect((data) => {
  if (!data.ok) { mode = 'error'; lastResult = { joinable: false }; message = data.message || 'I could not read the pieces.'; renderHud(); return; }
  if (data.confident && data.position && !reviewMode) { // certain enough: no questions asked
    confirm({ fen: data.position.fen, color: data.position.userColor });
    return;
  }
  inspected = data;
  assigned = {};
  for (const group of data.groups) if (group.guess && group.guess !== '?') assigned[group.id] = group.guess;
  userColor = data.userColor || 'white';
  turn = (data.position && data.position.turn) || data.turn || (userColor === 'white' ? 'w' : 'b'); // the last-move highlight tells whose turn it is
  mode = 'idle';
  renderEditor();
});

// ------------------------------------------------------------ interaction
let drag = null;
stage.addEventListener('pointerdown', (e) => {
  if (!info || mode === 'learning' || mode === 'success') return;
  const px = fromDip(e.clientX, 'x');
  const py = fromDip(e.clientY, 'y');
  const corner = e.target.dataset?.corner;
  stage.setPointerCapture(e.pointerId);
  if (corner && rect) {
    const anchor = { nw: [rect.x + rect.size, rect.y + rect.size], ne: [rect.x, rect.y + rect.size], sw: [rect.x + rect.size, rect.y], se: [rect.x, rect.y] }[corner];
    drag = { kind: 'resize', anchor };
  } else if (rect && px >= rect.x && px <= rect.x + rect.size && py >= rect.y && py <= rect.y + rect.size) {
    drag = { kind: 'move', offset: [px - rect.x, py - rect.y] };
  } else {
    drag = { kind: 'draw', start: [px, py] };
  }
  if (mode === 'error') { mode = 'idle'; renderHud(); }
});
stage.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const px = fromDip(e.clientX, 'x');
  const py = fromDip(e.clientY, 'y');
  if (drag.kind === 'move') {
    const x = Math.min(Math.max(0, px - drag.offset[0]), info.width - rect.size);
    const y = Math.min(Math.max(0, py - drag.offset[1]), info.height - rect.size);
    rect = { ...rect, x, y };
    sx.set(x); sy.set(y);
  } else {
    const [ax, ay] = drag.kind === 'resize' ? drag.anchor : drag.start;
    const size = Math.max(40, Math.max(Math.abs(px - ax), Math.abs(py - ay)));
    const x = px < ax ? ax - size : ax;
    const y = py < ay ? ay - size : ay;
    rect = { x, y, size };
    frame.hidden = false;
    sx.set(x); sy.set(y); ss.set(size);
    mode = 'idle';
  }
});
stage.addEventListener('pointerup', () => { if (drag && drag.kind === 'draw' && rect) renderHud(); drag = null; });

document.addEventListener('keydown', (e) => {
  if (editor.classList.contains('open')) { if (e.key === 'Escape') { editor.classList.remove('open'); mode = 'error'; renderHud(); } return; }
  if (e.key === 'Enter') confirm();
  else if (e.key === 'Escape') window.picker.cancel();
  else if (e.key.toLowerCase() === 'r') window.picker.retake();
  else if (e.key === 'Tab' && info && info.candidates.length > 1) {
    e.preventDefault();
    candidateIndex = (candidateIndex + 1) % info.candidates.length;
    setRect(info.candidates[candidateIndex]);
  }
});

// --------------------------------------------------------------- messages
window.picker.onInit((data) => {
  reviewMode = Boolean(data.review);
  info = {
    width: data.width, height: data.height, candidates: data.candidates,
    scaleX: data.dipWidth / data.width, scaleY: data.dipHeight / data.height,
  };
  shot.src = data.image;
  mode = 'idle';
  const best = data.candidates.find((c) => c.confidence >= 0.5) || null;
  if (best) {
    candidateIndex = data.candidates.indexOf(best);
    // start a little larger and let the highlight settle onto the board
    sx.set(best.x - best.size * 0.04); sy.set(best.y - best.size * 0.04); ss.set(best.size * 1.08);
    setRect(best);
  } else {
    setRect(null);
    mode = 'none';
  }
  paint();
  renderHud();
});

window.picker.onResult((result) => {
  if (result.ok) {
    mode = 'success';
    const side = result.color === 'white' ? 'White' : 'Black';
    let detail = result.errors ? 'Ready. I’ll keep learning your pieces as you play.' : 'Your board is ready. I’ll learn your pieces as you play.';
    if (result.system && result.systemColor && result.systemColor !== result.color) {
      detail = `${result.system} is a ${result.systemColor} opening, so I’ll coach normally this game.`;
    }
    message = { title: `You’re playing ${side}`, detail };
    if (result.fen) message = { title: `Joined your game as ${side}`, detail: 'I read the position from your screen. If anything looks off, you can correct it from the session window.' };
    if (result.region) setRect({ x: result.region.x - (info.monitor?.left || 0), y: result.region.y - (info.monitor?.top || 0), size: result.region.size }, true);
  } else {
    mode = 'error';
    lastResult = result;
    message = result.message || 'Something went wrong.';
    if (result.size) setRect({ x: result.x, y: result.y, size: result.size });
    if (result.joinable) { startInspect(); return; } // a game in progress: read it instead of asking
  }
  renderHud();
});

addEventListener('resize', paint);
