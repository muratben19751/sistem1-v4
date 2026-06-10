import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Wallet, ArrowUpDown, Bot, Bell, FlaskConical } from 'lucide-react';

const TABS = [
  { to: '/m', end: true, icon: LayoutDashboard, label: 'Özet' },
  { to: '/m/positions', end: false, icon: Wallet, label: 'Pozisyon' },
  { to: '/m/trade', end: false, icon: ArrowUpDown, label: 'İşlem' },
  { to: '/m/bots', end: false, icon: Bot, label: 'Botlar' },
  { to: '/m/backtest', end: false, icon: FlaskConical, label: 'Backtest' },
  { to: '/m/alerts', end: false, icon: Bell, label: 'Alert' },
];

export default function BottomNav() {
  return (
    <nav className="shrink-0 bg-ink-900 border-t border-white/10 grid grid-cols-6 pb-[env(safe-area-inset-bottom)]">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            `flex flex-col items-center justify-center gap-0.5 min-h-[56px] text-[10px] transition-colors ${
              isActive ? 'text-up' : 'text-ink-400 active:text-ink-200'
            }`
          }
        >
          <t.icon size={20} />
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
