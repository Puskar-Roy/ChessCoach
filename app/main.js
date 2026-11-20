// ChessCoach - desktop shell. Owns the windows and the Python coach; the pages only draw.
const { app, BrowserWindow, Menu, ipcMain, screen, nativeTheme } = require('electron');
const os = require('os');
const path = require('path');
const { PythonBackend } = require('./python');

const ROOT = path.resolve(__dirname, '..');
// Mica / acrylic window materials need Windows 11 (build 22621+); older systems get a solid window.
const HAS_MATERIAL = Number(os.release().split(".")[2]) >= 22621 && !process.env.CHESSCOACH_SOLID;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let backend;
let mainWin = null;
let dockWin = null;
let overlayWin = null;
let pickerWin = null;
let quitting = false;

// Anything unexpected is written to a log file and shown as a normal message, never as a crash.
function logProblem(label, error) {
  try {
    require('fs').appendFileSync(path.join(app.getPath('userData'), 'main.log'), `${new Date().toISOString()} ${label}: ${error && error.stack ? error.stack : error}
`);
  } catch { /* nothing more we can do */ }
  console.error(label, error);
}
process.on('uncaughtException', (error) => {
  logProblem('uncaughtException', error);
  broadcast('error', `Something went wrong: ${error.message}`);
});
process.on('unhandledRejection', (error) => {
  logProblem('unhandledRejection', error);
  broadcast('error', `Something went wrong: ${error && error.message ? error.message : error}`);
});

const live = { running: false, source: null, region: null, color: 'white' };
const cache = {}; // the latest value of every event, for windows that open later
let pickerWaiter = null;

// Keep animations running when the window is behind others (the dock panel lives next to a browser).
app.setAppUserModelId('com.chesscoach.app');
if (process.env.CHESSCOACH_PROFILE) app.setPath('userData', process.env.CHESSCOACH_PROFILE); // separate profile: lets tests run beside a real session
if (!app.requestSingleInstanceLock()) { app.quit(); }
app.on('second-instance', () => { const w = dockWin || mainWin; if (w) { if (w.isMinimized()) w.restore(); w.show(); w.focus(); } });

// ---------------------------------------------------------------- windows
function pagePath(name) { return path.join(__dirname, 'renderer', name); }

function baseOptions(extra) {
  return {
    show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: false, backgroundThrottling: false, offscreen: Boolean(process.env.CHESSCOACH_OFFSCREEN) },
    ...extra,
  };
}

function createMain() {
  mainWin = new BrowserWindow(baseOptions({
    width: 1280, height: 820, minWidth: 1020, minHeight: 700,
    title: 'ChessCoach',
    ...(HAS_MATERIAL ? { backgroundColor: '#00000000', backgroundMaterial: 'mica' } : { backgroundColor: nativeTheme.shouldUseDarkColors ? '#1c1c1e' : '#f5f5f7' }),
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#00000000', symbolColor: nativeTheme.shouldUseDarkColors ? '#ffffff' : '#1d1d1f', height: 44 },
  }));
  if (process.env.CHESSCOACH_DEBUG) mainWin.webContents.on('console-message', (details) => {
    console.log(`[renderer:${details.level}] ${details.message} (${details.sourceId}:${details.lineNumber})`);
  });
  mainWin.loadFile(pagePath('index.html'), { query: HAS_MATERIAL ? { material: '1' } : {} });
  if (process.env.CHESSCOACH_DEBUG) ['ready-to-show', 'show', 'hide', 'minimize', 'focus'].forEach((n) => mainWin.on(n, () => console.log('win', n)));
  mainWin.webContents.on('render-process-gone', (_e, details) => { logProblem('render-process-gone', details.reason); if (mainWin && !mainWin.isDestroyed()) mainWin.reload(); });
  mainWin.once('ready-to-show', () => mainWin.show());
  mainWin.on('closed', () => { mainWin = null; if (!quitting && !dockWin) app.quit(); });
  nativeTheme.on('updated', () => {
    if (mainWin) mainWin.setTitleBarOverlay({ color: '#00000000', symbolColor: nativeTheme.shouldUseDarkColors ? '#ffffff' : '#1d1d1f', height: 44 });
  });
}

function dipRect(region) {
  return screen.screenToDipRect(null, { x: region.x, y: region.y, width: region.size, height: region.size });
}

function createDock(region) {
  if (dockWin) return;
  const area = (region ? screen.getDisplayMatching(dipRect(region)) : screen.getPrimaryDisplay()).workArea;
  const width = 400;
  const height = Math.min(area.height - 24, 780);
  let x = area.x + area.width - width - 12;
  if (region) {
    const box = dipRect(region);
    const boardCentre = box.x + box.width / 2;
    if (boardCentre > area.x + area.width / 2) x = area.x + 12; // keep the panel on the side away from the board
  }
  dockWin = new BrowserWindow(baseOptions({
    x, y: area.y + 12, width, height, minWidth: 360, minHeight: 520,
    title: 'ChessCoach',
    ...(HAS_MATERIAL ? { backgroundMaterial: 'acrylic', backgroundColor: '#00000000' } : { backgroundColor: nativeTheme.shouldUseDarkColors ? '#1c1c1e' : '#f5f5f7' }),
    alwaysOnTop: true, frame: false, resizable: true, skipTaskbar: false, maximizable: false, fullscreenable: false,
  }));
  dockWin.setAlwaysOnTop(true, 'floating');
  dockWin.setContentProtection(true); // never read as part of the board being watched
  dockWin.loadFile(pagePath('index.html'), { query: HAS_MATERIAL ? { mode: 'dock', material: '1' } : { mode: 'dock' } });
  dockWin.once('ready-to-show', () => { dockWin.showInactive(); protect(dockWin); });
  dockWin.on('closed', () => { dockWin = null; if (live.running) stopSession(); });
}

// Keeps our own windows out of screen captures, so the board reader never sees the coach's arrow or panel.
// Windows only honours this once the window is on screen: asking earlier is silently ignored.
function protect(win) {
  const apply = () => { if (win && !win.isDestroyed()) win.setContentProtection(true); };
  apply();
  setTimeout(apply, 300);
  setTimeout(apply, 1500);
  win.on('show', apply);
}

function createOverlay(region) {
  if (overlayWin || !region) return;
  const box = dipRect(region);
  overlayWin = new BrowserWindow(baseOptions({
    x: box.x, y: box.y, width: box.width, height: box.height,
    transparent: true, frame: false, focusable: false, skipTaskbar: true, hasShadow: false, resizable: false, thickFrame: false,
    alwaysOnTop: true, backgroundColor: '#00000000',
  }));
  overlayWin.setIgnoreMouseEvents(true);
  overlayWin.setAlwaysOnTop(true, 'screen-saver');
  overlayWin.setContentProtection(true); // the board reader must not see our arrow
  overlayWin.loadFile(pagePath('overlay.html'));
  overlayWin.once('ready-to-show', () => { overlayWin.showInactive(); protect(overlayWin); pushOverlay(); });
  overlayWin.on('closed', () => { overlayWin = null; });
}

function moveOverlay(region) {
  if (!overlayWin || !region) return;
  overlayWin.setBounds(dipRect(region));
}

function pushOverlay() {
  if (!overlayWin) return;
  overlayWin.webContents.send('overlay:update', {
    arrow: cache.arrow ?? null,
    color: live.color,
    size: live.region ? dipRect(live.region).width : 0,
  });
}

function broadcast(event, data) {
  for (const win of [mainWin, dockWin]) {
    if (win && !win.isDestroyed()) win.webContents.send('py:event', { event, data });
  }
}

function teardownLive() {
  live.running = false;
  live.region = null;
  if (dockWin) { const w = dockWin; dockWin = null; w.destroy(); }
  if (overlayWin) { const w = overlayWin; overlayWin = null; w.destroy(); }
  if (!mainWin && !quitting) createMain();
  else if (mainWin) { mainWin.show(); mainWin.focus(); }
}

async function stopSession() {
  try { await backend.call('session.stop'); } catch { /* already stopped */ }
}

// ------------------------------------------------------------ board picker
function openPicker(snap) {
  const display = screen.getPrimaryDisplay();
  if (pickerWin) pickerWin.destroy();
  pickerWin = new BrowserWindow(baseOptions({
    x: display.bounds.x, y: display.bounds.y, width: display.bounds.width, height: display.bounds.height,
    frame: false, resizable: false, movable: false, skipTaskbar: true, alwaysOnTop: true, fullscreenable: false,
    backgroundColor: '#000000', hasShadow: false,
  }));
  pickerWin.setAlwaysOnTop(true, 'screen-saver');
  pickerWin.loadFile(pagePath('picker.html'));
  pickerWin.webContents.once('did-finish-load', () => {
    pickerWin.webContents.send('picker:init', { ...snap, scaleFactor: display.scaleFactor, dipWidth: display.bounds.width, dipHeight: display.bounds.height });
    pickerWin.show();
    protect(pickerWin); // the board is read while this window is open: it must not be part of what is read
    pickerWin.focus();
  });
  pickerWin.on('closed', () => { pickerWin = null; if (pickerWaiter) { pickerWaiter({ cancel: true }); pickerWaiter = null; } });
}

function waitForPicker() {
  return new Promise((resolve) => { pickerWaiter = resolve; });
}

function closePicker() {
  if (pickerWin) { const w = pickerWin; pickerWin = null; pickerWaiter = null; w.destroy(); }
}

ipcMain.on('picker:confirm', (_e, payload) => {
  if (pickerWaiter) { const done = pickerWaiter; pickerWaiter = null; done({ rect: { x: payload.x, y: payload.y, size: payload.size }, fen: payload.fen, color: payload.color }); }
});
ipcMain.on('picker:inspect', (_e, rect) => { if (pickerWaiter) { const done = pickerWaiter; pickerWaiter = null; done({ inspect: rect }); } });
ipcMain.on('picker:retake', () => { if (pickerWaiter) { const done = pickerWaiter; pickerWaiter = null; done({ retake: true }); } });
ipcMain.on('picker:cancel', () => { if (pickerWaiter) { const done = pickerWaiter; pickerWaiter = null; done({ cancel: true }); } });

async function captureBoard(options) {
  /** Shows the screen, lets the user confirm the board, learns it. Resolves { ok, color, region } or { cancelled }. */
  const cancel = async () => {
    await backend.call('capture.cancel').catch(() => {});
    closePicker();
    if (mainWin) mainWin.show();
    return { cancelled: true };
  };
  for (;;) {
    if (mainWin) mainWin.hide();
    await sleep(500); // let the page behind us repaint
    let snap;
    try { snap = await backend.call('capture.snapshot', { monitor: options.monitor || 1 }); }
    catch (error) { if (mainWin) mainWin.show(); throw error; }
    openPicker({ ...snap, review: Boolean(options.review) });
    for (;;) {
      const choice = await waitForPicker();
      if (choice.cancel) return cancel();
      if (choice.retake) { closePicker(); break; } // take a fresh screenshot
      if (choice.inspect) { // join a game in progress: read the pieces and let the user check them
        let inspected;
        try { inspected = await backend.call('capture.inspect', choice.inspect); } catch (error) { inspected = { ok: false, message: error.message }; }
        if (pickerWin) pickerWin.webContents.send('picker:inspect-result', inspected);
        continue;
      }
      let result;
      try { result = await backend.call('capture.confirm', { ...choice.rect, fen: choice.fen || options.fen || '', color: choice.color || options.color || 'white' }); }
      catch (error) { result = { ok: false, message: error.message }; }
      if (pickerWin) pickerWin.webContents.send('picker:result', { ...result, system: options.systemName || null, systemColor: options.systemColor || null });
      if (result.ok) { await sleep(1300); closePicker(); return result; }
      // not ok: the picker explains why and waits for another try
    }
  }
}

// --------------------------------------------------------------- sessions
async function startSession(options) {
  if (live.running) return { ok: false, error: 'A session is already running.' };
  const base = {
    voice: options.voice, arrows: options.arrows, engine_time: options.engineTime,
    system: options.system || '', level: options.level, strictness: options.strictness, fen: options.fen || '',
  };
  if (options.source !== 'screen') {
    await backend.call('session.start', { ...base, source: 'manual', color: options.color });
    return { ok: true };
  }
  live.options = { ...options, review: false };
  const result = await captureBoard(options);
  if (result.cancelled) return { ok: false, cancelled: true };
  base.fen = result.fen || base.fen;
  const systemMismatch = options.systemColor && options.systemColor !== result.color;
  await backend.call('session.start', {
    ...base, source: 'screen', color: result.color, system: systemMismatch ? '' : base.system,
  });
  return { ok: true, color: result.color, systemMismatch: Boolean(systemMismatch) };
}

function handleEvent(event, data) {
  if (process.env.CHESSCOACH_DEBUG) console.log('event', event);
  cache[event] = data;
  if (event === 'started') {
    live.running = true;
    live.source = data.source;
    live.color = data.color ? 'white' : 'black';
    live.region = data.region ? { x: data.region.left, y: data.region.top, size: data.region.width } : null;
    if (data.source === 'Screen') {
      if (mainWin) mainWin.hide();
      createDock(live.region);
      createOverlay(live.region);
    }
  } else if (event === 'region') {
    live.region = { x: data.x, y: data.y, size: data.size };
    moveOverlay(live.region);
    pushOverlay();
  } else if (event === 'arrow') {
    pushOverlay();
  } else if (event === 'stopped') {
    cache.arrow = null;
    teardownLive();
  }
  broadcast(event, data);
}

// -------------------------------------------------------------------- app
app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  backend = new PythonBackend(ROOT, app.getPath('userData'));
  backend.on('event', handleEvent);
  ipcMain.handle('py:call', (_e, cmd, args) => backend.call(cmd, args));
  ipcMain.handle('session:start', async (_e, options) => {
    try { return await startSession(options); } catch (error) { return { ok: false, error: error.message }; }
  });
  ipcMain.handle('session:stop', () => stopSession());
  ipcMain.handle('session:recheck', async () => { // joined mid-game and the pieces were read wrong: stop, then read them again with the editor open
    const options = live.options;
    if (!options) return { ok: false };
    await stopSession();
    for (let i = 0; i < 50 && live.running; i++) await sleep(100);
    try { return await startSession({ ...options, review: true }); } catch (error) { return { ok: false, error: error.message }; }
  });
  ipcMain.handle('window:expand', () => { if (mainWin) { mainWin.show(); mainWin.focus(); } });
  ipcMain.handle('app:theme', (_e, mode) => { nativeTheme.themeSource = mode; });
  ipcMain.handle('app:snapshot', () => ({ ...cache }));
  backend.on('exit', (code) => {
    if (quitting) return;
    broadcast('backend-exit', { code });
    if (live.running) teardownLive();
  });
  createMain();
  await backend.start();
  if (process.env.CHESSCOACH_SCRIPT) {
    setTimeout(() => require('./devscript').run(process.env.CHESSCOACH_SCRIPT, () => ({ main: mainWin, dock: dockWin, picker: pickerWin, overlay: overlayWin }), backend, app, handleEvent), 1500);
  }
  if (process.env.CHESSCOACH_PICKER_DEMO) {
    setTimeout(() => openPicker(JSON.parse(require('fs').readFileSync(process.env.CHESSCOACH_PICKER_DEMO, 'utf8'))), 1800);
  }

});

app.on('before-quit', () => {
  quitting = true;
  if (backend) backend.stop();
  setTimeout(() => app.exit(0), 2500); // never leave a half-closed process behind
});
app.on('window-all-closed', () => { if (!live.running) app.quit(); });
