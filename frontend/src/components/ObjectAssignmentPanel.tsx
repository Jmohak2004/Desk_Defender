import React, { useEffect, useState } from 'react';
import { ArrowUpCircle, Box, Crosshair, Shapes, Shield, Sparkles, Trash2, X } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import { act } from '../hooks/useGameSocket';
import { ROLE_STYLE } from './Battlefield';
import type { Behavior, CustomConfig, StructureRole } from '../types/game';

const ROLES: { id: StructureRole; icon: React.ElementType; blurb: string }[] = [
  { id: 'barrier', icon: Shield, blurb: 'Blocks paths, slows enemies brushing past it.' },
  { id: 'defense_tower', icon: Crosshair, blurb: 'Shoots enemies in range.' },
  { id: 'heavy_fortification', icon: Box, blurb: 'Huge, very durable obstacle.' },
  { id: 'support_tower', icon: Sparkles, blurb: 'Buffs nearby towers and slows enemies.' },
  { id: 'custom', icon: Shapes, blurb: 'Pick the behaviour and stats yourself.' },
];

export const ObjectAssignmentPanel: React.FC = () => {
  const selectedId = useGameStore((s) => s.selectedObjectId);
  const select = useGameStore((s) => s.select);
  const obj = useGameStore((s) => s.vision?.objects.find((o) => o.id === selectedId));
  const structure = useGameStore((s) => s.game?.structures.find((x) => x.object_id === selectedId));
  const config = useGameStore((s) => s.config);
  const credits = useGameStore((s) => s.game?.credits ?? 0);
  const inGame = useGameStore((s) => ['running', 'paused', 'wave_ended'].includes(s.game?.status ?? 'idle'));

  const [role, setRole] = useState<StructureRole>('barrier');
  const [custom, setCustom] = useState<CustomConfig>({ behavior: 'attack' });

  useEffect(() => {
    if (obj) {
      setRole(obj.role);
      setCustom(obj.custom ?? { behavior: 'attack' });
    }
  }, [obj?.id, obj?.role]);

  if (!selectedId) return null;
  if (!obj) {
    return (
      <div className="panel p-5 text-sm text-slate-400">
        <div className="mb-2 flex items-center justify-between">
          <span className="panel-title">Object</span>
          <button onClick={() => select(null)}><X className="h-4 w-4" /></button>
        </div>
        {selectedId} is no longer detected by the camera.
      </div>
    );
  }

  const stats = config?.roles[role];
  const changed = role !== obj.role || (role === 'custom' && JSON.stringify(custom) !== JSON.stringify(obj.custom ?? { behavior: 'attack' }));
  const cost = role === 'custom' ? custom.cost ?? stats?.cost : stats?.cost;

  const apply = () => act('set_role', { object_id: obj.id, role, custom: role === 'custom' ? custom : null }, `${obj.detected_class} is now a ${ROLE_STYLE[role].label}`);
  const remove = () => {
    act('remove_object', { object_id: obj.id }, `Removed ${obj.detected_class} - it will be ignored at that spot`);
    select(null);
  };

  return (
    <div className="panel animate-fade-up space-y-4 p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="label">Selected object · {obj.id}</div>
          <div className="mt-0.5 text-xl font-bold capitalize text-white">{obj.detected_class}</div>
        </div>
        <button onClick={() => select(null)} className="text-slate-400 hover:text-white"><X className="h-5 w-5" /></button>
      </div>

      <div className="grid grid-cols-3 gap-2 text-sm">
        <Info label="Confidence" value={`${Math.round(obj.confidence * 100)}%`} warn={obj.confidence < 0.5} />
        <Info label="Source" value={obj.source === 'yolo' ? 'YOLO' : obj.source === 'shape' ? 'Shape' : 'Simulated'} />
        <Info label="Status" value={obj.is_stale ? `Lost ${obj.removal_in?.toFixed(1)}s` : obj.confirmed ? 'Tracked' : 'Confirming'} warn={obj.is_stale} />
      </div>
      {obj.confidence < 0.5 && <p className="text-xs text-amber">Low confidence - check the class and assign a role manually if it is wrong.</p>}

      <div>
        <div className="label mb-2">Role {obj.is_manual_role ? '(manual)' : `(auto from “${obj.detected_class}”)`}</div>
        <div className="grid gap-2">
          {ROLES.map(({ id, icon: Icon, blurb }) => (
            <button
              key={id}
              onClick={() => setRole(id)}
              className={`flex items-center gap-3 rounded-xl border px-3 py-2 text-left transition ${role === id ? 'border-cyan/60 bg-cyan/10' : 'border-line bg-white/[0.03] hover:bg-white/[0.07]'}`}
            >
              <Icon className="h-5 w-5 shrink-0" style={{ color: ROLE_STYLE[id].color }} />
              <div className="flex-1">
                <div className="text-sm font-semibold text-white">{config?.roles[id]?.label ?? id}</div>
                <div className="text-xs text-slate-400">{blurb}</div>
              </div>
              <span className="font-mono text-xs text-amber">{config?.roles[id]?.cost}¢</span>
            </button>
          ))}
        </div>
      </div>

      {role === 'custom' && (
        <div className="space-y-3 rounded-xl border border-line p-3">
          <div className="label">Custom behaviour</div>
          <div className="flex gap-2">
            {(['attack', 'block', 'support'] as Behavior[]).map((b) => (
              <button key={b} onClick={() => setCustom({ ...custom, behavior: b })} className={`flex-1 rounded-lg border px-2 py-1.5 text-sm capitalize ${custom.behavior === b ? 'border-cyan/60 bg-cyan/10 text-cyan' : 'border-line text-slate-300'}`}>
                {b}
              </button>
            ))}
          </div>
          <Slider label="Durability" min={50} max={2000} step={10} value={custom.durability ?? stats?.durability ?? 260} onChange={(v) => setCustom({ ...custom, durability: v })} />
          {custom.behavior === 'attack' && (
            <>
              <Slider label="Range" min={40} max={400} step={5} value={custom.range ?? 170} onChange={(v) => setCustom({ ...custom, range: v })} />
              <Slider label="Damage" min={0} max={80} step={1} value={custom.damage ?? 22} onChange={(v) => setCustom({ ...custom, damage: v })} />
              <Slider label="Fire rate" min={0.1} max={4} step={0.1} value={custom.fire_rate ?? 1} onChange={(v) => setCustom({ ...custom, fire_rate: v })} />
            </>
          )}
          <Slider label="Cost" min={0} max={500} step={5} value={custom.cost ?? stats?.cost ?? 50} onChange={(v) => setCustom({ ...custom, cost: v })} />
        </div>
      )}

      {structure && (
        <div className="grid grid-cols-2 gap-2 rounded-xl border border-line bg-black/20 p-3 font-mono text-sm">
          <Info label="Health" value={`${Math.round(structure.health)}/${Math.round(structure.max_health)}`} />
          <Info label="Level" value={`${structure.level}`} />
          {structure.behavior === 'attack' && <Info label="Damage" value={`${structure.damage.toFixed(0)} ×${structure.fire_rate}/s`} />}
          {structure.behavior === 'attack' && <Info label="Range" value={`${structure.range.toFixed(0)}`} />}
          {structure.behavior === 'support' && <Info label="Aura" value={`${structure.buff_radius.toFixed(0)}`} />}
          <Info label="Kills" value={`${structure.kills}`} />
          <Info label="Blocks path" value={structure.blocks_path ? 'yes' : 'no'} />
        </div>
      )}

      {inGame && changed && <p className="text-xs text-amber">Changing role mid-game costs {cost}¢ and resets upgrades.</p>}
      <div className="grid grid-cols-2 gap-2">
        <button className="btn-primary" disabled={!changed} onClick={apply}>Apply role</button>
        <button className="btn-danger" onClick={remove}><Trash2 className="h-4 w-4" /> Remove</button>
      </div>
      {structure && structure.upgrade_cost !== null && (
        <button className="btn-amber w-full" disabled={credits < structure.upgrade_cost || structure.destroyed} onClick={() => act('upgrade', { structure_id: structure.id }, `Upgraded to level ${structure.level + 1}`)}>
          <ArrowUpCircle className="h-4 w-4" /> Upgrade to level {structure.level + 1} · {structure.upgrade_cost}¢
        </button>
      )}
    </div>
  );
};

const Info: React.FC<{ label: string; value: string; warn?: boolean }> = ({ label, value, warn }) => (
  <div>
    <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
    <div className={`font-semibold ${warn ? 'text-amber' : 'text-slate-100'}`}>{value}</div>
  </div>
);

const Slider: React.FC<{ label: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void }> = ({ label, min, max, step, value, onChange }) => (
  <label className="block text-sm">
    <div className="flex justify-between text-slate-300"><span>{label}</span><span className="font-mono">{value}</span></div>
    <input type="range" className="w-full" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
  </label>
);
