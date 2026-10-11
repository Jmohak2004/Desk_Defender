import React from 'react';
import { Eye, RotateCcw } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import { api } from '../utils/api';
import { ROLE_STYLE } from './Battlefield';

/** All tracked physical objects with confidence and role - click one to assign it. */
export const ObjectList: React.FC = () => {
  const objects = useGameStore((s) => s.vision?.objects ?? []);
  const suppressed = useGameStore((s) => s.vision?.suppressed ?? []);
  const selected = useGameStore((s) => s.selectedObjectId);
  const select = useGameStore((s) => s.select);
  const calibrated = useGameStore((s) => s.vision?.calibration.is_calibrated ?? false);

  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="panel-title flex items-center gap-2"><Eye className="h-4 w-4 text-cyan" /> Desk objects</span>
        <span className="font-mono text-sm text-slate-400">{objects.filter((o) => o.confirmed).length}</span>
      </div>
      {!calibrated && <p className="text-sm text-amber">Calibrate the desk to map objects onto the battlefield.</p>}
      {calibrated && objects.length === 0 && (
        <p className="text-sm text-slate-400">No objects detected yet. Place a book, bottle or cup in the play area.</p>
      )}
      <div className="max-h-[340px] space-y-1.5 overflow-y-auto pr-1">
        {objects.map((o) => (
          <button
            key={o.id}
            onClick={() => select(o.id)}
            className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition ${
              selected === o.id ? 'border-cyan/60 bg-cyan/10' : 'border-line bg-white/[0.02] hover:bg-white/[0.06]'
            } ${o.is_stale || !o.confirmed ? 'opacity-60' : ''}`}
          >
            <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: ROLE_STYLE[o.role]?.color }} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold capitalize text-white">{o.detected_class}</div>
              <div className="text-xs text-slate-400">
                {ROLE_STYLE[o.role]?.label}
                {o.is_manual_role ? ' · manual' : ''}
                {o.is_stale ? ` · lost, removing in ${o.removal_in?.toFixed(1)}s` : !o.confirmed ? ' · confirming' : ''}
              </div>
            </div>
            <span className={`font-mono text-xs ${o.confidence < 0.5 ? 'text-amber' : 'text-slate-300'}`}>{Math.round(o.confidence * 100)}%</span>
          </button>
        ))}
      </div>
      {suppressed.length > 0 && (
        <button className="mt-3 flex items-center gap-1.5 text-xs text-slate-400 hover:text-white" onClick={() => api('/api/objects/suppressed', { method: 'DELETE' })}>
          <RotateCcw className="h-3.5 w-3.5" /> Restore {suppressed.length} removed detection{suppressed.length > 1 ? 's' : ''}
        </button>
      )}
    </div>
  );
};
