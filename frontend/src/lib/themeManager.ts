export type AppTheme = 'light' | 'dark';

const STORAGE_KEY = 'app-theme';

export function applyTheme(theme: AppTheme): void {
  localStorage.setItem(STORAGE_KEY, theme);
  document.documentElement.classList.toggle('dark', theme === 'dark');
}

export function getStoredTheme(): AppTheme {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'dark' ? 'dark' : 'light';
}

export function initializeTheme(): void {
  applyTheme(getStoredTheme());
}
