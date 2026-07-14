// API base URL utilities

export const getApiBase = (): string => {
  // In deployed environments, use same-origin relative URLs (often proxied to backend)
  if (
    typeof window !== 'undefined' &&
    window.location.hostname !== 'localhost' &&
    window.location.hostname !== '127.0.0.1'
  ) {
    return '';
  }

  const configuredUrl =
    import.meta.env.VITE_BACKEND_URL || import.meta.env.VITE_API_URL;

  // Fallback for local Docker/dev when env vars aren't baked into the build
  return configuredUrl || 'http://localhost:8000';
};

export const getApiUrl = (path: string): string => {
  const base = getApiBase();
  return `${base}${path}`;
};