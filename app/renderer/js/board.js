// The chessboard. Pieces are real elements driven by springs: they slide to new squares, can be
// grabbed mid-flight, follow the pointer 1:1 from the exact point you grabbed them, and keep your
// release velocity when you let go.

import { h, piece as pieceSvg } from './dom.js';
import { Spring2, Velocity, reducedMotion } from './spring.js';

const FILES = 'abcdefgh';
const THEMES = {
  Green: ['#eeeed2', '#769656'],
  Brown: ['#f0d9b5', '#b58863'],
  Blue: ['#dee3e6', '#8ca2ad'],
  Violet: ['#e9e1f7', '#8a6bd1'],
  Slate: ['#cfd4e2', '#59627f'],
};
export const BOARD_THEMES = THEMES;

export function parseFen(fen) {
  const map = new Map();
  const rows = fen.split(' ')[0].split('/');
  rows.forEach((row, i) => {
    let file = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) { file += Number(ch); continue; }
      const color = ch === ch.toUpperCase() ? 'w' : 'b';
      map.set(FILES[file] + (8 - i), color + ch.toLowerCase());
      file += 1;
    }
  });
  return map;
}

export class Board {
  constructor({ onMove } = {}) {
    this.onMove = onMove;
    this.size = 480;
    this.orientation = 'white';
    this.interactive = false;
    this.legal = {};
    this.pieces = new Map(); // square -> { el, key, spring, unsubscribe }
    this.last = null;
    this.arrowSpring = null;
    this.selected = null;
    this.drag = null;

    this.highlights = h('div', { class: 'layer' });
    this.dots = h('div', { class: 'layer' });
    this.pieceLayer = h('div', { class: 'layer', style: { pointerEvents: 'none' } });
    this.arrowLayer = h('svg', { class: 'layer arrow-layer', viewBox: '0 0 8 8' });
    this.coords = h('div', { class: 'layer' });
    this.el = h('div', { class: 'board', role: 'application', 'aria-label': 'Chessboard' },
      this.highlights, this.coords, this.dots, this.pieceLayer, this.arrowLayer);
    this._buildArrow();
    this.el.addEventListener('pointerdown', (e) => this._down(e));
    this.el.addEventListener('pointermove', (e) => this._move(e));
    this.el.addEventListener('pointerup', (e) => this._up(e));
    this.el.addEventListener('pointercancel', (e) => this._up(e, true));
  }

  // ------------------------------------------------------------ geometry
  get cell() { return this.size / 8; }
  cellOf(square) {
    const file = FILES.indexOf(square[0]);
    const rank = Number(square[1]) - 1;
    return this.orientation === 'white' ? { col: file, row: 7 - rank } : { col: 7 - file, row: rank };
  }
  squareAt(x, y) {
    const col = Math.floor(x / this.cell);
    const row = Math.floor(y / this.cell);
    if (col < 0 || col > 7 || row < 0 || row > 7) return null;
    const file = this.orientation === 'white' ? col : 7 - col;
    const rank = this.orientation === 'white' ? 7 - row : row;
    return FILES[file] + (rank + 1);
  }
  px(square) { const { col, row } = this.cellOf(square); return [col * this.cell, row * this.cell]; }

  // ------------------------------------------------------------ settings
  setSize(px) {
    this.size = Math.max(160, Math.floor(px / 8) * 8);
    this.el.style.width = this.el.style.height = `${this.size}px`;
    for (const [square, p] of this.pieces) { const [x, y] = this.px(square); p.spring.set(x, y); }
    this._renderCoords();
    this._renderHighlights();
    this._renderDots();
  }

  setTheme(name) {
    const [light, dark] = THEMES[name] || THEMES.Green;
    this.el.style.setProperty('--sq-light', light);
    this.el.style.setProperty('--sq-dark', dark);
  }

  setOrientation(color) {
    if (color === this.orientation) return;
    this.orientation = color;
    this.el.classList.toggle('flipped', color === 'black');
    this._renderCoords();
    for (const [square, p] of this.pieces) { const [x, y] = this.px(square); p.spring.to(x, y, { response: 0.5 }); }
    this._renderHighlights();
    this._renderDots();
    this._placeArrow();
  }

  setInteractive(on) {
    this.interactive = on;
    this._markDraggable();
  }

  // ------------------------------------------------------------ position
  setPosition(fen, { last = null, legal = {}, check = null, animate = true } = {}) {
    this.legal = legal;
    this.last = last ? [last.slice(0, 2), last.slice(2, 4)] : null;
    this.check = check;
    this.selected = null;
    this._renderDots();
    const next = parseFen(fen);
    const gone = [];
    const kept = new Map();
    for (const [square, p] of this.pieces) {
      if (next.get(square) === p.key) kept.set(square, p);
      else gone.push([square, p]);
    }
    const arrivals = [];
    for (const [square, key] of next) if (!kept.has(square)) arrivals.push([square, key]);

    // pair each piece that left a square with the nearest arrival of the same piece
    const moved = [];
    for (const [from, p] of gone) {
      let best = -1;
      let bestDistance = Infinity;
      arrivals.forEach(([to, key], i) => {
        if (key !== p.key) return;
        const a = this.cellOf(from);
        const b = this.cellOf(to);
        const distance = Math.hypot(a.col - b.col, a.row - b.row);
        if (distance < bestDistance) { bestDistance = distance; best = i; }
      });
      if (best >= 0) { const [to] = arrivals.splice(best, 1)[0]; moved.push([p, to]); }
      else this._remove(p, animate);
    }
    this.pieces = kept;
    for (const [p, to] of moved) { this.pieces.set(to, p); this._slide(p, to, animate); }
    for (const [square, key] of arrivals) this._add(square, key, animate);
    this._markDraggable();
    this._renderHighlights();
    this._placeArrow();
  }

  _add(square, key, animate) {
    const el = h('div', { class: 'piece' }, pieceSvg(key));
    const [x, y] = this.px(square);
    const spring = new Spring2(x, y, { response: 0.38, damping: 1 });
    const unsubscribe = spring.on((sx, sy) => { el.style.transform = `translate(${sx}px, ${sy}px)`; });
    this.pieceLayer.append(el);
    const record = { el, key, spring, unsubscribe };
    this.pieces.set(square, record);
    if (animate && !reducedMotion()) {
      el.animate([{ opacity: 0, transform: `translate(${x}px, ${y}px) scale(0.6)` }, { opacity: 1, transform: `translate(${x}px, ${y}px) scale(1)` }],
        { duration: 260, easing: 'cubic-bezier(.2,.9,.3,1.2)' });
    }
    return record;
  }

  _remove(record, animate) {
    record.unsubscribe();
    if (animate && !reducedMotion()) {
      const fade = record.el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 180, easing: 'ease-out', fill: 'forwards' });
      fade.onfinish = () => record.el.remove();
    } else record.el.remove();
  }

  _slide(record, to, animate) {
    const [x, y] = this.px(to);
    if (animate) record.spring.to(x, y, { response: 0.4, damping: 1 });
    else record.spring.set(x, y);
  }

  _markDraggable() {
    for (const [square, p] of this.pieces) {
      const can = this.interactive && Boolean(this.legal[square]);
      p.el.classList.toggle('draggable', false); // dragging is handled on the board, not per piece
      p.canMove = can;
    }
    this.el.style.cursor = this.interactive ? 'pointer' : 'default';
  }

  // ------------------------------------------------------------- drawing
  _renderCoords() {
    this.coords.replaceChildren();
    const letters = this.orientation === 'white' ? FILES : [...FILES].reverse().join('');
    const ranks = this.orientation === 'white' ? '87654321' : '12345678';
    const light = getComputedStyle(this.el).getPropertyValue('--sq-light');
    const dark = getComputedStyle(this.el).getPropertyValue('--sq-dark');
    const small = Math.max(9, Math.round(this.cell * 0.15));
    for (let i = 0; i < 8; i++) {
      const bottomIsLight = i % 2 === 1; // the square under each file letter (bottom row) is dark for even i
      this.coords.append(h('span', { class: 'coord', style: { left: `${(i + 1) * this.cell - small * 1.1}px`, top: `${this.size - small * 1.5}px`, fontSize: `${small}px`, color: bottomIsLight ? dark : light } }, letters[i]));
      const leftIsLight = i % 2 === 0;
      this.coords.append(h('span', { class: 'coord', style: { left: `${small * 0.4}px`, top: `${i * this.cell + small * 0.4}px`, fontSize: `${small}px`, color: leftIsLight ? dark : light } }, ranks[i]));
    }
  }

  _renderHighlights() {
    this.highlights.replaceChildren();
    const add = (square, cls) => {
      const { col, row } = this.cellOf(square);
      this.highlights.append(h('div', { class: `hl ${cls}`, style: { left: `${col * 12.5}%`, top: `${row * 12.5}%` } }));
    };
    if (this.last) this.last.forEach((sq) => add(sq, 'last'));
    if (this.check) add(this.check, 'check');
    if (this.selected) add(this.selected, 'selected');
    if (this.hover) add(this.hover, 'hover');
  }

  _renderDots() {
    this.dots.replaceChildren();
    if (!this.selected) return;
    for (const target of this.legal[this.selected] || []) {
      const { col, row } = this.cellOf(target);
      const capture = this.pieces.has(target);
      this.dots.append(h('div', { class: `hl dot${capture ? ' capture' : ''}`, style: { left: `${col * 12.5}%`, top: `${row * 12.5}%` } }));
    }
  }

  // --------------------------------------------------------------- arrow
  _buildArrow() {
    const ns = 'http://www.w3.org/2000/svg';
    const make = (tag, attrs) => { const el = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v)); return el; };
    const defs = make('defs', {});
    const filter = make('filter', { id: 'arrow-shadow', x: '-20%', y: '-20%', width: '140%', height: '140%' });
    filter.append(make('feDropShadow', { dx: '0', dy: '0.04', stdDeviation: '0.07', 'flood-color': '#000', 'flood-opacity': '0.45' }));
    defs.append(filter);
    this.arrowGroup = make('g', { filter: 'url(#arrow-shadow)', opacity: '0' });
    this.arrowOutline = make('path', { stroke: '#fff', 'stroke-width': '0.30', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', fill: 'none' });
    this.arrowBody = make('path', { stroke: 'var(--blue)', 'stroke-width': '0.20', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', fill: 'none' });
    this.arrowHead = make('path', { fill: 'var(--blue)', stroke: '#fff', 'stroke-width': '0.08', 'stroke-linejoin': 'round' });
    this.arrowGroup.append(this.arrowOutline, this.arrowBody, this.arrowHead);
    this.arrowLayer.append(defs, this.arrowGroup);
    this.arrowSpring = new Spring2(0, 0, { response: 0.5, damping: 0.8 });
    this.arrowGrow = this.arrowSpring.x; // 0..1 growth of the shaft
    this.arrowFade = this.arrowSpring.y; // 0..1 opacity
    this.arrowSpring.on(() => this._drawArrow());
  }

  setArrow(uci) {
    if ((uci || null) === (this.arrowUci || null)) return; // already showing it: do not restart the animation
    this.arrowUci = uci || null;
    this._placeArrow();
  }

  _placeArrow() {
    if (!this.arrowUci) {
      this.arrowFade.to(0, { response: 0.25, damping: 1 });
      return;
    }
    const from = this.arrowUci.slice(0, 2);
    const to = this.arrowUci.slice(2, 4);
    this.arrowEnds = [from, to];
    this.arrowGrow.set(reducedMotion() ? 1 : 0);
    this.arrowGrow.to(1, { response: 0.5, damping: 0.8 });
    this.arrowFade.to(1, { response: 0.2, damping: 1 });
  }

  _drawArrow() {
    if (!this.arrowEnds) return;
    const [from, to] = this.arrowEnds;
    const a = this.cellOf(from);
    const b = this.cellOf(to);
    const sx = a.col + 0.5; const sy = a.row + 0.5;
    const ex = b.col + 0.5; const ey = b.row + 0.5;
    const length = Math.hypot(ex - sx, ey - sy) || 1;
    const ux = (ex - sx) / length; const uy = (ey - sy) / length;
    const headLength = 0.52;
    const grow = Math.max(0, this.arrowGrow.value);
    const tip = [sx + ux * (length - 0.18) * grow + ux * 0.18 * grow, sy + uy * (length - 0.18) * grow + uy * 0.18 * grow];
    const start = [sx + ux * 0.28, sy + uy * 0.28];
    const base = [tip[0] - ux * headLength, tip[1] - uy * headLength];
    const path = `M ${start[0]} ${start[1]} L ${base[0]} ${base[1]}`;
    this.arrowBody.setAttribute('d', path);
    this.arrowOutline.setAttribute('d', path);
    const nx = -uy; const ny = ux;
    this.arrowHead.setAttribute('d', `M ${tip[0]} ${tip[1]} L ${base[0] + nx * 0.3} ${base[1] + ny * 0.3} L ${base[0] - nx * 0.3} ${base[1] - ny * 0.3} Z`);
    this.arrowGroup.setAttribute('opacity', String(Math.min(1, Math.max(0, this.arrowFade.value))));
  }

  // --------------------------------------------------------- interaction
  _local(event) {
    const rect = this.el.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  _down(event) {
    if (!this.interactive || event.button !== 0) return;
    const [x, y] = this._local(event);
    const square = this.squareAt(x, y);
    if (!square) return;
    // second tap on a highlighted target completes a tap-to-move
    if (this.selected && (this.legal[this.selected] || []).includes(square)) {
      this._commit(this.selected, square, null);
      return;
    }
    const record = this.pieces.get(square);
    if (record && record.canMove) {
      try { this.el.setPointerCapture(event.pointerId); } catch { /* synthetic or already released pointer */ }
      const [px, py] = this.px(square);
      this.drag = { square, record, grab: [x - px, y - py], start: [x, y], started: false, velocity: new Velocity() };
      this.selected = square; // feedback on press, not on release
      this._renderHighlights();
      this._renderDots();
    } else {
      this.selected = null;
      this._renderHighlights();
      this._renderDots();
    }
  }

  _move(event) {
    const d = this.drag;
    if (!d) return;
    const [x, y] = this._local(event);
    if (!d.started) {
      if (Math.hypot(x - d.start[0], y - d.start[1]) < 5) return; // hysteresis before a press becomes a drag
      d.started = true;
      d.record.el.classList.add('dragging');
    }
    d.velocity.add(x, y);
    const nx = Math.min(Math.max(x - d.grab[0], -this.cell * 0.4), this.size - this.cell * 0.6);
    const ny = Math.min(Math.max(y - d.grab[1], -this.cell * 0.4), this.size - this.cell * 0.6);
    d.record.spring.set(nx, ny); // 1:1 with the pointer, from the point that was grabbed
    const over = this.squareAt(x, y);
    const next = over && (this.legal[d.square] || []).includes(over) ? over : null;
    if (next !== this.hover) { this.hover = next; this._renderHighlights(); }
  }

  _up(event, cancelled = false) {
    const d = this.drag;
    if (!d) return;
    this.drag = null;
    this.hover = null;
    d.record.el.classList.remove('dragging');
    if (!d.started) { this._renderHighlights(); return; } // a tap: the piece stays selected and shows its moves
    const [x, y] = this._local(event);
    const target = cancelled ? null : this.squareAt(x, y);
    if (target && (this.legal[d.square] || []).includes(target)) {
      const [vx, vy] = d.velocity.get();
      this._commit(d.square, target, [vx, vy]);
    } else {
      const [ox, oy] = this.px(d.square);
      const [vx, vy] = d.velocity.get();
      d.record.spring.to(ox, oy, { velocity: [vx, vy], response: 0.38, damping: 0.8 });
      this.selected = null;
      this._renderHighlights();
      this._renderDots();
    }
  }

  _commit(from, to, velocity) {
    const record = this.pieces.get(from);
    if (!record) return;
    const captured = this.pieces.get(to);
    if (captured) { this.pieces.delete(to); this._remove(captured, true); }
    this.pieces.delete(from);
    this.pieces.set(to, record);
    const [x, y] = this.px(to);
    record.spring.to(x, y, { velocity: velocity ? [velocity[0], velocity[1]] : [undefined, undefined], response: 0.34, damping: velocity ? 0.85 : 1 });
    this.selected = null;
    this.last = [from, to];
    this._renderDots();
    this._renderHighlights();
    const promotion = record.key[1] === 'p' && (to[1] === '8' || to[1] === '1') ? 'q' : '';
    this.onMove?.(from + to + promotion);
  }
}
