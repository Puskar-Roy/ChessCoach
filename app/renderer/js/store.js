// One small observable store shared by every page.

const listeners = new Set();

export const state = {
  ready: false,
  backendError: null,
  settings: {},
  systems: [],
  history: [],
  page: 'play',
  mode: window.coach?.mode || 'main',
  session: { running: false, starting: false, source: null, color: 'white', systemName: null },
  game: null, // last "state" event: fen, last, sans, eval, stats, legal, ...
  advice: null,
  arrow: null,
  watch: 'watching',
  notice: null,
};

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function update(patch) {
  Object.assign(state, patch);
  listeners.forEach((fn) => fn(state, patch));
}

export function updateSession(patch) { update({ session: { ...state.session, ...patch } }); }

export function systemById(id) { return state.systems.find((s) => s.id === id) || null; }

export function saveSettings(patch) {
  Object.assign(state.settings, patch);
  window.coach.call('settings.save', patch).catch(() => {});
  listeners.forEach((fn) => fn(state, { settings: state.settings }));
}
