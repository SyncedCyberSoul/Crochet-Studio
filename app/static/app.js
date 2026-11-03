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
    async importLink() {
      const url = this.$refs.importUrl.value.trim();
      if (!url) { this.message = 'Paste the link to the pattern first.'; return; }
      this.busy = true;
      this.message = '';
      try {
        const r = await fetch('/patterns/import', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) { this.message = data.error || "Couldn't import that page."; return; }
        const set = (name, value) => { const el = this.$root.elements[name]; if (el && value && !el.value) el.value = value; };
        set('title', data.title);
        set('designer', data.designer);
        set('source_url', data.source_url);
        set('notes', data.notes);
        this.$refs.raw.value = data.text;
      } catch (e) {
        this.message = "Couldn't reach the page. Check the connection and try again.";
        return;
      } finally {
        this.busy = false;
      }
      await this.split();
      if (this.steps.length) this.message = `Imported ${this.steps.length} steps. Check them over, then save.`;
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
    // helpers
    glossary: s.glossary || [],
    timeSpent: s.timeSpent || 0,
    gaugeMissing: s.gaugeMissing,
    gaugeDismissed: false,
    // track: what she counts while working: 'rows' (one tap per row/round), 'repeats' ("(sc, inc) x6"), 'stitches'
    settings: { track: 'rows', breakMinutes: 0, markerEvery: 0, resetOnNext: true, rowOnNext: false, sound: true },
    repeats: s.repeats || 0,
    countCheck: null,
    lastCheck: { label: '', count: 0 }, // text stays put while the note fades out
    showCountHelp: false,
    toastText: '',
    tapMode: false,
    explained: null,
    breakDue: false,
    toast: '',
    toastTimer: null,
    sessionSeconds: 0,
    unsentSeconds: 0,
    sinceBreak: 0,
    lastActive: Date.now(),
    voiceSupported: !!(window.SpeechRecognition || window.webkitSpeechRecognition),
    voiceOn: false,
    recog: null,
    abbrRe: null,
    init() {
      this.terms = readText('terms') || this.terms;
      this.settings = { ...this.settings, ...(readJSON('follow-settings') || {}) };
      this.gaugeDismissed = readText('gauge-skip-' + this.projectId) === '1';
      this.buildGlossary();
      // Active time: counts while the page is open and she's touched it in the last 5 minutes (or voice is on).
      setInterval(() => this.tick(), 1000);
      ['pointerdown', 'keydown'].forEach((ev) => window.addEventListener(ev, () => { this.lastActive = Date.now(); }));
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
          if ('repeats' in body) this.repeats = body.repeats;
        }
      }
      let i = this.steps.findIndex((x) => x.id === currentId);
      if (i < 0) i = Math.max(0, this.steps.findIndex((x) => !x.done));
      this.idx = i;
      window.addEventListener('online', () => this.flush());
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') { this.sendTime(); this.flush(true); }
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
      if (!('step_id' in body) && last && !('step_id' in last) && !lastIsSending) {
        const seconds = (last.add_seconds || 0) + (body.add_seconds || 0); // time adds up; everything else is latest-wins
        Object.assign(last, body);
        if (seconds) last.add_seconds = seconds;
      } else this.queue.push({ ...body });
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
      const finishing = !this.step.done;
      const finished = this.step;
      if (finishing) {
        this.step.done = true;
        this.enqueue({ step_id: this.step.id, done: true });
        if (this.settings.rowOnNext) { this.rows += 1; this.enqueue({ rows: this.rows }); }
        // The real-world check: count once at the end of the row against the number in brackets.
        this.countCheck = finished.count ? { label: finished.label || 'That row', count: finished.count } : null;
        if (this.countCheck) this.lastCheck = this.countCheck;
        if (this.countCheck) setTimeout(() => { if (this.countCheck && this.countCheck.count === finished.count) this.countCheck = null; }, 9000);
      }
      if (this.idx < this.steps.length - 1) this.go(this.idx + 1);
      if (finishing && this.settings.resetOnNext) {
        if (this.stitches) { this.stitches = 0; this.enqueue({ stitches: 0 }); }
        if (this.repeats) { this.repeats = 0; this.enqueue({ repeats: 0 }); }
      }
      if (finishing && this.idx === this.steps.length - 1 && this.doneCount === this.steps.length) this.say('All done! Well done.');
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
      if (d <= 0) return;
      if (which === 'repeats' && this.repeatTarget && this.repeats === this.repeatTarget) {
        this.showToast(`All ${this.repeatTarget} repeats done${this.target ? `: you should have ${this.target} sts` : ''}.`);
        if (navigator.vibrate) navigator.vibrate([60, 60, 120]);
        if (this.settings.sound) chime();
        return;
      }
      if (which !== 'stitches') return;
      if (this.target && this.stitches === this.target) {
        this.showToast(`${this.target} stitches: that's the count for this step!`);
        if (navigator.vibrate) navigator.vibrate([60, 60, 120]);
        if (this.settings.sound) chime();
      } else if (this.settings.markerEvery && this.stitches % this.settings.markerEvery === 0) {
        this.showToast(`${this.stitches} stitches: place a marker`);
        if (navigator.vibrate) navigator.vibrate([40, 40, 40]);
      }
    },
    get target() { return (this.step && this.step.count) || 0; },
    // "(sc, inc) x6" / "[sc 2, inc] × 6" / "rep from * 5 times" → how many repeats, and what's repeated.
    get repeatInfo() {
      const text = (this.step && this.step.text[this.terms]) || '';
      const m = text.match(/([([][^)\]]{1,60}[)\]])\s*(?:x|×|\*)\s*(\d+)/i)
        || text.match(/()\b(?:x|×)\s*(\d+)\b/i) || text.match(/()\b(\d+)\s*(?:more\s+)?times\b/i);
      return m ? { what: m[1] || 'the repeat', times: Number(m[2]) } : null;
    },
    get repeatTarget() { return this.repeatInfo ? this.repeatInfo.times : 0; },
    get tapUnit() { return { rows: 'rows', repeats: 'repeats', stitches: 'stitches' }[this.settings.track] || 'rows'; },
    setTrack(mode) { this.settings.track = mode; this.saveSettings(); },
    frog() {
      // Rip back: un-check the last finished row and go back to it.
      let i = this.idx;
      if (!this.steps[i].done) i = Math.max(0, i - 1);
      const st = this.steps[i];
      if (!st) return;
      if (st.done) { st.done = false; this.enqueue({ step_id: st.id, done: false }); }
      if (this.settings.rowOnNext && this.rows) { this.rows -= 1; this.enqueue({ rows: this.rows }); }
      this.go(i);
      this.countCheck = null;
      this.showToast(`Frogged back to ${st.label || 'the previous step'}. It happens to everyone!`);
    },
    showToast(text) {
      this.toast = text;
      this.toastText = text;
      clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => { this.toast = ''; }, 3200);
    },
    saveSettings() { writeJSON('follow-settings', this.settings); },
    dismissGauge() { this.gaugeDismissed = true; writeText('gauge-skip-' + this.projectId, '1'); },

    // ----- active time + stretch reminders -----
    tick() {
      const active = document.visibilityState === 'visible' && (this.voiceOn || Date.now() - this.lastActive < 5 * 60000);
      if (!active || this.breakDue) return;
      this.sessionSeconds += 1;
      this.unsentSeconds += 1;
      this.sinceBreak += 1;
      if (this.unsentSeconds >= 60) this.sendTime();
      if (this.settings.breakMinutes && this.sinceBreak >= this.settings.breakMinutes * 60) {
        this.breakDue = true;
        if (navigator.vibrate) navigator.vibrate([100, 80, 100]);
        if (this.settings.sound) chime();
      }
    },
    sendTime() {
      if (!this.unsentSeconds) return;
      this.enqueue({ add_seconds: this.unsentSeconds });
      this.unsentSeconds = 0;
    },
    takeBreak() { this.breakDue = false; this.sinceBreak = 0; this.lastActive = Date.now(); },
    fmt(seconds) {
      const m = Math.round(seconds / 60);
      return m < 60 ? `${m} min` : `${Math.floor(m / 60)} hr${m % 60 ? ' ' + (m % 60) + ' min' : ''}`;
    },

    // ----- tap a stitch abbreviation to see what it means -----
    buildGlossary() {
      const words = new Set();
      for (const g of this.glossary) { words.add(g.us); words.add(g.uk); }
      const list = [...words].filter(Boolean).sort((a, b) => b.length - a.length).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
      this.abbrRe = list.length ? new RegExp(`(^|[^A-Za-z0-9-])(${list.join('|')})(?=$|[^A-Za-z0-9])`, 'gi') : null;
    },
    lookup(word) {
      const w = word.toLowerCase();
      const key = this.terms === 'uk' ? 'uk' : 'us';
      return this.glossary.find((g) => g[key].toLowerCase() === w) || this.glossary.find((g) => g.us.toLowerCase() === w || g.uk.toLowerCase() === w);
    },
    marked(text) {
      const safe = escapeHtml(text || '');
      if (!this.abbrRe) return safe;
      return safe.replace(this.abbrRe, (m, pre, word) => `${pre}<button type="button" class="abbr" data-abbr="${word}">${word}</button>`);
    },
    explain(e) {
      const btn = e.target.closest('.abbr');
      if (btn) this.explained = this.lookup(btn.dataset.abbr) || null;
    },

    // ----- hands-free voice -----
    toggleVoice() {
      if (this.voiceOn) { this.voiceOn = false; if (this.recog) this.recog.stop(); return; }
      const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
      const r = new Rec();
      r.continuous = true;
      r.interimResults = false;
      r.lang = 'en-US';
      r.onresult = (ev) => {
        const said = ev.results[ev.results.length - 1][0].transcript.toLowerCase().trim();
        this.lastActive = Date.now();
        this.command(said);
      };
      r.onerror = (ev) => {
        if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
          this.voiceOn = false;
          this.showToast('The microphone is blocked. Allow it in the browser to use hands-free.');
        }
      };
      r.onend = () => { if (this.voiceOn) { try { r.start(); } catch (err) {} } }; // keep listening
      this.recog = r;
      this.voiceOn = true;
      try { r.start(); this.showToast('Listening: say "next", "count", "back", "frog" or "read"'); } catch (err) { this.voiceOn = false; }
    },
    command(said) {
      const has = (...words) => words.some((w) => new RegExp(`\\b${w}\\b`).test(said));
      if (has('next', 'done', 'finished', 'check')) this.doneNext();
      else if (has('back', 'previous', 'go back')) this.go(this.idx - 1);
      else if (has('frog', 'rip')) this.frog();
      else if (has('undo', 'minus')) this.bump(has('stitch', 'stitches') ? 'stitches' : has('repeat') ? 'repeats' : this.tapUnit, -1);
      else if (has('stitch', 'stitches')) this.bump('stitches', 1);
      else if (has('repeat', 'repeats')) this.bump('repeats', 1);
      else if (has('row', 'round')) this.bump('rows', 1);
      else if (has('count', 'plus', 'add', 'one', 'tap')) this.bump(this.tapUnit, 1);
      else if (has('read', 'again', 'what')) this.say(this.step ? `${this.step.label || ''}. ${this.step.text[this.terms]}` : '');
      else return;
      this.showToast(`Heard "${said}"`);
    },
    say(text) {
      if (!text || !window.speechSynthesis) return;
      speechSynthesis.cancel();
      speechSynthesis.speak(new SpeechSynthesisUtterance(text.replace(/\bsc\b/gi, 'single crochet').replace(/\binc\b/gi, 'increase').replace(/\bdec\b/gi, 'decrease')));
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

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// A soft two-note chime (no sound file needed).
let audioCtx = null;
function chime() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    [660, 880].forEach((freq, i) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const t = audioCtx.currentTime + i * 0.16;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t);
      osc.stop(t + 0.4);
    });
  } catch (e) {}
}

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
