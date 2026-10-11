import React, { useEffect, useState } from 'react';
import { useGameStore } from '../store/gameStore';

export const DebugOverlay: React.FC = () => {
  const show = useGameStore((s) => s.showDebug);
  const vision = useGameStore((s) => s.vision);
  const game = useGameStore((s) => s.game);
  const socket = useGameStore((s) => s.socket);
  const seq = useGameStore((s) => s.lastSeq);
  const latency = useGameStore((s) => s.latencyMs);
  const [renderFps, setRenderFps] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setRenderFps((window as unknown as { __renderFps?: number }).__renderFps ?? 0), 500);
    return () => clearInterval(id);
  }, []);

  if (!show) return null;
  const cam = vision?.camera;
  const pipe = vision?.pipeline;
  const rows: [string, string, boolean?][] = [
    ['Camera', cam ? `${cam.camera_name} (${cam.state})` : '—', !cam?.connected],
    ['Camera FPS', `${cam?.fps.toFixed(1) ?? 0}`],
    ['Detection rate', `${pipe?.detection_fps.toFixed(1) ?? 0} / ${pipe?.target_detection_fps ?? 0} Hz`],
    ['Inference', `${pipe?.inference_ms.toFixed(1) ?? 0} ms on ${pipe?.model_device ?? '?'}`],
    ['Model', cam?.is_simulated ? 'synthetic colour detector (SIM)' : `YOLO ${pipe?.model_status ?? '—'}`, pipe?.model_status === 'error'],
    ['Objects', `${vision?.objects.length ?? 0} tracked · ${pipe?.raw_detections ?? 0} raw`],
    ['Enemies', `${game?.enemies.length ?? 0}`],
    ['Sim tick', `${game?.perf.hz.toFixed(0) ?? 0} Hz · ${game?.perf.tick_ms.toFixed(2) ?? 0} ms`],
    ['Render', `${renderFps.toFixed(0)} fps`],
    ['WebSocket', `${socket} · seq ${seq} · ${latency.toFixed(0)} ms`, socket !== 'open'],
    ['Calibration', vision?.calibration.is_calibrated ? `v${vision.calibration.version}` : 'NOT CALIBRATED', !vision?.calibration.is_calibrated],
    ['Camera motion', pipe?.camera_motion.state ?? '—', pipe?.camera_motion.state === 'moved'],
    ['Nav grid', `v${game?.nav.version ?? 0}${game?.nav.no_path ? ' · NO PATH' : ''}`],
  ];
  return (
    <div className="pointer-events-none fixed bottom-4 left-4 z-40 w-[320px] rounded-xl border border-cyan/30 bg-black/85 p-3 font-mono text-xs shadow-glow backdrop-blur">
      <div className="mb-1.5 font-display text-[11px] font-bold tracking-widest text-cyan">DEBUG</div>
      {rows.map(([k, v, bad]) => (
        <div key={k} className="flex justify-between gap-3 py-0.5">
          <span className="text-slate-500">{k}</span>
          <span className={`truncate text-right ${bad ? 'text-rose-400' : 'text-slate-200'}`}>{v}</span>
        </div>
      ))}
    </div>
  );
};
