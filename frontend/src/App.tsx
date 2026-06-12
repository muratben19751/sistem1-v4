import { Suspense, lazy, useState, useEffect, type FormEvent } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import Sidebar from './components/layout/Sidebar';
import Header from './components/layout/Header';
import Footer from './components/layout/Footer';
import CircuitBreakerBanner from './components/layout/CircuitBreakerBanner';
import { authApi } from './lib/api';
import { applyStaticAuthHeader } from './lib/auth-token';
import { useGlobalWiring } from './hooks/useGlobalWiring';
import { useIsPhone } from './hooks/useMediaQuery';
import MobileRedirect from './mobile/MobileRedirect';
import { Smartphone } from 'lucide-react';
import ChatBox from './components/ChatBox';
import { lazyImport } from './lib/lazy-retry';

const Dashboard = lazy(lazyImport(() => import('./pages/Dashboard')));
const Bot = lazy(lazyImport(() => import('./pages/Bot')));
const SettingsPage = lazy(lazyImport(() => import('./pages/SettingsPage')));
const TradeDetail = lazy(lazyImport(() => import('./pages/TradeDetail')));
const Charts = lazy(lazyImport(() => import('./pages/Charts')));
const Journal = lazy(lazyImport(() => import('./pages/Journal')));
const Backtest = lazy(lazyImport(() => import('./pages/Backtest')));
const OptimizerLab = lazy(lazyImport(() => import('./pages/OptimizerLab')));
const BotConfig = lazy(lazyImport(() => import('./pages/BotConfig')));
const BotOverview = lazy(lazyImport(() => import('./pages/BotOverview')));
const ReplicaCompare = lazy(lazyImport(() => import('./pages/ReplicaCompare')));
const LeanOracle = lazy(lazyImport(() => import('./pages/LeanOracle')));
const StrategyReport = lazy(lazyImport(() => import('./pages/StrategyReport')));
const MobileApp = lazy(lazyImport(() => import('./mobile/MobileApp')));

function AuthPrompt() {
  const [visible, setVisible] = useState(false);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const show = () => setVisible(true);
    window.addEventListener('sistem1:auth-required', show);
    const headers = new Headers();
    applyStaticAuthHeader(headers);
    fetch('/api/auth/status', { credentials: 'same-origin', headers })
      .then((res) => res.json())
      .then((status) => {
        if (!status?.authenticated) setVisible(true);
      })
      .catch(() => setVisible(true));
    return () => window.removeEventListener('sistem1:auth-required', show);
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      await authApi.login(token.trim());
      window.location.reload();
    } catch {
      setError('Token hatali');
      setSubmitting(false);
    }
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm border border-white/10 bg-ink-900 shadow-2xl p-5">
        <div className="text-[10px] tracking-[0.3em] uppercase text-demo mb-2">[ DEMO AUTH ]</div>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoFocus
          placeholder="AUTH_TOKEN"
          className="w-full h-10 bg-ink-800 border border-white/10 px-3 text-[12px] text-ink-100 outline-none focus:border-up"
        />
        {error && <div className="mt-2 text-[11px] text-down">{error}</div>}
        <button
          type="submit"
          disabled={submitting || token.trim().length === 0}
          className="mt-4 w-full h-9 bg-up/20 border border-up/40 text-up text-[11px] tracking-[0.18em] uppercase disabled:opacity-40"
        >
          {submitting ? 'Checking...' : 'Enter'}
        </button>
      </form>
    </div>
  );
}

function DesktopShell() {
  return (
    <div className="flex flex-col h-screen bg-ink-900 text-ink-100 font-mono">
      <Header />
      <CircuitBreakerBanner />
      <div className="flex flex-1 min-h-0">
        <Sidebar />
        <main className="flex-1 min-w-0 flex flex-col overflow-auto">
          <Suspense fallback={<div className="p-8 text-gray-500">Loading...</div>}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/bot" element={<Bot />} />
              <Route path="/analytics" element={<Navigate to="/bot" replace />} />
              <Route path="/charts" element={<Charts />} />
              <Route path="/trade/:id" element={<TradeDetail />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/journal" element={<Journal />} />
              <Route path="/backtest" element={<Backtest />} />
              <Route path="/optimizer-lab" element={<OptimizerLab />} />
              <Route path="/rules" element={<Navigate to="/rules-assignment" replace />} />
              <Route path="/bot-config" element={<BotConfig />} />
              <Route path="/rules-assignment" element={<Navigate to="/bot-config" replace />} />
              <Route path="/positions" element={<Navigate to="/journal" replace />} />
              <Route path="/optimizer" element={<Navigate to="/optimizer-lab" replace />} />
              <Route path="/trade-genius" element={<Navigate to="/" replace />} />
              <Route path="/bot-overview" element={<BotOverview />} />
              <Route path="/replica-compare" element={<ReplicaCompare />} />
              <Route path="/lean" element={<LeanOracle />} />
              <Route path="/strategy-report" element={<StrategyReport />} />
              <Route path="/learning" element={<Navigate to="/settings" replace />} />
              <Route path="/customization" element={<Navigate to="/settings" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
      <Footer />
      <ChatBox />
    </div>
  );
}

function MobileViewButton() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate('/m')}
      className="fixed bottom-3 right-3 z-[90] flex items-center gap-1.5 bg-ink-800 border border-white/15 text-ink-100 rounded-full px-3 py-2 text-[11px] shadow-lg"
    >
      <Smartphone size={14} /> Mobil görünüm
    </button>
  );
}

export default function App() {
  useGlobalWiring();
  const location = useLocation();
  const isPhone = useIsPhone();
  const isMobileRoute = location.pathname.startsWith('/m');

  return (
    <>
      <MobileRedirect />
      {isMobileRoute ? (
        <Suspense fallback={<div className="h-screen bg-ink-900 text-ink-500 font-mono flex items-center justify-center text-sm">Yükleniyor...</div>}>
          <MobileApp />
        </Suspense>
      ) : (
        <DesktopShell />
      )}
      {!isMobileRoute && isPhone && <MobileViewButton />}
      <AuthPrompt />
    </>
  );
}
