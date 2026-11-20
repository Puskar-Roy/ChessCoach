// A transparent, click-through window laid exactly over the chess board on screen. It draws the
// suggested move. The window is hidden from screen capture, so the board reader never sees it.

import { Spring, reducedMotion } from './spring.js';

const ns = 'http://www.w3.org/2000/svg';
const svg = document.getElementById('art');
const FILES = 'abcdefgh';
const make = (tag, attrs = {}) => { const el = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v)); return el; };

const defs = make('defs');
const shadow = make('filter', { id: 'soft', x: '-30%', y: '-30%', width: '160%', height: '160%' });
shadow.append(make('feDropShadow', { dx: '0', dy: '0.04', stdDeviation: '0.08', 'flood-color': '#000', 'flood-opacity': '0.5' }));
defs.append(shadow);
const group = make('g', { filter: 'url(#soft)', opacity: '0' });
const fromBox = make('rect', { rx: '0.12', fill: 'rgba(48,209,88,0.30)', stroke: '#30d158', 'stroke-width': '0.07' });
const toBox = make('rect', { rx: '0.12', fill: 'rgba(10,132,255,0.28)', stroke: '#0a84ff', 'stroke-width': '0.07' });
const outline = make('path', { stroke: '#fff', 'stroke-width': '0.32', 'stroke-linecap': 'round', fill: 'none' });
const body = make('path', { stroke: '#0a84ff', 'stroke-width': '0.21', 'stroke-linecap': 'round', fill: 'none' });
const head = make('path', { fill: '#0a84ff', stroke: '#fff', 'stroke-width': '0.09', 'stroke-linejoin': 'round' });
group.append(fromBox, toBox, outline, body, head);
svg.append(defs, group);

const grow = new Spring(0, { response: 0.5, damping: 0.8 });
const fade = new Spring(0, { response: 0.25, damping: 1 });
let ends = null;
let orientation = 'white';

function cell(square) {
  const file = FILES.indexOf(square[0]);
  const rank = Number(square[1]) - 1;
  return orientation === 'white' ? [file, 7 - rank] : [7 - file, rank];
}

function draw() {
  if (!ends) return;
  const [a, b] = ends.map(cell);
  const sx = a[0] + 0.5; const sy = a[1] + 0.5; const ex = b[0] + 0.5; const ey = b[1] + 0.5;
  const length = Math.hypot(ex - sx, ey - sy) || 1;
  const ux = (ex - sx) / length; const uy = (ey - sy) / length;
  const g = Math.max(0, grow.value);
  const tip = [sx + ux * (length * g), sy + uy * (length * g)];
  const base = [tip[0] - ux * 0.5, tip[1] - uy * 0.5];
  const start = [sx + ux * 0.3, sy + uy * 0.3];
  const path = `M ${start[0]} ${start[1]} L ${base[0]} ${base[1]}`;
  body.setAttribute('d', path);
  outline.setAttribute('d', path);
  const nx = -uy; const ny = ux;
  head.setAttribute('d', `M ${tip[0]} ${tip[1]} L ${base[0] + nx * 0.3} ${base[1] + ny * 0.3} L ${base[0] - nx * 0.3} ${base[1] - ny * 0.3} Z`);
  fromBox.setAttribute('x', a[0] + 0.04); fromBox.setAttribute('y', a[1] + 0.04); fromBox.setAttribute('width', 0.92); fromBox.setAttribute('height', 0.92);
  toBox.setAttribute('x', b[0] + 0.04); toBox.setAttribute('y', b[1] + 0.04); toBox.setAttribute('width', 0.92); toBox.setAttribute('height', 0.92);
  group.setAttribute('opacity', String(Math.min(1, Math.max(0, fade.value))));
}
grow.on(draw);
fade.on(draw);

window.overlay.onUpdate(({ arrow, color }) => {
  orientation = color || 'white';
  if (!arrow) { fade.to(0); return; }
  ends = [arrow.slice(0, 2), arrow.slice(2, 4)];
  grow.set(reducedMotion() ? 1 : 0);
  grow.to(1);
  fade.to(1);
});
