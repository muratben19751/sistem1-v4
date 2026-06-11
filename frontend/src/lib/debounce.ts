// Trailing debounce: WS olay patlamalarında (örn. 20 pozisyonun aynı anda
// kapanması) art arda gelen refresh çağrılarını tek çağrıda toplar.
export function debounce<T extends (...args: any[]) => void>(fn: T, waitMs: number): T & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const wrapped = ((...args: any[]) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, waitMs);
  }) as T & { cancel: () => void };
  wrapped.cancel = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };
  return wrapped;
}
