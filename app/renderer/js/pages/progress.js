import { h } from '../dom.js';
import { Spring } from '../spring.js';
import { state, subscribe, update } from '../store.js';
import { confirmSheet, toast } from '../ui.js';

const GRADES = [
  ['best', 'Excellent', 'var(--green)'], ['good', 'Good', '#86d96a'], ['playable', 'Playable', 'var(--yellow)'],
  ['mistake', 'Mistake', 'var(--orange)'], ['blunder', 'Blunder', 'var(--red)'],
];

export function createProgressPage() {
  const tiles = ['Games coached', 'Average accuracy', 'Moves graded', 'Best game'].map((label) => ({
    label, value: h('div', { class: 'value' }, '–'), hint: h('div', { class: 'caption' }, ''),
  }));
  const stats = h('div', { class: 'stats' }, tiles.map((t) => h('div', { class: 'card stat' }, h('div', { class: 'overline' }, t.label), t.value, t.hint)));
  const bars = h('div', { class: 'bars' });
  const list = h('div');
  const el = h('div', {}, stats,
    h('div', { class: 'two' },
      h('section', { class: 'card padded' }, h('div', { class: 'card-head' }, h('span', { class: 'overline' }, 'Move quality')), bars),
      h('section', { class: 'card padded' }, h('div', { class: 'card-head' }, h('span', { class: 'overline' }, 'Recent games')), list)));

  const toolbar = h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } },
    h('span', { style: { flex: 1 } }),
    h('button', { class: 'btn', onclick: async () => {
      const ok = await confirmSheet({
        title: 'Clear your game history?', message: 'This removes the games shown here. It cannot be undone.', action: 'Clear history', destructive: true,
      });
      if (!ok) return;
      await window.coach.call('history.clear');
      update({ history: [] });
      toast('History cleared.');
    } }, 'Clear history'));

  const springs = GRADES.map(() => new Spring(0, { response: 0.7, damping: 0.85 }));
  const barEls = GRADES.map(([, label, colour], i) => {
    const fill = h('i', { style: { background: colour, height: '4px' } });
    const count = h('b', {}, '0');
    springs[i].on((v) => { fill.style.height = `${Math.max(4, v)}px`; });
    return { count, node: h('div', { class: 'bar' }, count, fill, h('span', { class: 'caption' }, label)) };
  });
  barEls.forEach((b) => bars.append(b.node));

  function render() {
    const history = state.history || [];
    const counts = Object.fromEntries(GRADES.map(([k]) => [k, 0]));
    const accuracies = [];
    let moves = 0;
    for (const game of history) {
      for (const [k, v] of Object.entries(game.counts || {})) if (k in counts) { counts[k] += v; moves += v; }
      if (typeof game.accuracy === 'number') accuracies.push(game.accuracy);
    }
    tiles[0].value.textContent = String(history.length);
    tiles[0].hint.textContent = 'saved sessions';
    tiles[1].value.textContent = accuracies.length ? `${Math.round(accuracies.reduce((a, b) => a + b, 0) / accuracies.length)}%` : '–';
    tiles[1].hint.textContent = 'across all games';
    tiles[2].value.textContent = String(moves);
    tiles[2].hint.textContent = 'checked by the engine';
    tiles[3].value.textContent = accuracies.length ? `${Math.round(Math.max(...accuracies))}%` : '–';
    tiles[3].hint.textContent = 'highest accuracy';

    const peak = Math.max(1, ...Object.values(counts));
    GRADES.forEach(([k], i) => { barEls[i].count.textContent = String(counts[k]); springs[i].to((counts[k] / peak) * 170); });

    list.replaceChildren();
    if (!history.length) {
      list.append(h('div', { class: 'empty' }, h('div', { class: 'headline' }, 'No games yet'),
        h('div', { class: 'callout' }, 'Play a few moves and your progress will show up here.')));
      return;
    }
    for (const game of [...history].reverse().slice(0, 12)) {
      const acc = game.accuracy;
      const colour = acc >= 80 ? 'var(--green)' : acc >= 55 ? 'var(--yellow)' : 'var(--red)';
      const system = game.followed ? ` · in system ${game.followed.followed}/${game.followed.total}` : '';
      list.append(h('div', { class: 'game-row' },
        h('div', { class: 'acc', style: { color: colour } }, typeof acc === 'number' ? `${Math.round(acc)}%` : '–'),
        h('div', { style: { flex: 1, minWidth: 0 } },
          h('div', { class: 'headline' }, game.system || `As ${game.color}`),
          h('div', { class: 'caption' }, `${game.ts} · ${Math.ceil((game.plies || 0) / 2)} moves${system}`)),
        h('span', { class: 'chip' }, game.result || 'Unfinished')));
    }
  }
  subscribe(render);
  render();
  return { el, toolbar, title: 'Progress' };
}
