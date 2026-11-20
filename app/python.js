// Starts the Python coach (bridge.py) and speaks to it: one JSON message per line over stdin/stdout.
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const { EventEmitter } = require('events');
const readline = require('readline');

class PythonBackend extends EventEmitter {
  constructor(root, dataDir, packaged = false) {
    super();
    this.root = root;
    this.packaged = packaged;
    this.dataDir = dataDir;
    this.next = 1;
    this.pending = new Map();
    this.proc = null;
    this.ready = null;
  }

  /** How to start the coach: the frozen backend of an installed app, or Python on a development checkout. */
  static command(root, packaged) {
    if (packaged) {
      const exe = path.join(process.resourcesPath, 'backend', 'chesscoach-backend.exe');
      return { file: exe, args: [], cwd: path.dirname(exe) };
    }
    const venv = path.join(root, '.venv', 'Scripts', 'python.exe');
    return { file: fs.existsSync(venv) ? venv : 'python', args: ['-u', 'bridge.py'], cwd: root };
  }

  start() {
    this.ready = new Promise((resolve) => { this._resolveReady = resolve; });
    const env = { ...process.env, CHESSCOACH_DATA: this.dataDir, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' };
    const { file, args, cwd } = PythonBackend.command(this.root, this.packaged);
    this.proc = spawn(file, args, { cwd, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    this.proc.on('error', (error) => { this.emit('exit', `cannot start: ${error.message}`); });
    readline.createInterface({ input: this.proc.stdout }).on('line', (line) => this._onLine(line));
    this.proc.stderr.on('data', (chunk) => process.stderr.write(chunk));
    this.proc.on('exit', (code) => {
      for (const { reject } of this.pending.values()) reject(new Error('The coach engine stopped.'));
      this.pending.clear();
      this.emit('exit', code);
    });
    return this.ready;
  }

  _onLine(line) {
    let message;
    try { message = JSON.parse(line); } catch { return; }
    if (message.event) {
      if (message.event === 'ready') this._resolveReady();
      this.emit('event', message.event, message.data);
      return;
    }
    const waiting = this.pending.get(message.id);
    if (!waiting) return;
    this.pending.delete(message.id);
    if (message.ok) waiting.resolve(message.data);
    else waiting.reject(new Error(message.error || 'Request failed'));
  }

  call(cmd, args = {}) {
    return new Promise((resolve, reject) => {
      const stdin = this.proc && this.proc.stdin;
      if (!this.proc || this.proc.killed || this.stopping || !stdin || !stdin.writable) { reject(new Error('The coach engine is not running.')); return; }
      const id = this.next++;
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ id, cmd, args }) + '\n');
    });
  }

  stop() {
    if (!this.proc) return;
    this.stopping = true; // no more requests: writing to a closed pipe would throw
    try { this.proc.stdin.end(); } catch { /* already closed */ }
    setTimeout(() => { try { this.proc.kill(); } catch { /* gone */ } }, 1500).unref();
  }
}

module.exports = { PythonBackend };
