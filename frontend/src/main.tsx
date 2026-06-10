import React, { Component, type ReactNode, type ErrorInfo } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

function isStaleChunkError(err: unknown): boolean {
  const msg = (err instanceof Error ? err.message : String(err)) || '';
  return /dynamically imported module|Importing a module script failed|Failed to fetch|ChunkLoadError/i.test(msg);
}

function reloadOnceForStaleChunk(): boolean {
  const KEY = 'stale-chunk-reload-at';
  const last = Number(sessionStorage.getItem(KEY) || '0');
  if (Date.now() - last < 10_000) return false;
  sessionStorage.setItem(KEY, String(Date.now()));
  window.location.reload();
  return true;
}

// Yeni deploy sonrasi eski oturumdaki kod-split chunk hash'leri degisir; bayat chunk yuklenemezse bir kez yenile.
window.addEventListener('vite:preloadError', (event) => {
  if (reloadOnceForStaleChunk()) event.preventDefault();
});

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('App crash:', error, info);
    if (isStaleChunkError(error)) reloadOnceForStaleChunk();
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, color: '#f87171', fontFamily: 'monospace', background: '#0a0a0a', minHeight: '100vh' }}>
          <h1 style={{ fontSize: 24, marginBottom: 16 }}>Uygulama Hatasi</h1>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#fbbf24' }}>{this.state.error.message}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#9ca3af', fontSize: 12, marginTop: 12 }}>{this.state.error.stack}</pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: 20, padding: '8px 16px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            Yeniden Yukle
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
