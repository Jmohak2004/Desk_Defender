import { create } from 'zustand';
import type { AbilityName, GameConfig, GameSnapshot, VisionSnapshot } from '../types/game';

export type AppPage = 'home' | 'camera' | 'calibration' | 'game' | 'results' | 'settings' | 'scores' | 'help';
export type ViewMode = 'split' | 'battlefield' | 'camera';
export type SocketState = 'connecting' | 'open' | 'closed';

export interface Prefs {
  playerName: string;
  sound: boolean;
  volume: number;
  showPaths: boolean;
  showDeskTexture: boolean;
  showThreat: boolean;
  showRanges: boolean;
}

export interface Toast {
  id: number;
  kind: 'info' | 'success' | 'warning' | 'error';
  text: string;
}

const PREFS_KEY = 'desk-defender-prefs';
const DEFAULT_PREFS: Prefs = {
  playerName: 'Player',
  sound: true,
  volume: 0.5,
  showPaths: true,
  showDeskTexture: true,
  showThreat: false,
  showRanges: true,
};

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : DEFAULT_PREFS;
  } catch {
    return DEFAULT_PREFS;
  }
}

interface StoreState {
  page: AppPage;
  viewMode: ViewMode;
  showDebug: boolean;
  selectedObjectId: string | null;
  targeting: AbilityName | null;
  simDrag: boolean;
  socket: SocketState;
  lastSeq: number;
  lastMessageAt: number;
  latencyMs: number;
  game: GameSnapshot | null;
  vision: VisionSnapshot | null;
  config: GameConfig | null;
  prefs: Prefs;
  toasts: Toast[];

  setPage: (p: AppPage) => void;
  setViewMode: (m: ViewMode) => void;
  toggleDebug: () => void;
  select: (id: string | null) => void;
  setTargeting: (a: AbilityName | null) => void;
  setSimDrag: (v: boolean) => void;
  setPrefs: (p: Partial<Prefs>) => void;
  toast: (kind: Toast['kind'], text: string) => void;
  dismissToast: (id: number) => void;
}

let toastId = 1;

export const useGameStore = create<StoreState>((set, get) => ({
  page: 'home',
  viewMode: 'split',
  showDebug: false,
  selectedObjectId: null,
  targeting: null,
  simDrag: false,
  socket: 'connecting',
  lastSeq: 0,
  lastMessageAt: 0,
  latencyMs: 0,
  game: null,
  vision: null,
  config: null,
  prefs: loadPrefs(),
  toasts: [],

  setPage: (page) => set({ page, targeting: null }),
  setViewMode: (viewMode) => set({ viewMode }),
  toggleDebug: () => set((s) => ({ showDebug: !s.showDebug })),
  select: (selectedObjectId) => set({ selectedObjectId }),
  setTargeting: (targeting) => set({ targeting }),
  setSimDrag: (simDrag) => set({ simDrag }),
  setPrefs: (p) => {
    const prefs = { ...get().prefs, ...p };
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch {
      /* storage unavailable - keep in memory */
    }
    set({ prefs });
  },
  toast: (kind, text) => {
    const id = toastId++;
    set((s) => ({ toasts: [...s.toasts.slice(-4), { id, kind, text }] }));
    setTimeout(() => get().dismissToast(id), kind === 'error' ? 6000 : 3500);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
