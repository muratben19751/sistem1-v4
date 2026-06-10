import { useEffect } from 'react';
import { useCustomizationStore } from '../store/customization-store';
import { RotateCcw } from 'lucide-react';

export default function SettingsPage() {
  return (
    <div>
      <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center px-4">
        <span className="text-[9px] tracking-[0.3em] text-ink-400 uppercase">[ SETTINGS ]</span>
      </div>
      <div className="p-4">
        <UiPreferencesTab />
      </div>
    </div>
  );
}

function UiPreferencesTab() {
  const { preferences, fetchPreferences, updatePreference, resetPreferences } = useCustomizationStore();
  useEffect(() => { fetchPreferences(); }, [fetchPreferences]);

  return (
    <>
      <div className="flex justify-end mb-4">
        <button onClick={resetPreferences}
          className="flex items-center gap-2 bg-ink-800 border border-white/5 text-ink-300 px-3 py-1.5 text-[11px] transition-colors hover:border-white/10">
          <RotateCcw size={14} /> Reset
        </button>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-ink-850 border border-white/5">
          <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center px-3">
            <span className="text-[9px] tracking-[0.3em] text-ink-400">[ CHART SETTINGS ]</span>
          </div>
          <div className="p-4 space-y-4">
            <SelectField label="Default Timeframe" value={preferences.defaultTimeframe}
              options={[{value:'1',label:'1m'},{value:'5',label:'5m'},{value:'15',label:'15m'},{value:'60',label:'1H'},{value:'240',label:'4H'},{value:'D',label:'1D'}]}
              onChange={(v) => updatePreference('defaultTimeframe', v)} />
            <SelectField label="Chart Type" value={preferences.chartType}
              options={[{value:'candle',label:'Candle'},{value:'heikinashi',label:'Heikin Ashi'},{value:'line',label:'Line'},{value:'area',label:'Area'}]}
              onChange={(v) => updatePreference('chartType', v)} />
            <ToggleField label="Show RSI" value={preferences.showRsi} onChange={(v) => updatePreference('showRsi', v)} />
            <ToggleField label="Show StochRSI" value={preferences.showStochRsi} onChange={(v) => updatePreference('showStochRsi', v)} />
            <ToggleField label="Show Volume" value={preferences.showVolume} onChange={(v) => updatePreference('showVolume', v)} />
            <ColorField label="Up Color" value={preferences.candleUpColor} onChange={(v) => updatePreference('candleUpColor', v)} />
            <ColorField label="Down Color" value={preferences.candleDownColor} onChange={(v) => updatePreference('candleDownColor', v)} />
          </div>
        </div>
        <div className="bg-ink-850 border border-white/5">
          <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center px-3">
            <span className="text-[9px] tracking-[0.3em] text-ink-400">[ DISPLAY ]</span>
          </div>
          <div className="p-4 space-y-4">
            <ToggleField label="Entry Markers" value={preferences.showEntryMarkers} onChange={(v) => updatePreference('showEntryMarkers', v)} />
            <ToggleField label="Exit Markers" value={preferences.showExitMarkers} onChange={(v) => updatePreference('showExitMarkers', v)} />
            <ToggleField label="Compact Mode" value={preferences.compactMode} onChange={(v) => updatePreference('compactMode', v)} />
            <SelectField label="Currency" value={preferences.currency}
              options={[{value:'USDT',label:'USDT'},{value:'USD',label:'USD'},{value:'TRY',label:'TRY'}]}
              onChange={(v) => updatePreference('currency', v)} />
            <SelectField label="Timezone" value={preferences.timezone}
              options={[{value:'local',label:'Local'},{value:'utc',label:'UTC'},{value:'europe_istanbul',label:'Istanbul (UTC+3)'}]}
              onChange={(v) => updatePreference('timezone', v)} />
            <ToggleField label="Browser Notifications" value={preferences.browserNotifications} onChange={(v) => updatePreference('browserNotifications', v)} />
            <ToggleField label="Sound Notifications" value={preferences.soundNotifications} onChange={(v) => updatePreference('soundNotifications', v)} />
          </div>
        </div>
      </div>
    </>
  );
}

function SelectField({ label, value, options, onChange }: {
  label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-[9px] tracking-widest text-ink-400 uppercase">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="bg-ink-800 text-ink-100 text-[11px] px-3 py-1.5 border border-white/5 focus:outline-none focus:border-white/20">
        {options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
      </select>
    </div>
  );
}

function ToggleField({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-[9px] tracking-widest text-ink-400 uppercase">{label}</label>
      <button onClick={() => onChange(!value)}
        className={`w-10 h-5 transition-colors relative ${value ? 'bg-info' : 'bg-ink-700'}`}>
        <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${value ? 'left-5' : 'left-0.5'}`} />
      </button>
    </div>
  );
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-[9px] tracking-widest text-ink-400 uppercase">{label}</label>
      <input type="color" value={value} onChange={(e) => onChange(e.target.value)}
        className="w-8 h-8 border border-white/5 cursor-pointer bg-transparent" />
    </div>
  );
}
