import { buildDock } from './dock.js';
import { h, icon, piece } from './dom.js';
import { createOpeningsPage } from './pages/openings.js';
import { createPlayPage } from './pages/play.js';
import { createProgressPage } from './pages/progress.js';
import { openSettings } from './settings.js';
import { Spring, installSpringEasing, reducedMotion, springCurve } from './spring.js';
import { state, subscribe, update, updateSession } from './store.js';
import { toast } from './ui.js';

const api = window.coach;

function injectSprite() {
  const doc = new DOMParser().parseFromString(api.asset('pieces.svg'), 'image/svg+xml');
  const svg = document.importNode(doc.documentElement, true);
  svg.setAttribute('style', 'display:none');
  svg.removeAttribute('width');
  svg.removeAttribute('height');
  document.body.prepend(svg);
}

function applyTheme() {
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

// ------------------------------------------------------------------ events
function wireEvents() {
  let noticeId = 0;
  api.onEvent((event, data) => {
    switch (event) {
      case 'started':
        update({ advice: null, arrow: null, game: null, watch: 'watching' });
        updateSession({
          running: true, starting: false, source: data.source, color: data.color ? 'white' : 'black', systemName: data.system, joined: Boolean(data.joined),
        });
        break;
      case 'state': update({ game: data }); break;
      case 'advice': update({ advice: data }); break;
      case 'arrow': update({ arrow: data }); break;
      case 'watch': update({ watch: data }); break;
      case 'notice': update({ notice: { text: data, id: ++noticeId } }); break;
      case 'error': toast(data, { kind: 'error', duration: 8000 }); break;
      case 'stopped':
        updateSession({ running: false, starting: false });
        update({ arrow: null, advice: null, watch: 'watching' });
        api.call('history.get').then((history) => update({ history })).catch(() => {});
        break;
      case 'backend-exit':
        update({ backendError: 'The coach engine stopped unexpectedly.' });
        break;
      default: break;
    }
  });
}

async function hydrate() {
  const hello = await api.call('hello');
  update({ settings: hello.settings, systems: hello.systems, history: hello.history, ready: true });
  api.setTheme((hello.settings.appearance || 'system').toLowerCase());
  const cached = await api.snapshot();
  if (cached.started) {
    updateSession({ running: true, source: cached.started.source, color: cached.started.color ? 'white' : 'black', systemName: cached.started.system, joined: Boolean(cached.started.joined) });
  }
  if (cached.state) update({ game: cached.state });
  if (cached.advice) update({ advice: cached.advice });
  if (cached.arrow !== undefined) update({ arrow: cached.arrow });
  if (cached.watch) update({ watch: cached.watch });
}

// ------------------------------------------------------------------ shell
function buildMain(root) {
  const navItems = [['play', 'Play', 'board'], ['openings', 'Openings', 'book'], ['progress', 'Progress', 'chart']];
  const pill = h('span', { class: 'nav-pill' });
  const nav = h('nav', { class: 'nav', 'aria-label': 'Sections' }, pill);
  const buttons = {};
  const pillY = new Spring(0, { response: 0.4, damping: 0.9 });
  pillY.on((v) => { pill.style.transform = `translateY(${v}px)`; });

  const statusDot = h('span', { class: 'status-dot' });
  const statusText = h('div', {}, h('div', { class: 'headline', style: { fontSize: '13px' } }, 'Ready'), h('div', { class: 'caption' }, 'Engine loaded'));
  const status = h('div', { class: 'status-card' }, statusDot, statusText);
  const settingsButton = h('button', { class: 'nav-item', onclick: openSettings }, icon('gear'), 'Settings');

  const sidebar = h('aside', { class: 'sidebar drag' },
    h('div', { class: 'brand no-drag' },
      h('div', { class: 'brand-mark' }, piece('wn')),
      h('div', {}, h('div', { class: 'brand-name' }, 'ChessCoach'), h('div', { class: 'brand-sub' }, 'Learn by playing'))),
    nav,
    h('div', { class: 'sidebar-foot no-drag' }, status, settingsButton));

  const toolbarTitle = h('div', { class: 'title-1' });
  const toolbarSlot = h('div', { style: { flex: 1, display: 'flex', alignItems: 'center', minWidth: 0 } });
  const toolbar = h('div', { class: 'toolbar drag' }, toolbarTitle, toolbarSlot);

  const pages = {
    play: createPlayPage(),
    openings: createOpeningsPage({ goPlay: () => go('play') }),
    progress: createProgressPage(),
  };
  const pageEls = {};
  const content = h('main', { class: 'content' }, toolbar);
  for (const [key] of navItems) {
    const el = h('section', { class: 'page', 'aria-hidden': 'true' }, pages[key].el);
    if (key === 'play') el.style.padding = '72px 26px 24px';
    pageEls[key] = el;
    content.append(el);
  }
  root.append(h('div', { class: 'app' }, sidebar, content));

  navItems.forEach(([key, label, iconName]) => {
    const button = h('button', { class: 'nav-item', onclick: () => go(key), 'aria-current': 'false' }, icon(iconName), label);
    buttons[key] = button;
    nav.append(button);
  });

  let current = null;
  function go(key, instant = false) {
    if (key === current) return;
    const previous = current;
    current = key;
    update({ page: key });
    Object.entries(buttons).forEach(([k, b]) => b.setAttribute('aria-current', k === key ? 'page' : 'false'));
    pillY.to(buttons[key].offsetTop, instant ? {} : undefined);
    if (instant) pillY.set(buttons[key].offsetTop);
    toolbarTitle.textContent = pages[key].title;
    toolbarSlot.replaceChildren(pages[key].toolbar);

    const order = navItems.map(([k]) => k);
    const direction = previous ? Math.sign(order.indexOf(key) - order.indexOf(previous)) || 1 : 0;
    const incoming = pageEls[key];
    const outgoing = previous ? pageEls[previous] : null;
    incoming.classList.add('active');
    incoming.setAttribute('aria-hidden', 'false');
    if (!instant && !reducedMotion() && outgoing) {
      const { easing } = springCurve(0.45, 1);
      incoming.animate([{ opacity: 0, transform: `translateX(${direction * 28}px)` }, { opacity: 1, transform: 'none' }], { duration: 560, easing });
      const out = outgoing.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: `translateX(${-direction * 28}px)` }], { duration: 220, easing: 'ease-in', fill: 'forwards' });
      out.onfinish = () => { out.cancel(); outgoing.classList.remove('active'); outgoing.setAttribute('aria-hidden', 'true'); };
    } else {
      incoming.animate([{ opacity: 0 }, { opacity: 1 }], { duration: instant ? 0 : 160 });
      if (outgoing) { outgoing.classList.remove('active'); outgoing.setAttribute('aria-hidden', 'true'); }
    }
  }

  function renderStatus() {
    const { running, source, starting } = state.session;
    statusDot.className = 'status-dot' + (running ? ' live' : starting ? ' warn' : '');
    const title = running ? (source === 'Screen' ? 'Watching your screen' : 'Game in progress') : starting ? 'Getting ready…' : 'Ready';
    statusText.firstChild.textContent = title;
    statusText.lastChild.textContent = running ? (state.session.systemName || 'Free play') : 'Engine loaded';
  }
  subscribe(renderStatus);
  renderStatus();

  go('play', true);
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === ',') { e.preventDefault(); openSettings(); }
    if (e.ctrlKey && /^[1-3]$/.test(e.key)) { e.preventDefault(); go(navItems[Number(e.key) - 1][0]); }
  });
}

// -------------------------------------------------------------------- boot
async function boot() {
  installSpringEasing();
  injectSprite();
  applyTheme();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  if (!new URLSearchParams(location.search).has('material')) document.documentElement.classList.add('no-material');
  wireEvents();
  try {
    await hydrate();
  } catch (error) {
    document.body.append(h('div', { class: 'empty', style: { height: '100vh' } }, h('div', { class: 'title-2' }, 'The coach engine could not start'), h('div', { class: 'callout' }, error.message)));
    return;
  }
  const root = document.getElementById('root');
  if (api.mode === 'dock') buildDock(root);
  else buildMain(root);
  subscribe((s) => {
    if (s.backendError && !document.getElementById('backend-error')) {
      document.body.append(h('div', { id: 'backend-error', class: 'scrim open', style: { display: 'grid', placeItems: 'center', opacity: 1 } },
        h('div', { class: 'veil-card' }, h('div', { class: 'title-2' }, 'The coach engine stopped'), h('div', { class: 'callout secondary', style: { margin: '6px 0 14px' } }, 'Please restart ChessCoach.'))));
    }
  });
}

boot();
