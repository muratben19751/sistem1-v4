import { useState, useRef, useEffect } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { LayoutDashboard, Bot, CandlestickChart, Settings, ChevronDown, Play, Square, ScrollText, Wrench, LayoutList, FlaskConical, Cpu, GitCompare, ShieldCheck } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { useUiStore, type BotStatus } from '../../store/ui-store';
import { api } from '../../lib/api';

const NAV_ITEMS = [
  { to: '/', icon: LayoutDashboard, label: 'Desk' },
  { to: '/bot', icon: Bot, label: 'Bot' },
  { to: '/bot-overview', icon: LayoutList, label: 'Bot Overview' },
  { to: '/journal', icon: ScrollText, label: 'Trades' },
  { to: '/backtest', icon: FlaskConical, label: 'Backtest' },
  { to: '/optimizer-lab', icon: Cpu, label: 'Optimizer Lab' },
  { to: '/charts', icon: CandlestickChart, label: 'Charts' },
  { to: '/bot-config', icon: Wrench, label: 'Bot Config' },
  { to: '/replica-compare', icon: GitCompare, label: 'Replica Kiyas' },
  { to: '/lean', icon: ShieldCheck, label: 'LEAN' },
];

function fmt(n: number | undefined) {
  if (n == null) return '--';
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`;
  return `$${n.toFixed(0)}`;
}

function BotPanel() {
  const { accounts, fetchAccounts } = useAccountStore();
  const botStatuses = useUiStore((s) => s.botStatuses);
  const botLogs = useUiStore((s) => s.botLogs);
  const setBotStatus = useUiStore((s) => s.setBotStatus);
  const [expandedBot, setExpandedBot] = useState<number | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    accounts.forEach((acc) => {
      api.get<BotStatus>(`/bot/status?accountId=${acc.id}`).then((s) => setBotStatus(acc.id, s)).catch(() => {});
    });
  }, [accounts, setBotStatus]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [expandedBot, botLogs]);

  const toggle = async (accountId: number, isRunning: boolean) => {
    setToggling(accountId);
    try {
      const endpoint = isRunning ? '/bot/stop' : '/bot/start';
      const result = await api.post<BotStatus>(endpoint, { accountId });
      setBotStatus(accountId, result);
      fetchAccounts();
    } catch {}
    setToggling(null);
  };

  const logs = expandedBot ? (botLogs[expandedBot] || []) : [];

  return (
    <div className="flex flex-col min-h-0 border-t border-white/5">
      <div className="px-3 py-1.5">
        <span className="text-[9px] font-medium text-ink-400 tracking-[0.25em] uppercase">BOTS</span>
      </div>
      <div className="flex flex-col gap-px px-2">
        {accounts.map((acc) => {
          const status = botStatuses[acc.id];
          const isRunning = status?.status === 'running';
          const isExpanded = expandedBot === acc.id;
          return (
            <div key={acc.id}>
              <div className="flex items-center gap-1.5 px-1.5 py-1 hover:bg-white/[0.025] rounded transition-colors">
                <button
                  onClick={() => toggle(acc.id, isRunning)}
                  disabled={toggling === acc.id}
                  className={`w-5 h-5 flex items-center justify-center rounded transition-colors disabled:opacity-50 ${
                    isRunning
                      ? 'bg-up/15 text-up hover:bg-up/25'
                      : 'bg-down/15 text-down hover:bg-down/25'
                  }`}
                >
                  {isRunning ? <Square size={8} /> : <Play size={8} className="ml-0.5" />}
                </button>
                <button
                  onClick={() => setExpandedBot(isExpanded ? null : acc.id)}
                  className="flex-1 flex items-center gap-1.5 min-w-0 text-left"
                >
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isRunning ? 'bg-up pulse-dot' : 'bg-down'}`} />
                  <span className="text-[10px] text-ink-200 truncate">{acc.name}</span>
                  {isRunning && status?.totalOrders != null && status.totalOrders > 0 && (
                    <span className="text-[9px] text-ink-500 num ml-auto flex-shrink-0">{status.totalOrders}ord</span>
                  )}
                </button>
              </div>
              {isExpanded && (
                <div className="ml-1 mr-1 mb-1 bg-ink-850 border border-white/5 rounded">
                  {isRunning && status && (
                    <div className="flex gap-2 px-2 py-1 border-b border-white/5 text-[9px] text-ink-400">
                      <span>S:{status.totalScans}</span>
                      <span>G:{status.totalSignals}</span>
                      <span>O:{status.totalOrders}</span>
                    </div>
                  )}
                  <div ref={logRef} className="max-h-[160px] overflow-y-auto p-1.5 space-y-px">
                    {logs.length === 0 ? (
                      <p className="text-[9px] text-ink-600 text-center py-2">No logs</p>
                    ) : (
                      logs.slice(-30).map((l, i) => (
                        <div key={i} className="text-[9px] leading-[14px] font-mono">
                          <span className="text-ink-500">{l.time?.split('T').pop()?.substring(0, 8) || ''} </span>
                          <span className={
                            l.level === 'error' ? 'text-down' :
                            l.level === 'warn' ? 'text-warn' :
                            'text-ink-300'
                          }>{l.message}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function Sidebar() {
  const { accounts, activeAccountId, setActiveAccount } = useAccountStore();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  const active = accounts.find((a) => a.id === activeAccountId);

  const NEUTRAL_PATHS = new Set(['/bot', '/bot-overview', '/journal', '/backtest', '/bot-config', '/charts', '/replica-compare', '/']);
  const pickAccount = (id: number | null) => {
    setActiveAccount(id);
    setDropdownOpen(false);
    if (id !== null && !NEUTRAL_PATHS.has(location.pathname)) {
      navigate('/bot');
    }
  };

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setDropdownOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <aside className="w-[212px] min-w-[212px] bg-[#471c0b] border-r border-white/5 flex flex-col h-screen sticky top-0 font-mono select-none">
      <div className="p-3 border-b border-white/5" ref={dropRef}>
        <span className="text-[9px] font-medium text-ink-400 tracking-[0.25em] uppercase">ACCOUNT</span>
        <button
          onClick={() => setDropdownOpen(!dropdownOpen)}
          className="mt-1.5 w-full flex items-center justify-between bg-ink-800 border border-white/5 rounded px-2.5 py-1.5 text-[11px] text-ink-50 hover:border-white/10 transition-colors"
        >
          <span className="flex items-center gap-2 truncate">
            {activeAccountId === null ? (
              <span className="relative inline-flex rounded-full h-2 w-2 bg-ink-300" />
            ) : (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-up opacity-60" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-up" />
              </span>
            )}
            <span className="truncate">{activeAccountId === null ? 'All Accounts' : (active?.name ?? 'No Account')}</span>
          </span>
          <ChevronDown size={12} className={`text-ink-400 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
        </button>
        {dropdownOpen && accounts.length > 0 && (
          <div className="absolute z-50 mt-1 left-3 right-3 bg-ink-800 border border-white/10 rounded shadow-lg max-h-48 overflow-y-auto">
            <button
              onClick={() => pickAccount(null)}
              className={`w-full text-left flex items-center gap-2 px-2.5 py-1.5 text-[11px] transition-colors border-b border-white/5 ${
                activeAccountId === null ? 'text-up bg-up/5' : 'text-ink-200 hover:bg-white/[0.025]'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-ink-300" />
              <span className="truncate">All Accounts</span>
            </button>
            {accounts.map((acc) => (
              <button
                key={acc.id}
                onClick={() => pickAccount(acc.id)}
                className={`w-full text-left flex items-center gap-2 px-2.5 py-1.5 text-[11px] transition-colors ${
                  acc.id === activeAccountId ? 'text-up bg-up/5' : 'text-ink-200 hover:bg-white/[0.025]'
                }`}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: acc.color || '#3ddc97' }} />
                <span className="truncate">{acc.name}</span>
              </button>
            ))}
          </div>
        )}
        <div className="mt-2 grid grid-cols-2 gap-2">
          <div>
            <span className="text-[9px] text-ink-400 tracking-[0.25em]">BAL</span>
            <p className="text-[10px] text-ink-100 mt-0.5">
              {activeAccountId === null
                ? fmt(accounts.reduce((s, a) => s + (a.account_equity ?? a.wallet_balance ?? a.balance ?? 0), 0))
                : fmt(active?.account_equity ?? active?.wallet_balance ?? active?.balance)}
            </p>
          </div>
          <div>
            <span className="text-[9px] text-ink-400 tracking-[0.25em]">MARGIN</span>
            <p className="text-[10px] text-ink-100 mt-0.5">
              {activeAccountId === null ? '--' : (active?.leverage ? `${active.leverage}x` : '--')}
            </p>
          </div>
        </div>
      </div>

      <div className="py-2">
        <span className="px-3 text-[9px] font-medium text-ink-400 tracking-[0.25em] uppercase">NAVIGATE</span>
        <nav className="mt-1.5 flex flex-col">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-1.5 text-[11px] transition-colors ${
                  isActive
                    ? 'selbar text-ink-50'
                    : 'text-ink-200 hover:bg-white/[0.025]'
                }`
              }
            >
              <item.icon size={14} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        <BotPanel />
      </div>

      <div className="border-t border-white/5">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex items-center gap-2.5 px-3 py-1.5 text-[11px] transition-colors ${
              isActive ? 'selbar text-ink-50' : 'text-ink-200 hover:bg-white/[0.025]'
            }`
          }
        >
          <Settings size={14} />
          Settings
        </NavLink>
      </div>

      <div className="p-3 border-t border-white/5">
        <p className="text-[9px] text-ink-500 text-center truncate">
          {activeAccountId === null ? `all :: ${accounts.length} accounts` : `${active?.engine ?? 'paper'} :: ${active?.name ?? '--'}`}
        </p>
      </div>
    </aside>
  );
}
