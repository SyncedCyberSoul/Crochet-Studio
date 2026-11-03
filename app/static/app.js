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
});
