import React from 'react';
import { FlaskConical, Plus, RotateCcw } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import { api } from '../utils/api';

const KINDS = ['book', 'bottle', 'cup', 'box', 'pencil holder'] as const;

/** Development-only controls for the SIMULATED desk. Hidden with a real camera. */
export const SimDeskPanel: React.FC = () => {
  const isSim = useGameStore((s) => s.vision?.camera.is_simulated ?? false);
  const simDrag = useGameStore((s) => s.simDrag);
  const setSimDrag = useGameStore((s) => s.setSimDrag);
  const toast = useGameStore((s) => s.toast);
  if (!isSim) return null;

  const add = async (kind: string) => {
    try {
      await api('/api/sim/objects', { body: { kind, x: 150 + Math.random() * 600, y: 100 + Math.random() * 500 } });
    } catch (e) {
      toast('error', (e as Error).message);
    }
  };

  return (
    <div className="panel border-amber/40 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-bold text-amber"><FlaskConical className="h-4 w-4" /> Simulated desk (dev mode)</div>
      <p className="mb-3 text-xs text-slate-400">
        Objects here are drawn on a synthetic camera frame and detected with OpenCV, exercising the full pipeline without hardware.
      </p>
      <label className="mb-3 flex items-center gap-2 text-sm text-slate-200">
        <input type="checkbox" checked={simDrag} onChange={(e) => setSimDrag(e.target.checked)} /> Drag simulated objects on the battlefield
      </label>
      <div className="flex flex-wrap gap-1.5">
        {KINDS.map((k) => (
          <button key={k} className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => add(k)}><Plus className="h-3 w-3" /> {k}</button>
        ))}
        <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => api('/api/sim/reset', { method: 'POST' })}><RotateCcw className="h-3 w-3" /> reset</button>
      </div>
    </div>
  );
};
