/* ===========================================================================
 * أثَر — shared theme engine
 * One source of truth for light / dark / sepia across every page.
 *
 * Each page's CSS uses its own theme class prefix (reading: dark-mode/sepia-mode,
 * تثبيت: mz-*, مُكْث: wq-*, editor: ed-*). Rather than rewrite 4 large
 * stylesheets, this engine stores the choice under ONE localStorage key and
 * applies every page's class variant, so the theme follows the user everywhere.
 *
 * API:  AtharTheme.get() | .set('light'|'dark'|'sepia') | .cycle()
 * Bind: any element with [data-athar-theme="dark|sepia|light|cycle"] toggles it.
 * Event: document fires 'athar:theme' (detail = theme) on change.
 * ======================================================================== */
(function () {
  var KEY = 'quranApp_theme';
  var DARK  = ['dark-mode', 'mz-dark', 'wq-dark', 'ed-dark'];
  // editor (ed) supports light/dark only; everything else supports sepia too.
  var SEPIA = ['sepia-mode', 'mz-sepia', 'wq-sepia'];
  var ALL = DARK.concat(SEPIA);

  function get() {
    // migrate the editor's former standalone key on first run
    return localStorage.getItem(KEY) || localStorage.getItem('ed_theme') || 'light';
  }

  function apply(theme) {
    var b = document.body;
    if (!b) return;
    ALL.forEach(function (c) { b.classList.remove(c); });
    if (theme === 'dark')  DARK.forEach(function (c) { b.classList.add(c); });
    else if (theme === 'sepia') SEPIA.forEach(function (c) { b.classList.add(c); });
    b.setAttribute('data-theme', theme || 'light');
    document.documentElement.setAttribute('data-theme', theme || 'light');
  }

  function set(theme) {
    localStorage.setItem(KEY, theme);
    apply(theme);
    try { document.dispatchEvent(new CustomEvent('athar:theme', { detail: theme })); } catch (e) {}
  }

  function cycle() {
    var t = get();
    set(t === 'light' ? 'dark' : t === 'dark' ? 'sepia' : 'light');
  }

  function bind(root) {
    (root || document).querySelectorAll('[data-athar-theme]').forEach(function (el) {
      if (el.__atBound) return;
      el.__atBound = true;
      el.addEventListener('click', function (e) {
        e.preventDefault();
        var v = el.getAttribute('data-athar-theme');
        if (v === 'cycle' || !v) cycle(); else set(v);
      });
    });
  }

  window.AtharTheme = { get: get, set: set, apply: apply, cycle: cycle, bind: bind };

  // Apply as early as possible, then again once the DOM is ready.
  apply(get());
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { apply(get()); bind(); });
  } else {
    bind();
  }
})();
