// Springs: motion that starts from where things are, carries velocity, and can be grabbed at any time.
// Two parameters: damping ratio (1 = no overshoot) and response (seconds).

const reducedQuery = matchMedia('(prefers-reduced-motion: reduce)');
export const reducedMotion = () => reducedQuery.matches;

const active = new Set();
let frame = 0;
let last = 0;

function tick(now) {
  const dt = Math.min(0.032, (now - last) / 1000 || 0.016);
  last = now;
  for (const spring of [...active]) spring._step(dt);
  frame = active.size ? requestAnimationFrame(tick) : 0;
}

function start(spring) {
  active.add(spring);
  if (!frame) { last = performance.now(); frame = requestAnimationFrame(tick); }
}

export class Spring {
  constructor(value = 0, { response = 0.4, damping = 1 } = {}) {
    this.value = value;
    this.target = value;
    this.velocity = 0;
    this.response = response;
    this.damping = damping;
    this.listeners = new Set();
    this.rest = 0.0005;
  }

  on(fn) { this.listeners.add(fn); fn(this.value, this); return () => this.listeners.delete(fn); }

  /** Re-target from the current on-screen value and velocity (never from the old target). */
  to(target, { velocity, response, damping } = {}) {
    if (response !== undefined) this.response = response;
    if (damping !== undefined) this.damping = damping;
    this.target = target;
    if (velocity !== undefined) this.velocity = velocity;
    if (reducedMotion()) { this.set(target); return this; }
    start(this);
    return this;
  }

  set(value) {
    this.value = this.target = value;
    this.velocity = 0;
    active.delete(this);
    this.listeners.forEach((fn) => fn(this.value, this));
  }

  get settled() { return !active.has(this); }

  _step(dt) {
    const omega = (2 * Math.PI) / Math.max(this.response, 0.05);
    const stiffness = omega * omega;
    const drag = 2 * this.damping * omega;
    // semi-implicit Euler in small slices keeps it stable at any frame rate
    const slices = Math.ceil(dt / 0.004);
    const h = dt / slices;
    for (let i = 0; i < slices; i++) {
      const force = -stiffness * (this.value - this.target) - drag * this.velocity;
      this.velocity += force * h;
      this.value += this.velocity * h;
    }
    const scale = Math.max(1, Math.abs(this.target));
    if (Math.abs(this.value - this.target) < this.rest * scale && Math.abs(this.velocity) < 0.02 * scale) {
      this.value = this.target;
      this.velocity = 0;
      active.delete(this);
    }
    this.listeners.forEach((fn) => fn(this.value, this));
  }
}

/** A 2D value made of two independent springs, so x and y never desync. */
export class Spring2 {
  constructor(x = 0, y = 0, options) {
    this.x = new Spring(x, options);
    this.y = new Spring(y, options);
  }
  on(fn) {
    const call = () => fn(this.x.value, this.y.value);
    const offs = [this.x.on(call), this.y.on(call)];
    return () => offs.forEach((off) => off());
  }
  to(x, y, { velocity = [undefined, undefined], ...options } = {}) {
    this.x.to(x, { velocity: velocity[0], ...options });
    this.y.to(y, { velocity: velocity[1], ...options });
  }
  set(x, y) { this.x.set(x); this.y.set(y); }
}

/** CSS `linear()` easing that traces a spring, for non-gesture transitions. */
export function springCurve(response = 0.4, damping = 0.9, samples = 48) {
  const omega = (2 * Math.PI) / response;
  const points = [];
  let x = 0;
  let v = 0;
  const total = response * 2.4;
  const dt = total / samples;
  for (let i = 0; i <= samples; i++) {
    points.push(Number(x.toFixed(4)));
    for (let k = 0; k < 8; k++) {
      const force = -omega * omega * (x - 1) - 2 * damping * omega * v;
      v += force * (dt / 8);
      x += v * (dt / 8);
    }
  }
  points[points.length - 1] = 1;
  return { easing: `linear(${points.join(', ')})`, duration: `${Math.round(total * 1000)}ms` };
}

/** Exponential-decay projection used for flicks (the formula Apple ships). */
export function project(velocity, rate = 0.998) {
  return ((velocity / 1000) * rate) / (1 - rate);
}

/** Tracks the last few pointer samples to get a release velocity. */
export class Velocity {
  constructor() { this.samples = []; }
  add(x, y) {
    const t = performance.now();
    this.samples.push({ x, y, t });
    while (this.samples.length > 6 || (this.samples.length > 1 && t - this.samples[0].t > 120)) this.samples.shift();
  }
  get() {
    if (this.samples.length < 2) return [0, 0];
    const a = this.samples[0];
    const b = this.samples[this.samples.length - 1];
    const dt = (b.t - a.t) / 1000;
    return dt > 0 ? [(b.x - a.x) / dt, (b.y - a.y) / dt] : [0, 0];
  }
}

/** Animate a numeric property with a spring: `driver(value)` is called every frame. */
export function drive(spring, driver) { return spring.on(driver); }

export function installSpringEasing() {
  const { easing, duration } = springCurve(0.42, 0.78);
  document.documentElement.style.setProperty('--spring', easing);
  document.documentElement.style.setProperty('--spring-dur', duration);
}
