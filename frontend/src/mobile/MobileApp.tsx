import { useEffect, useRef, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { wsClient } from '../lib/ws';
import MobileTopBar from './components/MobileTopBar';
import BottomNav from './components/BottomNav';
import MobileAlertDrawer from './components/MobileAlertDrawer';
import MobileOverview from './pages/MobileOverview';
import MobilePositions from './pages/MobilePositions';
import MobileTrade from './pages/MobileTrade';
import MobileBots from './pages/MobileBots';
import MobileAlerts from './pages/MobileAlerts';
import MobileBacktest from './pages/MobileBacktest';

export default function MobileApp() {
  // Alert ekrani varsayilan KAPALI; ust bardaki can butonuyla acilir (slide-over drawer).
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const openRef = useRef(false);

  useEffect(() => { openRef.current = alertsOpen; }, [alertsOpen]);
  useEffect(() => {
    const unsub = wsClient.on('alert:received', () => {
      if (!openRef.current) setUnread((n) => Math.min(99, n + 1));
    });
    return () => unsub();
  }, []);

  const openAlerts = () => { setUnread(0); setAlertsOpen(true); };

  return (
    <div className="flex flex-col h-[100dvh] overflow-hidden bg-ink-900 text-ink-100 font-mono">
      <MobileTopBar onOpenAlerts={openAlerts} alertUnread={unread} />
      <main className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
        <Routes>
          <Route path="/m" element={<MobileOverview />} />
          <Route path="/m/positions" element={<MobilePositions />} />
          <Route path="/m/trade" element={<MobileTrade />} />
          <Route path="/m/bots" element={<MobileBots />} />
          <Route path="/m/alerts" element={<MobileAlerts />} />
          <Route path="/m/backtest" element={<MobileBacktest />} />
          <Route path="/m/*" element={<Navigate to="/m" replace />} />
        </Routes>
      </main>
      <BottomNav />
      <MobileAlertDrawer open={alertsOpen} onClose={() => setAlertsOpen(false)} />
    </div>
  );
}
