// The compact panel that sits beside your chess website while a screen game is live.
// It never shows a second board: your real board carries the arrow. It shows what to do and why.

import { h, icon } from './dom.js';
import { formatAdvice, rise } from './pages/play.js';
import { Spring } from './spring.js';
import { state, subscribe, systemById } from './store.js';
import { gradeChip, toast } from './ui.js';

const WATCH = {
  watching: ['green', 'Watching your board'],
  settling: ['yellow', 'Waiting for the board to settle'],
  unclear: ['red', 'Couldn’t read that change'],
  lost: ['red', 'I can’t see the board'],
};

export function buildDock(root) {
  const watchChip = h('span', { class: 'chip green' }, h('span', { class: 'dot' }), 'Watching your board');
  const endButton = h('button', { class: 'btn icon', title: 'End session', 'aria-label': 'End session', onclick: () => window.coach.stopSession() }, icon('x'));
  const expandButton = h('button', { class: 'btn icon', title: 'Open the full window', 'aria-label': 'Open the full window', onclick: () => window.coach.expand() }, icon('expand'));
  const head = h('div', { class: 'dock-head' }, watchChip, h('div', { style: { display: 'flex', gap: '6px' } }, expandButton, endButton));

  const evalFill = h('i');
  const evalSpring = new Spring(0.5, { response: 0.6, damping: 1 });
  evalSpring.on((v) => { evalFill.style.width = `${v * 100}%`; });
  const evalText = h('span', { class: 'tnum caption' }, 'Even');
  const turnChip = h('span', { class: 'chip' });
  const evalRow = h('div', { class: 'dock-eval' }, h('div', { class: 'bar-track' }, evalFill), evalText);

  const gradeSlot = h('div');
  const coachText = h('div', { class: 'coach-text' }, 'Making my move list…');
  const notice = h('div', { class: 'notice', hidden: true });
  const joinedEl = h('div', { class: 'joined', hidden: true }, h('span', {}, 'Joined mid-game. Misread?'),
    h('div', { class: 'joined-actions' },
      h('button', { class: 'btn', onclick: () => window.coach.call('session.command', { kind: 'flip_turn' }).catch(() => {}) }, 'Switch side'),
      h('button', { class: 'btn', onclick: () => window.coach.recheckPieces().catch(() => {}) }, 'Fix pieces')));
  const coach = h('section', { class: 'card coach' }, h('div', { class: 'card-head' }, h('span', { class: 'overline' }, 'Coach'), turnChip), gradeSlot, coachText, notice, joinedEl);

  const planTitle = h('span', { class: 'overline' }, 'Your plan');
  const planBody = h('div');
  const plan = h('section', { class: 'card padded' }, h('div', { class: 'card-head' }, planTitle), planBody);

  const entry = h('input', { class: 'field', placeholder: 'Move not detected? Type it, e.g. e5', 'aria-label': 'Type a move' });
  entry.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !entry.value.trim()) return;
    window.coach.call('session.command', { kind: 'move_text', data: { text: entry.value.trim() } }).catch(() => {});
    entry.value = '';
  });
  const send = (kind) => () => window.coach.call('session.command', { kind }).catch(() => {});
  const actions = h('div', { class: 'actions' },
    h('button', { class: 'btn', onclick: send('hint') }, icon('bulb'), 'Hint'),
    h('button', { class: 'btn', onclick: send('reread') }, icon('refresh'), 'Re-read'),
    h('button', { class: 'btn', onclick: send('new') }, icon('plus'), 'New'),
    h('button', { class: 'btn', onclick: send('undo') }, icon('undo'), 'Undo'));

  root.append(h('div', { class: 'dock' }, head, evalRow, coach, plan, h('div', { style: { flex: 1 } }), entry, actions));

  let shown = null;
  let lastNotice = null;
  let timer = null;
  function render() {
    const [colour, label] = WATCH[state.watch] || WATCH.watching;
    watchChip.className = `chip ${colour}`;
    watchChip.replaceChildren(h('span', { class: 'dot' }), label);

    const game = state.game;
    if (game) {
      turnChip.hidden = false;
      turnChip.className = `chip ${game.over ? '' : game.user_turn ? 'accent' : ''}`;
      turnChip.textContent = game.over ? (game.result || 'Game over') : game.user_turn ? 'Your move' : 'Opponent’s move';
      if (game.eval) {
        const white = 1 / (1 + Math.exp(-game.eval.cp / 260));
        const mine = game.user_color ? white : 1 - white;
        evalSpring.to(mine);
        const cp = game.user_color ? game.eval.cp : -game.eval.cp;
        evalText.textContent = game.eval.mate ? `Mate in ${Math.abs(game.eval.mate)}` : `You ${cp > 0 ? '+' : ''}${(cp / 100).toFixed(1)}`;
      }
    } else turnChip.hidden = true;

    const advice = state.advice;
    if (advice !== shown) {
      shown = advice;
      gradeSlot.replaceChildren();
      if (advice) {
        const chip = gradeChip(advice.grade);
        if (chip) gradeSlot.append(h('div', { class: 'grade' }, chip));
        coachText.replaceChildren(formatAdvice(advice.text));
        rise(coachText);
        planBody.replaceChildren();
        if (advice.plan && advice.plan.length) {
          planTitle.textContent = advice.plan_title || 'Your plan';
          planBody.append(h('ul', { class: 'plan-list' }, advice.plan.map((item) => h('li', {}, item))));
        } else if (advice.lines && advice.lines.length) {
          planTitle.textContent = 'Engine lines';
          planBody.append(h('div', { class: 'lines' }, advice.lines.map((line) =>
            h('div', { class: 'row' }, h('b', {}, line.san), h('span', {}, line.score), h('span', { class: 'secondary' }, line.pv)))));
        } else {
          planTitle.textContent = 'Engine lines';
          planBody.append(h('div', { class: 'callout secondary' }, 'Shown when it is your turn.'));
        }
      }
    }
    if (state.notice && state.notice !== lastNotice) {
      lastNotice = state.notice;
      clearTimeout(timer);
      notice.hidden = !state.notice.text;
      if (state.notice.text) {
        notice.textContent = state.notice.text;
        rise(notice);
        timer = setTimeout(() => { notice.hidden = true; }, 9000);
      }
    }
    joinedEl.hidden = !(state.session.running && state.session.joined);
    const system = systemById(state.settings.system);
    if (!advice && system) planBody.replaceChildren(h('ul', { class: 'plan-list' }, system.ideas.map((item) => h('li', {}, item))));
  }
  subscribe(render);
  render();
  return { toast };
}
