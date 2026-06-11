import { applyStaticAuthHeader } from './auth-token';

const BASE_URL = '/api';

function notifyAuthRequired() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('sistem1:auth-required'));
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  headers.set('Content-Type', 'application/json');
  applyStaticAuthHeader(headers);

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
      credentials: 'same-origin',
    });
  } catch (err) {
    // Sayfalardaki catch{} blokları hatayı yutuyor; en azından konsolda iz kalsın.
    console.warn(`[api] ${options?.method || 'GET'} ${path} ağ hatası:`, err);
    throw err;
  }
  if (res.status === 401) notifyAuthRequired();
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: res.statusText }));
    console.warn(`[api] ${options?.method || 'GET'} ${path} -> ${res.status}:`, error.error || res.statusText);
    throw new Error(error.error || res.statusText);
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};

export const authApi = {
  async login(token: string): Promise<void> {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) throw new Error('Unauthorized');
  },

  async logout(): Promise<void> {
    await fetch(`${BASE_URL}/auth/logout`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
    });
    notifyAuthRequired();
  },
};
