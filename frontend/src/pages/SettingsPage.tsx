import React, { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import { api } from '../utils/api';

interface RuntimeSettings {
  camera: { width: number; height: number };
  vision: {
    inference_fps: number;
    inference_size: number;
    confidence_threshold: number;
    device: string;
    shape_detection_enabled: boolean;
    stale_grace_seconds: number;
    position_smoothing_alpha: number;
    jitter_deadband: number;
    move_event_threshold: number;
    preview_fps: number;
    low_performance_mode: boolean;
  };
}

export const SettingsPage: React.FC = () => {
  const prefs = useGameStore((s) => s.prefs);
  const setPrefs = useGameStore((s) => s.setPrefs);
  const toast = useGameStore((s) => s.toast);
  const [rt, setRt] = useState<RuntimeSettings | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<RuntimeSettings>('/api/settings').then(setRt).catch((e) => setErr(e.message));
  }, []);

  const save = async () => {
    if (!rt) return;
    try {
      setRt(await api<RuntimeSettings>('/api/settings', { method: 'PUT', body: { vision: rt.vision } }));
      toast('success', 'Settings saved to backend/data/settings.json');
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const v = rt?.vision;
  const setV = (patch: Partial<RuntimeSettings['vision']>) => rt && setRt({ ...rt, vision: { ...rt.vision, ...patch } });

  return (
    <div className="mx-auto grid max-w-6xl gap-6 py-6 lg:grid-cols-2">
      <div className="panel space-y-4 p-6">
        <div className="panel-title">Player & display</div>
        <label className="block text-sm">
          <span className="text-slate-300">Player name (for high scores)</span>
          <input className="input mt-1" maxLength={24} value={prefs.playerName} onChange={(e) => setPrefs({ playerName: e.target.value })} />
        </label>
        <Toggle label="Sound effects" checked={prefs.sound} onChange={(sound) => setPrefs({ sound })} />
        <Range label="Volume" min={0} max={1} step={0.05} value={prefs.volume} onChange={(volume) => setPrefs({ volume })} fmt={(x) => `${Math.round(x * 100)}%`} />
        <Toggle label="Show enemy routes" checked={prefs.showPaths} onChange={(showPaths) => setPrefs({ showPaths })} />
        <Toggle label="Show tower ranges & auras" checked={prefs.showRanges} onChange={(showRanges) => setPrefs({ showRanges })} />
        <Toggle label="Show real desk under the battlefield" checked={prefs.showDeskTexture} onChange={(showDeskTexture) => setPrefs({ showDeskTexture })} />
        <Toggle label="Show tower threat heatmap (debug)" checked={prefs.showThreat} onChange={(showThreat) => setPrefs({ showThreat })} />
        <p className="text-xs text-slate-500">These preferences are stored in this browser.</p>
      </div>

      <div className="panel space-y-4 p-6">
        <div className="panel-title">Vision & performance</div>
        {err && <p className="rounded-lg bg-rose-500/15 p-3 text-sm text-rose-200">{err}</p>}
        {!v ? (
          <p className="text-slate-400">Loading…</p>
        ) : (
          <>
            <Toggle label="Low-performance mode (3 Hz detection, 416 px inference, lighter preview)" checked={v.low_performance_mode} onChange={(low_performance_mode) => setV({ low_performance_mode })} />
            <Range label="Detection frequency" min={1} max={15} step={1} value={v.inference_fps} onChange={(inference_fps) => setV({ inference_fps })} fmt={(x) => `${x} Hz`} />
            <Range label="Confidence threshold" min={0.1} max={0.9} step={0.05} value={v.confidence_threshold} onChange={(confidence_threshold) => setV({ confidence_threshold })} fmt={(x) => `${Math.round(x * 100)}%`} />
            <label className="block text-sm">
              <span className="text-slate-300">Inference size</span>
              <select className="input mt-1" value={v.inference_size} onChange={(e) => setV({ inference_size: Number(e.target.value) })}>
                {[320, 416, 480, 640, 800, 960].map((s) => <option key={s} value={s}>{s}px</option>)}
              </select>
            </label>
            <label className="block text-sm">
              <span className="text-slate-300">Inference device</span>
              <select className="input mt-1" value={v.device} onChange={(e) => setV({ device: e.target.value })}>
                <option value="auto">Auto (Apple GPU / MPS if available)</option>
                <option value="mps">Apple GPU (MPS)</option>
                <option value="cpu">CPU</option>
              </select>
            </label>
            <Toggle label="Detect unknown objects (needs empty-desk reference)" checked={v.shape_detection_enabled} onChange={(shape_detection_enabled) => setV({ shape_detection_enabled })} />
            <Range label="Lost-object grace period" min={1} max={10} step={0.5} value={v.stale_grace_seconds} onChange={(stale_grace_seconds) => setV({ stale_grace_seconds })} fmt={(x) => `${x}s`} />
            <Range label="Position smoothing" min={0.1} max={1} step={0.05} value={v.position_smoothing_alpha} onChange={(position_smoothing_alpha) => setV({ position_smoothing_alpha })} fmt={(x) => x.toFixed(2)} />
            <Range label="Jitter dead-band" min={0} max={20} step={1} value={v.jitter_deadband} onChange={(jitter_deadband) => setV({ jitter_deadband })} fmt={(x) => `${x} units`} />
            <Range label="Movement threshold" min={5} max={60} step={1} value={v.move_event_threshold} onChange={(move_event_threshold) => setV({ move_event_threshold })} fmt={(x) => `${x} units`} />
            <Range label="Preview frame rate" min={4} max={30} step={1} value={v.preview_fps} onChange={(preview_fps) => setV({ preview_fps })} fmt={(x) => `${x} fps`} />
            <button className="btn-primary w-full" onClick={save}><Save className="h-4 w-4" /> Save vision settings</button>
            <p className="text-xs text-slate-500">Balance values (enemy stats, waves, role stats, class→role mapping) live in backend/config.py.</p>
          </>
        )}
      </div>
    </div>
  );
};

const Toggle: React.FC<{ label: string; checked: boolean; onChange: (v: boolean) => void }> = ({ label, checked, onChange }) => (
  <label className="flex cursor-pointer items-center justify-between gap-4 text-sm text-slate-200">
    <span>{label}</span>
    <button type="button" onClick={() => onChange(!checked)} className={`relative h-6 w-11 shrink-0 rounded-full transition ${checked ? 'bg-cyan' : 'bg-white/15'}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${checked ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  </label>
);

const Range: React.FC<{ label: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void; fmt: (v: number) => string }> = ({ label, min, max, step, value, onChange, fmt }) => (
  <label className="block text-sm">
    <div className="flex justify-between text-slate-300"><span>{label}</span><span className="font-mono">{fmt(value)}</span></div>
    <input type="range" className="w-full" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
  </label>
);
