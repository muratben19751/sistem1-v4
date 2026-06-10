import { Bell, X } from 'lucide-react';
import MobileAlerts from '../pages/MobileAlerts';

export default function MobileAlertDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <div className={`fixed inset-0 z-[60] ${open ? '' : 'pointer-events-none'}`} aria-hidden={!open}>
      <div
        className={`absolute inset-0 bg-black/60 transition-opacity duration-200 ${open ? 'opacity-100' : 'opacity-0'}`}
        onClick={onClose}
      />
      <div
        className={`absolute top-0 right-0 h-[100dvh] w-[88%] max-w-sm bg-ink-900 border-l border-white/10 flex flex-col transition-transform duration-200 ${open ? 'translate-x-0' : 'translate-x-full'}`}
      >
        <div className="shrink-0 flex items-center justify-between px-3 py-3 border-b-2 border-demo/50">
          <span className="text-sm font-semibold text-ink-50 flex items-center gap-2">
            <Bell size={16} className="text-demo" /> Alertler
          </span>
          <button onClick={onClose} aria-label="Kapat" className="text-ink-400 active:text-ink-100 p-1">
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom)]">
          {open && <MobileAlerts />}
        </div>
      </div>
    </div>
  );
}
