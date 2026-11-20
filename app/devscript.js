// Development helper: drive the windows from a JSON script and take screenshots of the app's own windows.
//   set CHESSCOACH_SCRIPT=path\to\steps.json  then run  npm start
// A step is { wait: ms } | { window: "main"|"dock"|"picker"|"overlay", eval: "js" } | { window, shot: "file.png" } | { call: "cmd", args: {} }
const fs = require('fs');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function run(file, windows, backend, app, emit) {
  const steps = JSON.parse(fs.readFileSync(file, 'utf8'));
  const log = [];
  for (const step of steps) {
    try {
      if (step.wait) await sleep(step.wait);
      const win = windows()[step.window || 'main'];
      if (step.eval && win) { const result = await win.webContents.executeJavaScript(step.eval); if (step.log) log.push({ log: step.log, result }); }
      if (step.shot && !win) log.push({ error: 'no window', step });
      if (step.shot && win) fs.writeFileSync(step.shot, (await win.webContents.capturePage()).toPNG());
      if (step.winstate && win) log.push({ winstate: { visible: win.isVisible(), minimized: win.isMinimized(), bounds: win.getBounds(), focused: win.isFocused(), occluded: 'n/a' } });
      if (step.send && win) win.webContents.send(step.send.channel, step.send.data);
      if (step.emit && emit) emit(step.emit.event, step.emit.data);
      if (step.call) { const result = await backend.call(step.call, step.args || {}); if (step.log) log.push({ log: step.log, result }); }
    } catch (error) { log.push({ error: String(error), step }); }
  }
  fs.writeFileSync(process.env.CHESSCOACH_LOG || 'devscript.log.json', JSON.stringify(log, null, 2));
  app.quit();
}
module.exports = { run };
