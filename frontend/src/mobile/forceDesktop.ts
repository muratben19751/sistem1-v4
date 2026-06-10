const KEY = 'sistem1:forceDesktop';

export function isForceDesktop(): boolean {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

export function setForceDesktop(): void {
  try {
    localStorage.setItem(KEY, '1');
  } catch {}
}

export function clearForceDesktop(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {}
}
