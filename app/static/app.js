// Light/dark: follows the device until toggled, then remembers the choice.
function toggleTheme() {
  const root = document.documentElement;
  const current = root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = current === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  try { localStorage.setItem('theme', next); } catch (e) {}
}

// Alpine components. Loaded before Alpine so they register on alpine:init.
document.addEventListener('alpine:init', () => {
  Alpine.data('tagInput', (initial, suggestions) => ({
    tags: initial,
    suggestions,
    draft: '',
    add(value) {
      const name = (value ?? this.draft).replace(/,/g, ' ').trim().replace(/\s+/g, ' ').toLowerCase();
      if (name && !this.tags.includes(name)) this.tags.push(name);
      this.draft = '';
    },
    remove(name) {
      this.tags = this.tags.filter((t) => t !== name);
    },
    onKey(e) {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        this.add();
      } else if (e.key === 'Backspace' && !this.draft) {
        this.tags.pop();
      }
    },
    get filtered() {
      const d = this.draft.trim().toLowerCase();
      return this.suggestions.filter((s) => !this.tags.includes(s) && (!d || s.includes(d))).slice(0, 12);
    },
  }));

  // Pattern editor: split pasted text into steps, edit them, and keep a draft on this device.
  Alpine.data('stepsEditor', (initial, draftKey) => ({
    steps: initial.map((s) => withKey(s)),
    expand: true,
    busy: false,
    message: '',
    draft: null,
    draftFound: false,
    draftAge: '',
    init() {
      const d = readJSON(draftKey);
      if (d && d.at) {
        this.draft = d;
        this.draftFound = true;
        this.draftAge = timeAgo(d.at);
      }
    },
    get json() {
      return JSON.stringify(this.steps.map(({ key, ...s }) => s));
    },
    async split() {
      const text = this.$refs.raw.value.trim();
      if (!text) { this.message = 'Paste the pattern text first.'; return; }
      if (this.steps.length && !confirm('Replace the current steps with a fresh split of the text?')) return;
      this.busy = true;
      this.message = '';
      try {
        const r = await fetch('/patterns/parse', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, expand: this.expand }),
        });
        if (!r.ok || r.redirected) throw new Error(r.status);
        const old = this.steps;
        // Keep ids where the same row lands in the same place, so checked-off progress survives a re-split.
        this.steps = (await r.json()).steps.map((s, i) =>
          withKey({ ...s, id: old[i] && old[i].label === s.label ? old[i].id : null }));
        this.message = this.steps.length ? '' : "Couldn't find any rows in that text. Add steps by hand below.";
        this.saveDraft();
      } catch (e) {
        this.message = "Couldn't split the text. Check the connection and try again.";
      }
      this.busy = false;
    },
    add(i) {
      this.steps.splice(i + 1, 0, withKey({ section: this.steps[i]?.section || '', label: '', text: '' }));
      this.saveDraft();
    },
    remove(i) { this.steps.splice(i, 1); this.saveDraft(); },
    move(i, d) {
      const j = i + d;
      if (j < 0 || j >= this.steps.length) return;
      [this.steps[i], this.steps[j]] = [this.steps[j], this.steps[i]];
      this.saveDraft();
    },
    saveDraft() {
      this.draftFound = false; // editing again means the newest work is what's on screen
      const fields = {};
      for (const el of this.$root.elements) {
        if (!el.name || el.type === 'file' || el.type === 'hidden') continue;
        if (el.type === 'radio' || el.type === 'checkbox') { if (el.checked) fields[el.name] = el.value; }
        else fields[el.name] = el.value;
      }
      writeJSON(draftKey, { fields, steps: this.steps, at: Date.now() });
    },
    restoreDraft() {
      const { fields = {}, steps = [] } = this.draft || {};
      for (const el of this.$root.elements) {
        if (!el.name || !(el.name in fields) || el.type === 'file' || el.type === 'hidden') continue;
        if (el.type === 'radio' || el.type === 'checkbox') el.checked = fields[el.name] === el.value;
        else el.value = fields[el.name];
      }
      this.steps = steps.map((s) => withKey(s));
      this.draftFound = false;
    },
    discardDraft() { removeKey(draftKey); this.draftFound = false; },
    clearDraft() { removeKey(draftKey); },
  }));

  // Follow-along: every tap saves to the server; changes queue on the device and retry if the connection drops.
  Alpine.data('follow', (s) => ({
    projectId: s.projectId,
    steps: s.steps,
    rows: s.rows,
    stitches: s.stitches,
    terms: s.terms,
    idx: 0,
    queue: [],
    inFlight: false,
    saveState: 'saved',
    retryMs: 2000,
    timer: null,
    keepAwake: false,
    lock: null,
    init() {
      this.terms = readText('terms') || this.terms;
      let currentId = s.current;
      const backup = readJSON(this.backupKey);
      if (backup && Array.isArray(backup.queue) && backup.queue.length) {
        // Changes that never reached the server last time: they're newer, so apply and resend them.
        this.queue = backup.queue;
        for (const body of this.queue) {
          if ('step_id' in body) { const st = this.steps.find((x) => x.id === body.step_id); if (st) st.done = body.done; }
          if ('current' in body) currentId = body.current;
          if ('rows' in body) this.rows = body.rows;
          if ('stitches' in body) this.stitches = body.stitches;
        }
      }
      let i = this.steps.findIndex((x) => x.id === currentId);
      if (i < 0) i = Math.max(0, this.steps.findIndex((x) => !x.done));
      this.idx = i;
      window.addEventListener('online', () => this.flush());
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') this.flush(true);
        else if (this.keepAwake) this.setAwake();
      });
      window.addEventListener('beforeunload', (e) => {
        if (this.queue.length) { this.flush(true); e.preventDefault(); }
      });
      if (this.queue.length) this.flush();
    },
    get backupKey() { return 'follow-' + this.projectId; },
    get step() { return this.steps[this.idx]; },
    get doneCount() { return this.steps.filter((x) => x.done).length; },
    get pct() { return this.steps.length ? Math.round((this.doneCount / this.steps.length) * 100) : 0; },
    get saveLabel() {
      return { saved: 'Saved ✓', saving: 'Saving…', offline: 'Offline: kept on this device, will retry' }[this.saveState];
    },
    enqueue(body) {
      const last = this.queue[this.queue.length - 1];
      const lastIsSending = this.inFlight && this.queue.length === 1;
      if (!('step_id' in body) && last && !('step_id' in last) && !lastIsSending) Object.assign(last, body);
      else this.queue.push({ ...body });
      this.writeBackup();
      this.flush();
    },
    writeBackup() {
      writeJSON(this.backupKey, { queue: this.queue, at: Date.now() });
    },
    async flush(leaving = false) {
      if (this.inFlight) return;
      if (!this.queue.length) { this.saveState = 'saved'; return; }
      this.inFlight = true;
      this.saveState = 'saving';
      try {
        const r = await fetch(`/projects/${this.projectId}/progress`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.queue[0]), keepalive: leaving, credentials: 'same-origin',
        });
        // A redirect means the session ended (sent to the profile picker): keep the change and retry later.
        if (r.redirected || (!r.ok && r.status !== 400 && r.status !== 404)) throw new Error(String(r.status));
        this.queue.shift(); // 400/404: the step was removed from the pattern, so there's nothing to save
        this.retryMs = 2000;
        this.writeBackup();
        this.inFlight = false;
        if (this.queue.length) return this.flush(leaving);
        this.saveState = 'saved';
      } catch (e) {
        this.inFlight = false;
        this.saveState = 'offline';
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.flush(), this.retryMs);
        this.retryMs = Math.min(this.retryMs * 2, 30000);
      }
    },
    go(i) {
      if (i < 0 || i >= this.steps.length) return;
      this.idx = i;
      this.enqueue({ current: this.step.id });
    },
    doneNext() {
      if (!this.step) return;
      if (!this.step.done) {
        this.step.done = true;
        this.enqueue({ step_id: this.step.id, done: true });
      }
      if (this.idx < this.steps.length - 1) this.go(this.idx + 1);
      if (navigator.vibrate) navigator.vibrate(15);
    },
    toggle(st) {
      st.done = !st.done;
      this.enqueue({ step_id: st.id, done: st.done });
    },
    bump(which, d) {
      this[which] = Math.max(0, this[which] + d);
      this.enqueue({ [which]: this[which] });
      if (navigator.vibrate) navigator.vibrate(10);
    },
    reset(which) {
      if (!this[which] || !confirm(`Reset the ${which} counter to 0?`)) return;
      this[which] = 0;
      this.enqueue({ [which]: 0 });
    },
    rememberTerms() { writeText('terms', this.terms); },
    async setAwake() {
      try {
        if (this.keepAwake) this.lock = await navigator.wakeLock.request('screen');
        else if (this.lock) { await this.lock.release(); this.lock = null; }
      } catch (e) { this.keepAwake = false; }
    },
    onKey(e) {
      if (e.target.closest('input, textarea, select')) return;
      if (e.key === ' ' || e.key === 'Enter') { if (e.target.tagName !== 'BUTTON') { e.preventDefault(); this.doneNext(); } }
      else if (e.key === 'ArrowRight') this.go(this.idx + 1);
      else if (e.key === 'ArrowLeft') this.go(this.idx - 1);
      else if (e.key === '+' || e.key === '=') this.bump('rows', 1);
      else if (e.key === '-') this.bump('rows', -1);
    },
  }));
});

// ---------- small helpers (storage can be blocked, e.g. private browsing) ----------
let keySeq = 0;
function withKey(s) {
  return { id: null, section: '', label: '', text: '', ...s, stitch_count: s.stitch_count ?? '', key: 'k' + keySeq++ };
}
function readText(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function writeText(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
function removeKey(key) { try { localStorage.removeItem(key); } catch (e) {} }
function readJSON(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; } }
function writeJSON(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {} }
function timeAgo(ms) {
  const mins = Math.round((Date.now() - ms) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} minute${mins === 1 ? '' : 's'} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  return new Date(ms).toLocaleDateString();
}
