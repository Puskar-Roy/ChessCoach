import { BOARD_THEMES } from './board.js';
import { h, icon } from './dom.js';
import { state, saveSettings } from './store.js';
import { openSheet, segmented, toggle, toast } from './ui.js';

function row(label, hint, control) {
  return h('div', { class: 'setting' },
    h('div', {}, h('div', { class: 'label' }, label), hint ? h('div', { class: 'hint' }, hint) : null), control);
}

export function openSettings() {
  return openSheet((sheet) => {
    const s = state.settings;

    const appearance = segmented([['system', 'System'], ['light', 'Light'], ['dark', 'Dark']], (s.appearance || 'system').toLowerCase(), (key) => {
      saveSettings({ appearance: key });
      window.coach.setTheme(key);
    });

    const swatches = h('div', { class: 'swatches' }, Object.entries(BOARD_THEMES).map(([name, [light, dark]]) => {
      const button = h('button', { class: 'swatch', type: 'button', title: name, 'aria-label': `${name} board`, 'aria-pressed': String((s.board_theme || 'Green') === name),
        onclick: () => {
          saveSettings({ board_theme: name });
          swatches.querySelectorAll('.swatch').forEach((b) => b.setAttribute('aria-pressed', String(b === button)));
        } }, h('i', { style: { background: light } }), h('i', { style: { background: dark } }));
      return button;
    }));

    const voice = toggle(s.voice !== false, (on) => {
      saveSettings({ voice: on });
      if (state.session.running) window.coach.call('session.command', { kind: 'voice', data: { on } }).catch(() => {});
    });
    const arrows = toggle(s.arrows !== false, (on) => {
      saveSettings({ arrows: on });
      if (state.session.running) window.coach.call('session.command', { kind: 'arrows', data: { on } }).catch(() => {});
    });

    const timeLabel = h('span', { class: 'tnum secondary', style: { width: '40px', textAlign: 'right' } }, `${Number(s.engine_time || 0.6).toFixed(1)}s`);
    const slider = h('input', { type: 'range', min: '0.2', max: '3', step: '0.1', value: String(s.engine_time || 0.6), 'aria-label': 'Thinking time' });
    slider.addEventListener('input', () => {
      const seconds = Number(slider.value);
      timeLabel.textContent = `${seconds.toFixed(1)}s`;
      saveSettings({ engine_time: seconds });
      if (state.session.running) window.coach.call('session.command', { kind: 'time', data: { seconds } }).catch(() => {});
    });

    const monitor = h('select', { class: 'field', style: { width: '120px' }, 'aria-label': 'Monitor' }, [1, 2, 3, 4].map((n) => h('option', { value: String(n) }, `Screen ${n}`)));
    monitor.value = String(s.monitor || 1);
    monitor.addEventListener('change', () => saveSettings({ monitor: Number(monitor.value) }));

    const fen = h('input', { class: 'field', style: { width: '280px' }, placeholder: 'Standard start position', value: s.fen || '', 'aria-label': 'Custom start position' });
    const commitFen = () => {
      const value = fen.value.trim();
      if (value && value.split(' ').length < 2) { toast('That doesn’t look like a FEN position.', { kind: 'error' }); return; }
      saveSettings({ fen: value });
    };
    fen.addEventListener('change', commitFen);

    return h('div', {},
      h('div', { class: 'sheet-head' }, h('div', { class: 'title-2' }, 'Settings'), h('button', { class: 'btn primary', onclick: () => sheet.close() }, 'Done')),
      h('div', { class: 'overline', style: { margin: '4px 28px 8px' } }, 'Appearance'),
      h('div', { class: 'group' }, row('Theme', 'Follows Windows unless you choose', appearance.el), row('Board colours', null, swatches)),
      h('div', { class: 'overline', style: { margin: '4px 28px 8px' } }, 'Coach'),
      h('div', { class: 'group' },
        row('Spoken advice', 'The coach reads its advice aloud', voice),
        row('Move arrow', 'Draw the suggested move on the board', arrows),
        row('Thinking time', 'Longer is stronger but slower', h('div', { style: { display: 'flex', alignItems: 'center', gap: '10px' } }, slider, timeLabel))),
      h('div', { class: 'overline', style: { margin: '4px 28px 8px' } }, 'Games'),
      h('div', { class: 'group' },
        row('Screen to watch', 'Where your chess website is shown', monitor),
        row('Start position', 'Leave empty for a normal game. Use a FEN to join a game in progress.', fen)),
      h('div', { class: 'caption', style: { padding: '0 28px 22px' } },
        'Chess pieces by Colin M.L. Burnett (CC BY-SA 3.0), via cm-chessboard. Engine: Stockfish.'));
  }, { width: 600 });
}

export { icon };
