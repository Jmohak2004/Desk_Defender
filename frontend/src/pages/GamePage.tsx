import React, { useEffect, useState } from 'react';
import { Battlefield } from '../components/Battlefield';
import { CameraPreview } from '../components/CameraPreview';
import { GameHUD } from '../components/GameHUD';
import { ObjectAssignmentPanel } from '../components/ObjectAssignmentPanel';
import { ObjectList } from '../components/ObjectList';
import { SimDeskPanel } from '../components/SimDeskPanel';
import { StatusBanners } from '../components/StatusBanners';
import { WaveSummaryModal } from '../components/WaveSummaryModal';
import { act, onGameEvents } from '../hooks/useGameSocket';
import { useGameStore } from '../store/gameStore';
import { play } from '../utils/audio';
import type { AbilityName } from '../types/game';

export const GamePage: React.FC = () => {
  const viewMode = useGameStore((s) => s.viewMode);
  const selected = useGameStore((s) => s.selectedObjectId);
  const status = useGameStore((s) => s.game?.status);
  const calibrated = useGameStore((s) => s.vision?.calibration.is_calibrated ?? false);
  const setPage = useGameStore((s) => s.setPage);
  const [banner, setBanner] = useState<{ key: number; title: string; sub: string } | null>(null);

  // Wave banners, end-of-game navigation and notable-event toasts.
  useEffect(() => {
    return onGameEvents((events) => {
      const { toast } = useGameStore.getState();
      for (const ev of events) {
        if (ev.type === 'wave_started') {
          setBanner({ key: Date.now(), title: `WAVE ${ev.wave}`, sub: `${ev.enemies} enemies · AI ${String(ev.difficulty)}` });
          play('wave');
        } else if (ev.type === 'game_over') {
          const win = ev.outcome === 'victory';
          setBanner({ key: Date.now(), title: win ? 'VICTORY' : 'CORE DESTROYED', sub: `Final score ${Number(ev.score).toLocaleString()}` });
          play(win ? 'victory' : 'defeat');
          setTimeout(() => setPage('results'), 2800);
        } else if (ev.type === 'no_path') {
          toast('warning', String(ev.message));
        } else if (ev.type === 'structure_removed') {
          toast('info', `${ev.cls} left the desk - structure removed`);
        } else if (ev.type === 'sabotage') {
          toast('warning', 'A saboteur disabled one of your towers!');
        }
      }
    });
  }, [setPage]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      const typing = el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || (el.tagName === 'INPUT' && ['text', 'number', 'search'].includes((el as HTMLInputElement).type));
      if (typing) return;
      const st = useGameStore.getState();
      const s = st.game?.status;
      if (e.code === 'Space') {
        e.preventDefault();
        if (s === 'running') act('pause');
        else if (s === 'paused') act('resume');
      } else if (e.key === 'd' || e.key === 'D') st.toggleDebug();
      else if (e.key === 'v' || e.key === 'V') st.setViewMode(st.viewMode === 'split' ? 'battlefield' : st.viewMode === 'battlefield' ? 'camera' : 'split');
      else if (e.key === 'Escape') { st.setTargeting(null); st.select(null); }
      else if (['1', '2', '3'].includes(e.key)) {
        const ab = (['strike', 'emp', 'repair'] as AbilityName[])[Number(e.key) - 1];
        if (ab === 'strike') st.setTargeting(st.targeting ? null : 'strike');
        else act('ability', { ability: ab });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const side = (
    <div className="space-y-4">
      {selected ? <ObjectAssignmentPanel /> : <ObjectList />}
      {selected && <ObjectList />}
      <SimDeskPanel />
      <Legend />
    </div>
  );

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 py-2">
      <GameHUD />
      <StatusBanners />
      {!calibrated && (
        <div className="rounded-xl border border-amber/40 bg-amber/10 p-4 text-amber">
          The desk is not calibrated, so physical objects cannot be placed on the battlefield.{' '}
          <button className="underline" onClick={() => setPage('calibration')}>Calibrate now</button>
        </div>
      )}
      <div className="grid items-start gap-4 xl:grid-cols-[1fr_360px]">
        <div className="relative">
          {viewMode === 'split' && (
            <div className="grid gap-4 2xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
              <div className="space-y-2">
                <div className="label">Physical desk · live camera + detections</div>
                <CameraPreview variant="overlay" />
              </div>
              <div className="space-y-2">
                <div className="label">Virtual battlefield</div>
                <Battlefield />
              </div>
            </div>
          )}
          {viewMode === 'battlefield' && <Battlefield />}
          {viewMode === 'camera' && <CameraPreview variant="overlay" />}
          {banner && (
            <div key={banner.key} className="pointer-events-none absolute inset-0 flex animate-banner flex-col items-center justify-center">
              <div className="neon-text font-display text-6xl font-black tracking-widest text-white">{banner.title}</div>
              <div className="mt-2 text-lg font-semibold text-slate-200">{banner.sub}</div>
            </div>
          )}
        </div>
        {side}
      </div>
      {status === 'wave_ended' && <WaveSummaryModal />}
    </div>
  );
};

const Legend: React.FC = () => (
  <div className="panel p-4 text-sm">
    <div className="panel-title mb-2">Legend</div>
    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-slate-300">
      <span><b className="text-amber">■</b> Barrier (book)</span>
      <span><b className="text-orange-300">■</b> Fortress (box)</span>
      <span><b className="text-cyan">●</b> Tower (bottle/cup)</span>
      <span><b className="text-violet">●</b> Support (holder)</span>
      <span><b className="text-rose-400">▲</b> Scout</span>
      <span><b className="text-rose-500">■</b> Tank</span>
      <span><b className="text-fuchsia-400">◆</b> Saboteur</span>
      <span><b className="text-red-500">✸</b> Boss</span>
    </div>
    <div className="mt-2 text-xs text-slate-500">Dotted lines are planned enemy routes: violet = flanking around towers, amber = breaching a wall.</div>
    <div className="mt-2 text-xs text-slate-500">Keys: Space pause · 1/2/3 abilities · V view · D debug · Esc cancel</div>
  </div>
);
