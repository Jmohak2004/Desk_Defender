import React, { useEffect } from 'react';
import { Camera, HelpCircle, Home, Settings, Shield, Swords, Target, Trophy, Wifi, WifiOff } from 'lucide-react';
import { useGameStore, type AppPage } from './store/gameStore';
import { useGameSocket } from './hooks/useGameSocket';
import { api } from './utils/api';
import { HomePage } from './pages/HomePage';
import { CameraSetupPage } from './pages/CameraSetupPage';
import { CalibrationPage } from './pages/CalibrationPage';
import { GamePage } from './pages/GamePage';
import { ResultsPage } from './pages/ResultsPage';
import { SettingsPage } from './pages/SettingsPage';
import { HighScoresPage } from './pages/HighScoresPage';
import { HowToPlayPage } from './pages/HowToPlayPage';
import { DebugOverlay } from './components/DebugOverlay';
import { Toasts } from './components/Toasts';
import type { GameConfig } from './types/game';

const NAV: { id: AppPage; label: string; icon: React.ElementType }[] = [
  { id: 'home', label: 'Home', icon: Home },
  { id: 'camera', label: 'Camera', icon: Camera },
  { id: 'calibration', label: 'Calibrate', icon: Target },
  { id: 'game', label: 'Battlefield', icon: Swords },
  { id: 'scores', label: 'Scores', icon: Trophy },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'help', label: 'How to play', icon: HelpCircle },
];

export const App: React.FC = () => {
  useGameSocket();
  const page = useGameStore((s) => s.page);
  const setPage = useGameStore((s) => s.setPage);
  const socket = useGameStore((s) => s.socket);
  const sim = useGameStore((s) => s.vision?.camera.is_simulated ?? false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api<GameConfig>('/api/config')
        .then((config) => !cancelled && useGameStore.setState({ config }))
        .catch(() => !cancelled && setTimeout(load, 2000));
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-line bg-abyss/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-6 py-3">
          <button onClick={() => setPage('home')} className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan/40 bg-cyan/10"><Shield className="h-5 w-5 text-cyan" /></span>
            <span className="font-display text-lg font-black tracking-wider text-white">DESK <span className="text-cyan">DEFENDER</span></span>
          </button>
          <nav className="flex flex-wrap items-center gap-1">
            {NAV.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setPage(id)}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold transition ${page === id ? 'bg-cyan/15 text-cyan' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}
              >
                <Icon className="h-4 w-4" /> <span className="hidden md:inline">{label}</span>
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            {sim && <span className="chip border-amber/50 bg-amber/15 text-amber">SIMULATED</span>}
            <span className={`chip ${socket === 'open' ? 'border-emerald-400/40 text-emerald-300' : 'border-rose-400/40 text-rose-300'}`}>
              {socket === 'open' ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
              {socket === 'open' ? 'Live' : socket === 'connecting' ? 'Connecting' : 'Offline'}
            </span>
          </div>
        </div>
      </header>
      {socket === 'closed' && (
        <div className="bg-rose-500/15 px-6 py-2 text-center text-sm text-rose-100">
          Lost connection to the backend. Retrying… make sure it is running with <code className="font-mono">./start.sh</code>.
        </div>
      )}
      <main className="flex-1 px-6 py-4">
        {page === 'home' && <HomePage />}
        {page === 'camera' && <CameraSetupPage />}
        {page === 'calibration' && <CalibrationPage />}
        {page === 'game' && <GamePage />}
        {page === 'results' && <ResultsPage />}
        {page === 'settings' && <SettingsPage />}
        {page === 'scores' && <HighScoresPage />}
        {page === 'help' && <HowToPlayPage />}
      </main>
      <DebugOverlay />
      <Toasts />
    </div>
  );
};

export default App;
