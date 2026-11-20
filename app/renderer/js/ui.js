// Shared UI pieces: toasts, sheets, segmented controls, switches.

import { h, icon } from './dom.js';
import { Spring, reducedMotion, springCurve } from './spring.js';

// ------------------------------------------------------------------ toasts
let toastHost;
export function toast(text, { duration = 4200, kind = 'info' } = {}) {
  if (!toastHost) { toastHost = h('div', { class: 'toast-host', role: 'status', 'aria-live': 'polite' }); document.body.append(toastHost); }
  const el = h('div', { class: 'toast' }, text);
  if (kind === 'error') el.style.color = 'var(--red)';
  toastHost.append(el);
  const { easing } = springCurve(0.45, 0.85);
  if (!reducedMotion()) el.animate([{ opacity: 0, transform: 'translateY(14px) scale(0.96)' }, { opacity: 1, transform: 'none' }], { duration: 520, easing });
  else el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160 });
  const close = () => {
    const out = el.animate([{ opacity: 1 }, { opacity: 0, transform: reducedMotion() ? 'none' : 'translateY(8px)' }], { duration: 200, easing: 'ease-in', fill: 'forwards' });
    out.onfinish = () => el.remove();
  };
  setTimeout(close, duration);
  return close;
}

// ------------------------------------------------------------------ sheets
let sheetOpen = null;
export function openSheet(build, { width } = {}) {
  if (sheetOpen) sheetOpen.close();
  const scrim = h('div', { class: 'scrim' });
  const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true' });
  if (width) sheet.style.width = `${width}px`;
  const api = { close: () => {}, el: sheet };
  sheet.append(build(api));
  document.body.append(scrim, sheet);
  scrim.classList.add('open');
  sheet.classList.add('open');

  const progress = new Spring(0, { response: 0.42, damping: 0.9 });
  const apply = (p) => {
    scrim.style.opacity = String(Math.min(1, Math.max(0, p)));
    sheet.style.opacity = String(Math.min(1, Math.max(0, p * 1.4)));
    const scale = 0.94 + 0.06 * p;
    const lift = (1 - p) * 26;
    sheet.style.transform = reducedMotion() ? 'translate(-50%, -50%)' : `translate(-50%, calc(-50% + ${lift}px)) scale(${scale})`;
  };
  progress.on(apply);
  progress.to(1);
  let closing = false;
  api.close = () => {
    if (closing) return;
    closing = true;
    document.removeEventListener('keydown', onKey);
    progress.to(0, { damping: 1, response: 0.3 });
    const finish = () => { if (progress.value < 0.02 || reducedMotion()) { scrim.remove(); sheet.remove(); sheetOpen = null; } else requestAnimationFrame(finish); };
    requestAnimationFrame(finish);
    scrim.classList.remove('open');
    sheet.classList.remove('open');
  };
  const onKey = (e) => { if (e.key === 'Escape') api.close(); };
  document.addEventListener('keydown', onKey);
  scrim.addEventListener('pointerdown', () => api.close());
  sheetOpen = api;
  return api;
}

export function confirmSheet({ title, message, action, destructive = false }) {
  return new Promise((resolve) => {
    openSheet((sheet) => {
      const done = (value) => { resolve(value); sheet.close(); };
      return h('div', { style: { padding: '24px 24px 20px' } },
        h('div', { class: 'title-2', style: { marginBottom: '6px' } }, title),
        h('div', { class: 'body secondary', style: { marginBottom: '20px' } }, message),
        h('div', { style: { display: 'flex', gap: '10px', justifyContent: 'flex-end' } },
          h('button', { class: 'btn', onclick: () => done(false) }, 'Cancel'),
          h('button', { class: `btn ${destructive ? 'destructive' : 'primary'}`, onclick: () => done(true) }, action)));
    }, { width: 420 });
  });
}

// --------------------------------------------------------------- segmented
/** A segmented control whose thumb slides on a spring and can be re-targeted mid-flight. */
export function segmented(options, value, onChange, { disabled = false } = {}) {
  const thumb = h('span', { class: 'thumb' });
  const buttons = options.map(([key, label]) => h('button', { type: 'button', 'aria-pressed': String(key === value), dataset: { key }, onclick: () => select(key, true) }, label));
  const el = h('div', { class: 'segmented', role: 'group', 'data-disabled': String(disabled) }, thumb, ...buttons);
  const x = new Spring(0, { response: 0.36, damping: 0.88 });
  const w = new Spring(0, { response: 0.36, damping: 0.88 });
  x.on((v) => { thumb.style.transform = `translateX(${v}px)`; });
  w.on((v) => { thumb.style.width = `${v}px`; });
  let current = value;
  function place(animate) {
    const target = buttons.find((b) => b.dataset.key === current);
    if (!target || !target.offsetWidth) return;
    if (animate) { x.to(target.offsetLeft); w.to(target.offsetWidth); } else { x.set(target.offsetLeft); w.set(target.offsetWidth); }
  }
  function select(key, notify) {
    current = key;
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.key === key)));
    place(true);
    if (notify) onChange?.(key);
  }
  const observer = new ResizeObserver(() => place(false));
  observer.observe(el);
  requestAnimationFrame(() => place(false));
  return {
    el,
    set(key) { if (key !== current) select(key, false); },
    disable(on) { el.dataset.disabled = String(on); },
  };
}

// ------------------------------------------------------------------ switch
export function toggle(checked, onChange) {
  const el = h('button', { class: 'switch', type: 'button', role: 'switch', 'aria-checked': String(Boolean(checked)) });
  el.addEventListener('click', () => {
    const next = el.getAttribute('aria-checked') !== 'true';
    el.setAttribute('aria-checked', String(next));
    onChange?.(next);
  });
  el.set = (value) => el.setAttribute('aria-checked', String(Boolean(value)));
  return el;
}

export function gradeChip(grade) {
  const map = {
    best: ['Excellent', 'green'], good: ['Good move', 'green'], playable: ['Playable', 'yellow'],
    mistake: ['Mistake', 'orange'], blunder: ['Blunder', 'red'],
  };
  const [label, colour] = map[grade] || [null, null];
  if (!label) return null;
  return h('span', { class: `chip ${colour}` }, h('span', { class: 'dot' }), label);
}

export { icon };
