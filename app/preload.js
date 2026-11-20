// The only door between the pages and the rest of the computer.
const { contextBridge, ipcRenderer } = require('electron');
const fs = require('fs');
const path = require('path');

const listeners = new Set();
ipcRenderer.on('py:event', (_event, payload) => listeners.forEach((fn) => fn(payload.event, payload.data)));

contextBridge.exposeInMainWorld('coach', {
  call: (cmd, args) => ipcRenderer.invoke('py:call', cmd, args),
  startSession: (options) => ipcRenderer.invoke('session:start', options),
  stopSession: () => ipcRenderer.invoke('session:stop'),
  recheckPieces: () => ipcRenderer.invoke('session:recheck'),
  expand: () => ipcRenderer.invoke('window:expand'),
  setTheme: (mode) => ipcRenderer.invoke('app:theme', mode),
  onEvent: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  asset: (name) => fs.readFileSync(path.join(__dirname, 'renderer', 'assets', name), 'utf8'),
  platform: process.platform,
  mode: new URLSearchParams(location.search).get('mode') || 'main',
  snapshot: () => ipcRenderer.invoke('app:snapshot'),
});

contextBridge.exposeInMainWorld('picker', {
  onInit: (fn) => ipcRenderer.on('picker:init', (_e, data) => fn(data)),
  onResult: (fn) => ipcRenderer.on('picker:result', (_e, data) => fn(data)),
  confirm: (payload) => ipcRenderer.send('picker:confirm', payload),
  inspect: (rect) => ipcRenderer.send('picker:inspect', rect),
  onInspect: (fn) => ipcRenderer.on('picker:inspect-result', (_e, data) => fn(data)),
  retake: () => ipcRenderer.send('picker:retake'),
  cancel: () => ipcRenderer.send('picker:cancel'),
});

contextBridge.exposeInMainWorld('overlay', {
  onUpdate: (fn) => ipcRenderer.on('overlay:update', (_e, data) => fn(data)),
});
