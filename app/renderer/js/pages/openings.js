import { h, icon } from '../dom.js';
import { Spring, reducedMotion, springCurve } from '../spring.js';
import { state, subscribe, saveSettings } from '../store.js';
import { segmented, toast } from '../ui.js';

const LEVEL_HELP = {
  Guided: 'I show the move on the board and explain why. Best for learning a new system.',
  Practice: 'I only give you the plan. Think first, press Hint to check your idea.',
  Test: 'No help until you ask. Afterwards I grade every move against the system.',
};
const STRICT = [['Stick to the system', 'Only override the system for a real blunder'], ['Balanced', 'Warn when a system move costs about a pawn'], ['Engine first', 'Prefer the engine unless the system move is close']];

export function createOpeningsPage({ goPlay }) {
  const levelHelp = h('div', { class: 'callout secondary', style: { marginTop: '10px' } }, LEVEL_HELP[state.settings.level || 'Guided']);
  const level = segmented([['Guided', 'Guided'], ['Practice', 'Practice'], ['Test', 'Test']], state.settings.level || 'Guided', (key) => {
    saveSettings({ level: key });
    levelHelp.textContent = LEVEL_HELP[key];
    if (state.session.running) window.coach.call('session.command', { kind: 'level', data: { level: key } }).catch(() => {});
  });
  const strictness = h('select', { class: 'field', style: { width: '220px' }, 'aria-label': 'Strictness' },
    STRICT.map(([name]) => h('option', { value: name }, name)));
  strictness.value = state.settings.strictness || 'Balanced';
  const strictHint = h('div', { class: 'caption' }, '');
  const showStrictHint = () => { strictHint.textContent = STRICT.find(([n]) => n === strictness.value)?.[1] || ''; };
  showStrictHint();
  strictness.addEventListener('change', () => {
    showStrictHint();
    saveSettings({ strictness: strictness.value });
    if (state.session.running) window.coach.call('session.command', { kind: 'strictness', data: { strictness: strictness.value } }).catch(() => {});
  });

  const controls = h('section', { class: 'card padded', style: { marginBottom: '16px' } },
    h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' } },
      h('div', {}, h('div', { class: 'headline' }, 'How should I teach?'), h('div', { class: 'caption' }, 'The coach follows your opening whatever the engine prefers.')),
      level.el),
    levelHelp,
    h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', marginTop: '14px', paddingTop: '14px', borderTop: '1px solid var(--separator)' } },
      h('div', {}, h('div', { class: 'headline' }, 'Strictness'), strictHint), strictness));

  const grid = h('div', { class: 'grid' });
  const el = h('div', {}, controls, grid);
  const toolbar = h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } });

  const cards = new Map();
  function build() {
    grid.replaceChildren();
    cards.clear();
    const free = { id: '', name: 'Free play', color: null, tagline: 'No opening to follow. The coach suggests the strongest move every time.', ideas: [] };
    for (const system of [free, ...state.systems]) {
      const check = h('span', { class: 'check' }, icon('check'));
      const badge = system.color ? h('span', { class: `side-badge ${system.color}`, title: `${system.color} opening` }) : null;
      const card = h('button', { class: 'card pressable system', type: 'button', 'aria-pressed': 'false', onclick: () => choose(system) },
        check,
        h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } }, badge, h('span', { class: 'name' }, system.name)),
        h('div', { class: 'callout secondary' }, system.tagline),
        system.ideas.length ? h('ul', { class: 'plan-list', style: { marginTop: '4px' } }, system.ideas.slice(0, 2).map((idea) => h('li', {}, idea))) : null,
        h('div', { style: { marginTop: 'auto', display: 'flex', gap: '6px', flexWrap: 'wrap' } },
          system.color ? h('span', { class: 'chip' }, `Play as ${system.color}`) : h('span', { class: 'chip' }, 'Any side'),
          system.lines ? h('span', { class: 'chip' }, `${system.lines.length} lines`) : null));
      const spring = new Spring(0, { response: 0.4, damping: 0.7 });
      spring.on((v) => { check.style.transform = `scale(${Math.max(0, v)})`; });
      cards.set(system.id, { card, spring });
      grid.append(card);
    }
    sync();
  }

  function sync() {
    const current = state.settings.system || '';
    for (const [id, { card, spring }] of cards) {
      const selected = id === current;
      card.classList.toggle('selected', selected);
      card.setAttribute('aria-pressed', String(selected));
      spring.to(selected ? 1 : 0);
    }
  }

  function choose(system) {
    const patch = { system: system.id };
    if (system.color) patch.color = system.color === 'white' ? 'White' : 'Black';
    saveSettings(patch);
    sync();
    toast(system.id ? `Learning the ${system.name}.` : 'Free play with the engine.');
    if (state.session.running) toast('Your choice applies from the next game.', { duration: 3600 });
    else setTimeout(goPlay, reducedMotion() ? 0 : 520);
  }

  let built = false;
  subscribe(() => { if (!built && state.systems.length) { built = true; build(); } else if (built) sync(); });
  if (state.systems.length) { built = true; build(); }
  return { el, toolbar, title: 'Openings' };
}
