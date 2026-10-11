import React from 'react';
import { Camera, CheckCircle2, Circle, Cpu, HelpCircle, Play, Settings, Target, Trophy } from 'lucide-react';
import { useGameStore, type AppPage } from '../store/gameStore';

export const HomePage: React.FC = () => {
  const setPage = useGameStore((s) => s.setPage);
  const vision = useGameStore((s) => s.vision);
  const socket = useGameStore((s) => s.socket);
  const cam = vision?.camera;
  const checks: { label: string; ok: boolean; detail: string; page: AppPage }[] = [
    { label: 'Backend link', ok: socket === 'open', detail: socket === 'open' ? 'WebSocket connected' : 'Start the backend (./start.sh)', page: 'home' },
    {
      label: 'Camera',
      ok: !!cam?.connected,
      detail: cam?.connected ? `${cam.camera_name}${cam.is_simulated ? ' (SIMULATED)' : ''} · ${cam.fps.toFixed(0)} fps` : cam?.error ?? 'Not connected',
      page: 'camera',
    },
    {
      label: 'Desk calibration',
      ok: !!vision?.calibration.is_calibrated,
      detail: vision?.calibration.is_calibrated ? 'Four corners saved' : 'Mark the play area corners',
      page: 'calibration',
    },
    {
      label: 'Object detection',
      ok: vision?.pipeline.model_status === 'ready' || !!cam?.is_simulated,
      detail: cam?.is_simulated ? 'Synthetic colour detector' : vision?.pipeline.model_status === 'ready' ? `YOLO on ${vision.pipeline.model_device} · ${vision.pipeline.inference_ms.toFixed(0)} ms` : vision?.pipeline.model_error ?? `YOLO ${vision?.pipeline.model_status ?? 'waiting for camera'}`,
      page: 'settings',
    },
  ];
  const ready = checks.every((c) => c.ok);

  return (
    <div className="mx-auto grid max-w-6xl items-center gap-10 py-10 lg:grid-cols-[1.2fr_1fr]">
      <div className="animate-fade-up">
        <div className="chip mb-5 border-cyan/40 bg-cyan/10 text-cyan">Physical-world tower defense · Continuity Camera + YOLO</div>
        <h1 className="neon-text font-display text-6xl font-black leading-[1.05] tracking-wide text-white md:text-7xl">
          DESK<br /><span className="bg-gradient-to-r from-cyan via-sky-200 to-violet bg-clip-text text-transparent">DEFENDER</span>
        </h1>
        <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
          Your desk is the map. Books become walls, bottles become turrets, a pencil holder powers your defenses.
          Move a real object and the battlefield - and the enemy AI's routes - change instantly.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <button className="btn-primary px-7 py-3.5 text-base" onClick={() => setPage(ready ? 'game' : checks.find((c) => !c.ok)!.page === 'home' ? 'game' : checks.find((c) => !c.ok)!.page)}>
            <Play className="h-5 w-5" /> {ready ? 'Start Game' : 'Continue setup'}
          </button>
          <button className="btn-ghost px-5 py-3.5" onClick={() => setPage('camera')}><Camera className="h-4 w-4" /> Camera Setup</button>
          <button className="btn-ghost px-5 py-3.5" onClick={() => setPage('help')}><HelpCircle className="h-4 w-4" /> How to Play</button>
          <button className="btn-ghost px-5 py-3.5" onClick={() => setPage('settings')}><Settings className="h-4 w-4" /> Settings</button>
          <button className="btn-ghost px-5 py-3.5" onClick={() => setPage('scores')}><Trophy className="h-4 w-4" /> High Scores</button>
        </div>
      </div>

      <div className="panel animate-fade-up space-y-3 p-6">
        <div className="panel-title flex items-center gap-2"><Cpu className="h-4 w-4 text-cyan" /> System check</div>
        {checks.map((c) => (
          <button key={c.label} onClick={() => setPage(c.page)} className="flex w-full items-start gap-3 rounded-xl border border-line bg-white/[0.02] p-3 text-left hover:bg-white/[0.06]">
            {c.ok ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-400" /> : <Circle className="mt-0.5 h-5 w-5 text-amber" />}
            <div>
              <div className="font-semibold text-white">{c.label}</div>
              <div className={`text-sm ${c.ok ? 'text-slate-400' : 'text-amber'}`}>{c.detail}</div>
            </div>
          </button>
        ))}
        <div className="grid grid-cols-4 gap-2 pt-2 text-center text-xs">
          {[['📚', 'Book', 'Barrier', 'text-amber'], ['🍶', 'Bottle/Cup', 'Tower', 'text-cyan'], ['📦', 'Box', 'Fortress', 'text-orange-300'], ['✏️', 'Holder', 'Support', 'text-violet']].map(([e, a, b, c]) => (
            <div key={a} className="rounded-xl border border-line bg-black/30 p-2">
              <div className="text-2xl">{e}</div>
              <div className="text-slate-300">{a}</div>
              <div className={`font-semibold ${c}`}>{b}</div>
            </div>
          ))}
        </div>
        <button className="btn-ghost mt-1 w-full" onClick={() => setPage('calibration')}><Target className="h-4 w-4" /> Calibrate desk</button>
      </div>
    </div>
  );
};
