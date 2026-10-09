// Applies a saved theme before the app starts, so the page never shows the
// other theme first. The key is THEME_STORAGE_KEY in ThemeService. A file
// rather than an inline script, so the Content-Security-Policy can allow
// scripts from this origin only.
try {
  var theme = localStorage.getItem('datapilot.theme');
  if (theme === 'light' || theme === 'dark') {
    document.documentElement.setAttribute('data-theme', theme);
  }
} catch (error) {
  // Storage is unavailable; the system preference applies.
}
