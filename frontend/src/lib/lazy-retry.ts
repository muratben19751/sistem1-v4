// Yeni build sonrasi eski sekme tuzagi: acik sekme eski index'i tasirken chunk
// hash'leri degisir; daha once ziyaret edilmemis lazy sayfaya gecis eski dosyayi
// isteyip 404 alir ve sayfa hic acilmaz. Import patlarsa sayfayi BIR KEZ yenile
// (yeni index gelir); sessionStorage bayragi yenileme dongusunu engeller.
const FLAG = 'sistem1:chunk-reloaded';

export function lazyImport<T>(factory: () => Promise<T>): () => Promise<T> {
  return async () => {
    try {
      const mod = await factory();
      sessionStorage.removeItem(FLAG);
      return mod;
    } catch (err) {
      if (!sessionStorage.getItem(FLAG)) {
        sessionStorage.setItem(FLAG, '1');
        console.warn('[lazy] chunk yüklenemedi, sayfa yenileniyor (yeni build olabilir):', err);
        window.location.reload();
        // reload akisi devralir; Suspense fallback'te kalmasi icin bekleyen promise dondur
        return new Promise<T>(() => {});
      }
      throw err;
    }
  };
}
