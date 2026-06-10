const STATIC_AUTH_TOKEN = (import.meta as any).env?.VITE_AUTH_TOKEN as string | undefined;

export function getStaticAuthToken(): string | undefined {
  const token = STATIC_AUTH_TOKEN?.trim();
  return token || undefined;
}

export function applyStaticAuthHeader(headers: Headers): void {
  const token = getStaticAuthToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
}
