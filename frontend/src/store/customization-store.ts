import { create } from 'zustand';
import { api } from '../lib/api';

interface Preferences {
  defaultTimeframe: string;
  chartType: string;
  showRsi: boolean;
  showStochRsi: boolean;
  showVolume: boolean;
  candleUpColor: string;
  candleDownColor: string;
  showEntryMarkers: boolean;
  showExitMarkers: boolean;
  compactMode: boolean;
  currency: string;
  decimalPrecision: number;
  timezone: string;
  dateFormat: string;
  browserNotifications: boolean;
  soundNotifications: boolean;
  positionColumns: string;
}

const DEFAULT_PREFS: Preferences = {
  defaultTimeframe: '5',
  chartType: 'candle',
  showRsi: true,
  showStochRsi: true,
  showVolume: true,
  candleUpColor: '#22C55E',
  candleDownColor: '#EF4444',
  showEntryMarkers: true,
  showExitMarkers: true,
  compactMode: false,
  currency: 'USDT',
  decimalPrecision: 2,
  timezone: 'local',
  dateFormat: 'DD/MM/YYYY',
  browserNotifications: false,
  soundNotifications: false,
  positionColumns: 'symbol,side,leverage,margin,value,entry,mark,pnlUsd,pnlPct,risk,age',
};

interface CustomizationStore {
  preferences: Preferences;
  loading: boolean;
  fetchPreferences: () => Promise<void>;
  updatePreference: <K extends keyof Preferences>(key: K, value: Preferences[K]) => Promise<void>;
  resetPreferences: () => Promise<void>;
}

export const useCustomizationStore = create<CustomizationStore>((set, get) => ({
  preferences: { ...DEFAULT_PREFS },
  loading: false,

  fetchPreferences: async () => {
    set({ loading: true });
    try {
      const settings = await api.get<Record<string, string>>('/settings');
      const prefs = { ...DEFAULT_PREFS };
      for (const [key, value] of Object.entries(settings)) {
        if (key.startsWith('pref_') && key.slice(5) in prefs) {
          const prefKey = key.slice(5) as keyof Preferences;
          const current = prefs[prefKey];
          if (typeof current === 'boolean') {
            (prefs as any)[prefKey] = value === 'true';
          } else if (typeof current === 'number') {
            (prefs as any)[prefKey] = parseFloat(value);
          } else {
            (prefs as any)[prefKey] = value;
          }
        }
      }
      set({ preferences: prefs, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  updatePreference: async (key, value) => {
    set((s) => ({ preferences: { ...s.preferences, [key]: value } }));
    try {
      await api.put(`/settings/pref_${key}`, { value: String(value) });
    } catch (err) {
      console.error('[customization] save failed:', err);
    }
  },

  resetPreferences: async () => {
    const prefs = { ...DEFAULT_PREFS };
    set({ preferences: prefs });
    try {
      for (const [key, value] of Object.entries(prefs)) {
        await api.put(`/settings/pref_${key}`, { value: String(value) });
      }
    } catch (err) {
      console.error('[customization] reset sync failed:', err);
    }
  },
}));
