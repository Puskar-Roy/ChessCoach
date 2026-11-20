import { Board, BOARD_THEMES } from '../board.js';
import { h, icon } from '../dom.js';
import { Spring, reducedMotion, springCurve } from '../spring.js';
import { state, subscribe, systemById, update, updateSession, saveSettings } from '../store.js';
import { confirmSheet, gradeChip, segmented, toast } from '../ui.js';

const SAN = /(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8][+#]?|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?|\b[a-h][1-8][+#]?\b)/g;

export function formatAdvice(text) {
  const frag = document.createDocumentFragment();
  let last = 0;
  for (const match of text.matchAll(SAN)) {
    frag.append(text.slice(last, match.index));
    frag.append(h('span', { class: 'san' }, match[0]));
    last = match.index + match[0].length;
  }
  frag.append(text.slice(last));
  return frag;
}

export function rise(el) {
  if (reducedMotion()) { el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160 }); return; }
  el.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 560, easing: springCurve(0.42, 1).easing });
}

export function startOptions() {
  const s = state.settings;
  const system = systemById(s.system);
  return {
    source: s.source === 'Screen' ? 'screen' : 'manual',
    color: system ? system.color : (s.color || 'White').toLowerCase(),
    system: s.system || '',
    systemName: system?.name || null,
    systemColor: system?.color || null,
    level: s.level, strictness: s.strictness, voice: s.voice, arrows: s.arrows, engineTime: s.engine_time,
    fen: s.fen || '', monitor: s.monitor || 1,
  };
}

export async function beginSession() {
  if (state.session.running || state.session.starting) return;
  updateSession({ starting: true });
  const options = startOptions();
  try {
    const result = await window.coach.startSession(options);
    if (result.ok) {
      if (result.systemMismatch) toast(`Playing as ${result.color}. ${options.systemName} is a ${options.systemColor} system, so I'll coach normally this game.`, { duration: 7000 });
    } else if (result.error) toast(result.error, { kind: 'error', duration: 6000 });
  } catch (error) {
    toast(error.message, { kind: 'error' });
  }
  updateSession({ starting: false });
}

export async function endSession() {
  await window.coach.stopSession();
}

export function createPlayPage() {
  const board = new Board({ onMove: (uci) => window.coach.call('session.command', { kind: 'move_uci', data: { uci } }).catch(() => {}) });
  board.setTheme(state.settings.board_theme || 'Green');

  // ---- eval bar
  const evalFill = h('div', { class: 'eval-fill' });
  const evalLabel = h('span', { class: 'eval-label' }, '0.0');
  const evalBar = h('div', { class: 'eval', role: 'img', 'aria-label': 'Evaluation' }, evalFill, evalLabel);
  const evalSpring = new Spring(0.5, { response: 0.6, damping: 1 });
  evalSpring.on((v) => { evalFill.style.height = `${Math.round(v * 1000) / 10}%`; });

  const veil = h('div', { class: 'board-veil' });
  const boardRow = h('div', { class: 'board-row' }, evalBar, board.el);
  const stage = h('div', { class: 'stage' }, boardRow, veil);

  // ---- coach card
  const gradeSlot = h('div');
  const coachText = h('div', { class: 'coach-text' });
  const noticeEl = h('div', { class: 'notice', hidden: true });
  const joinedEl = h('div', { class: 'joined', hidden: true }, h('span', {}, 'Joined mid-game. Wrong side to move, or a piece misread?'),
    h('div', { class: 'joined-actions' },
      h('button', { class: 'btn', onclick: () => window.coach.call('session.command', { kind: 'flip_turn' }).catch(() => {}) }, 'Switch side'),
      h('button', { class: 'btn', onclick: () => window.coach.recheckPieces().catch(() => {}) }, 'Fix pieces')));
  const coach = h('section', { class: 'card coach', 'aria-live': 'polite' },
    h('div', { class: 'card-head' }, h('span', { class: 'overline' }, 'Coach')), gradeSlot, coachText, noticeEl, joinedEl);

  // ---- plan / engine lines
  const planTitle = h('span', { class: 'overline' }, 'Engine lines');
  const planProgress = h('div', { class: 'progress', hidden: true }, h('i'));
  const planBody = h('div');
  const plan = h('section', { class: 'card padded' }, h('div', { class: 'card-head' }, planTitle), planProgress, planBody);
  const progressSpring = new Spring(0, { response: 0.6, damping: 1 });
  progressSpring.on((v) => { planProgress.firstChild.style.width = `${v * 100}%`; });

  // ---- moves
  const movesEl = h('div', { class: 'moves' });
  const entry = h('input', { class: 'field', placeholder: 'Type a move, for example Nf3', 'aria-label': 'Type a move', style: { marginTop: '12px' } });
  entry.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !entry.value.trim()) return;
    window.coach.call('session.command', { kind: 'move_text', data: { text: entry.value.trim() } }).catch(() => {});
    entry.value = '';
  });
  const moves = h('section', { class: 'card padded' }, h('div', { class: 'card-head' }, h('span', { class: 'overline' }, 'Moves')), movesEl, entry);

  // ---- actions
  const send = (kind) => () => window.coach.call('session.command', { kind }).catch(() => {});
  const actions = h('div', { class: 'actions' },
    h('button', { class: 'btn', onclick: send('hint') }, icon('bulb'), 'Hint'),
    h('button', { class: 'btn', onclick: send('undo') }, icon('undo'), 'Undo'),
    h('button', { class: 'btn', onclick: send('new') }, icon('plus'), 'New'),
    h('button', { class: 'btn destructive', onclick: async () => {
      if (await confirmSheet({ title: 'Resign this game?', message: 'The game will end and be saved to your progress.', action: 'Resign', destructive: true })) send('resign')();
    } }, icon('flag'), 'Resign'));

  const side = h('aside', { class: 'side' }, coach, plan, moves, actions);
  const el = h('div', { class: 'play' }, stage, side);

  // ---- toolbar (shown in the window header while this page is active)
  const startButton = h('button', { class: 'btn primary', onclick: () => (state.session.running ? endSession() : beginSession()) });
  const sourceControl = segmented([['Manual', 'On this board'], ['Screen', 'From my screen']], state.settings.source || 'Manual', (key) => saveSettings({ source: key }));
  const sideControl = segmented([['White', 'White'], ['Black', 'Black']], state.settings.color || 'White', (key) => saveSettings({ color: key }));
  const systemChip = h('span', { class: 'chip accent', hidden: true });
  const turnChip = h('span', { class: 'chip' });
  const toolbar = h('div', { class: 'toolbar-group', style: { display: 'flex', alignItems: 'center', gap: '10px' } },
    sourceControl.el, sideControl.el, systemChip, h('span', { class: 'grow', style: { flex: 1 } }), turnChip, startButton);

  // ---- sizing
  const fit = () => {
    const { width, height } = stage.getBoundingClientRect();
    if (width < 100 || height < 100) return;
    board.setSize(Math.min(width - 14 - 12 - 8, height - 8));
    evalBar.style.height = `${board.size}px`;
  };
  new ResizeObserver(fit).observe(stage);

  // ---- rendering
  function renderVeil() {
    veil.replaceChildren();
    const running = state.session.running;
    veil.style.display = running ? 'none' : 'grid';
    if (running) return;
    const s = state.settings;
    const system = systemById(s.system);
    veil.append(h('div', { class: 'veil-card' },
      h('div', { class: 'title-2', style: { marginBottom: '6px' } }, state.session.starting ? 'Getting ready…' : 'Ready when you are'),
      h('div', { class: 'callout secondary', style: { marginBottom: '16px' } },
        s.source === 'Screen'
          ? 'I will look at your screen, find the board by myself and follow the game as it is played.'
          : 'Play on this board and I will coach every move.'),
      system ? h('div', { style: { marginBottom: '14px' } }, h('span', { class: 'chip accent' }, `Learning the ${system.name}`)) : null,
      h('button', { class: 'btn primary large', disabled: state.session.starting, onclick: beginSession }, icon(s.source === 'Screen' ? 'screen' : 'play'), s.source === 'Screen' ? 'Select my board' : 'Start playing')));
  }

  function renderToolbar() {
    const running = state.session.running;
    const s = state.settings;
    startButton.replaceChildren(running ? icon('x') : icon('play'), running ? 'End session' : (state.session.starting ? 'Starting…' : 'Start'));
    startButton.className = running ? 'btn' : 'btn primary';
    startButton.disabled = state.session.starting;
    sourceControl.disable(running || state.session.starting);
    sourceControl.set(s.source || 'Manual');
    const system = systemById(s.system);
    const fixedSide = running || Boolean(system) || s.source === 'Screen';
    sideControl.disable(fixedSide);
    sideControl.el.style.display = s.source === 'Screen' ? 'none' : '';
    sideControl.set(system ? (system.color === 'white' ? 'White' : 'Black') : (s.color || 'White'));
    systemChip.hidden = !system;
    systemChip.replaceChildren(icon('book', 13), system ? system.name : '');
    const game = state.game;
    turnChip.hidden = !running || !game;
    if (game) {
      turnChip.className = `chip ${game.over ? '' : game.user_turn ? 'accent' : ''}`;
      turnChip.textContent = game.over ? (game.result || 'Game over') : game.user_turn ? 'Your move' : 'Opponent’s move';
    }
  }

  function renderGame() {
    const game = state.game;
    const running = state.session.running;
    const manual = state.session.source === 'Manual' || !state.session.source;
    board.setInteractive(running && manual && !(game && game.over));
    const color = game ? (game.user_color ? 'white' : 'black') : ((state.settings.color || 'White').toLowerCase());
    board.setOrientation(running || game ? color : (systemById(state.settings.system)?.color || color));
    if (game) {
      const checked = game.check ? findKing(game.fen) : null;
      board.setPosition(game.fen, { last: game.last, legal: game.legal || {}, check: checked });
      if (game.eval) {
        const white = 1 / (1 + Math.exp(-game.eval.cp / 260));
        evalSpring.to(color === 'white' ? white : 1 - white);
        evalLabel.textContent = game.eval.mate ? `M${Math.abs(game.eval.mate)}` : `${game.eval.cp > 0 ? '+' : ''}${(game.eval.cp / 100).toFixed(1)}`;
        evalLabel.style.bottom = color === 'white' ? '6px' : 'auto';
        evalLabel.style.top = color === 'white' ? 'auto' : '6px';
        evalLabel.style.color = (color === 'white' ? white >= 0.5 : white < 0.5) ? 'var(--eval-dark)' : 'var(--eval-light)';
      }
      renderMoves(game.sans);
    } else {
      board.setPosition('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', { animate: false });
      movesEl.replaceChildren(h('div', { class: 'secondary callout', style: { gridColumn: '1 / -1' } }, 'No moves yet.'));
    }
  }

  function renderMoves(sans) {
    movesEl.replaceChildren();
    if (!sans.length) { movesEl.append(h('div', { class: 'secondary callout', style: { gridColumn: '1 / -1' } }, 'No moves yet.')); return; }
    for (let i = 0; i < sans.length; i += 2) {
      movesEl.append(h('span', { class: 'n' }, `${i / 2 + 1}.`),
        h('span', { class: `m${i === sans.length - 1 ? ' last' : ''}` }, sans[i]),
        h('span', { class: `m${i + 1 === sans.length - 1 ? ' last' : ''}` }, sans[i + 1] || ''));
    }
    movesEl.scrollTop = movesEl.scrollHeight;
  }

  let shownAdvice;  // undefined until the first render, so the empty state is drawn
  function renderAdvice() {
    const advice = state.advice;
    if (advice === shownAdvice) return;
    shownAdvice = advice;
    gradeSlot.replaceChildren();
    if (!advice) {
      coachText.textContent = state.session.running ? 'Thinking…' : 'Choose how you want to play, then press Start. I will explain every move.';
      renderPlan(null);
      return;
    }
    const chip = gradeChip(advice.grade);
    if (chip) gradeSlot.append(h('div', { class: 'grade' }, chip));
    coachText.replaceChildren(formatAdvice(advice.text));
    rise(coachText);
    renderPlan(advice);
  }

  function renderPlan(advice) {
    planBody.replaceChildren();
    if (advice && advice.plan && advice.plan.length) {
      planTitle.textContent = advice.plan_title || 'Your plan';
      planProgress.hidden = !(advice.phase === 'opening' && advice.progress);
      if (advice.progress) progressSpring.to(advice.progress[0] / Math.max(1, advice.progress[1]));
      planBody.append(h('ul', { class: 'plan-list' }, advice.plan.map((item) => h('li', {}, item))));
      return;
    }
    planProgress.hidden = true;
    const system = systemById(state.settings.system);
    if (system && !state.session.running) {
      planTitle.textContent = `${system.name} - key ideas`;
      planBody.append(h('ul', { class: 'plan-list' }, system.ideas.map((item) => h('li', {}, item))));
      return;
    }
    planTitle.textContent = 'Engine lines';
    if (advice && advice.lines && advice.lines.length) {
      planBody.append(h('div', { class: 'lines' }, advice.lines.map((line) =>
        h('div', { class: 'row' }, h('b', {}, line.san), h('span', { style: { color: line.cp >= 100 ? 'var(--green)' : line.cp <= -100 ? 'var(--red)' : 'var(--label-2)' } }, line.score), h('span', { class: 'secondary' }, line.pv)))));
    } else {
      planBody.append(h('div', { class: 'callout secondary' }, state.session.running ? 'Shown when it is your turn.' : 'The engine’s best lines appear here during a game.'));
    }
  }

  let noticeTimer = null;
  let lastNotice = null;
  function renderNotice() {
    const notice = state.notice;
    if (!notice || notice === lastNotice) return;
    lastNotice = notice;
    clearTimeout(noticeTimer);
    if (!notice.text) { noticeEl.hidden = true; return; }
    noticeEl.hidden = false;
    noticeEl.textContent = notice.text;
    rise(noticeEl);
    noticeTimer = setTimeout(() => { noticeEl.hidden = true; }, 9000);
  }

  function render() {
    renderToolbar();
    renderVeil();
    renderGame();
    renderAdvice();
    renderNotice();
    joinedEl.hidden = !(state.session.running && state.session.joined);
    board.setArrow(state.settings.arrows === false ? null : state.arrow);
    board.setTheme(state.settings.board_theme || 'Green');
  }
  subscribe(render);
  render();
  requestAnimationFrame(fit);

  return { el, toolbar, board, title: 'Play' };
}

function findKing(fen) {
  // square of the king of the side to move, for the check highlight
  const [placement, turn] = fen.split(' ');
  const target = turn === 'w' ? 'K' : 'k';
  const rows = placement.split('/');
  for (let r = 0; r < 8; r++) {
    let file = 0;
    for (const ch of rows[r]) {
      if (/\d/.test(ch)) { file += Number(ch); continue; }
      if (ch === target) return 'abcdefgh'[file] + (8 - r);
      file += 1;
    }
  }
  return null;
}
