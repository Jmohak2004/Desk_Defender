import React, { useState } from 'react';
import { ArrowRight, CheckCircle2, FlaskConical, Loader2, Plug, RefreshCw, Smartphone, Unplug, Video } from 'lucide-react';
import { CameraPreview } from '../components/CameraPreview';
import { useCameraState } from '../hooks/useCameraState';
import { useGameStore } from '../store/gameStore';
import { api } from '../utils/api';

const RESOLUTIONS: [number, number][] = [[1280, 720], [1920, 1080], [3840, 2160]];

export const CameraSetupPage: React.FC = () => {
  const { devices, status, troubleshooting, busy, error, refresh, connect, disconnect } = useCameraState();
  const setPage = useGameStore((s) => s.setPage);
  const pipeline = useGameStore((s) => s.vision?.pipeline);
  const [res, setRes] = useState<[number, number]>([1920, 1080]);
  const [thumbs, setThumbs] = useState<Record<string, string | 'error' | 'loading'>>({});
  const [inferFps, setInferFps] = useState<number | null>(null);

  const probe = async (index: number) => {
    setThumbs((t) => ({ ...t, [index]: 'loading' }));
    try {
      const r = await fetch(`/api/cameras/${index}/snapshot?t=${Date.now()}`);
      if (!r.ok) throw new Error();
      const blob = await r.blob();
      setThumbs((t) => ({ ...t, [index]: URL.createObjectURL(blob) }));
    } catch {
      setThumbs((t) => ({ ...t, [index]: 'error' }));
    }
  };

  const saveRate = async (v: number) => {
    setInferFps(v);
    await api('/api/settings', { method: 'PUT', body: { vision: { inference_fps: v } } }).catch(() => {});
  };

  const real = devices.filter((d) => !d.is_simulated);
  const sim = devices.find((d) => d.is_simulated);
  const perm = status?.permission;

  return (
    <div className="mx-auto max-w-7xl space-y-6 py-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="label">Step 1 of 2</div>
          <h1 className="font-display text-3xl font-black text-white">Camera setup</h1>
          <p className="mt-1 text-slate-400">Mount your iPhone above the desk, rear camera pointing down, then pick it below and confirm the live picture.</p>
        </div>
        <button className="btn-primary" disabled={!status?.connected} onClick={() => setPage('calibration')}>
          Continue to calibration <ArrowRight className="h-4 w-4" />
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-4">
          <CameraPreview variant="overlay" />
          <div className="panel grid grid-cols-2 gap-4 p-4 text-sm sm:grid-cols-4">
            <Diag label="State" value={status?.state ?? '—'} ok={status?.connected} />
            <Diag label="Device" value={status?.camera_name ?? '—'} />
            <Diag label="Resolution" value={status?.resolution ? status.resolution.join('×') : '—'} />
            <Diag label="Camera FPS (measured)" value={status?.connected ? status.fps.toFixed(1) : '—'} />
            <Diag label="Permission" value={perm ?? '—'} ok={perm === 'authorized'} />
            <Diag label="Detector" value={status?.is_simulated ? 'synthetic' : pipeline?.model_status ?? '—'} ok={pipeline?.model_status === 'ready' || status?.is_simulated} />
            <Diag label="Inference (measured)" value={pipeline?.inference_ms ? `${pipeline.inference_ms.toFixed(0)} ms` : '—'} />
            <Diag label="Detection rate" value={pipeline ? `${pipeline.detection_fps.toFixed(1)} Hz` : '—'} />
          </div>
          {(error || status?.error) && (
            <div className="rounded-xl border border-rose-400/40 bg-rose-500/10 p-4 text-sm text-rose-100">{error ?? status?.error}</div>
          )}
        </div>

        <div className="space-y-4">
          <div className="panel space-y-3 p-5">
            <div className="flex items-center justify-between">
              <span className="panel-title">Cameras found</span>
              <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => { setThumbs({}); refresh(); }}><RefreshCw className="h-3.5 w-3.5" /> Refresh</button>
            </div>
            {real.length === 0 && <p className="text-sm text-amber">No cameras detected. See troubleshooting below.</p>}
            {real.map((d) => {
              const active = status?.camera_id === d.id && status?.connected;
              const thumb = thumbs[String(d.index)];
              return (
                <div key={d.unique_id} className={`rounded-xl border p-3 ${active ? 'border-emerald-400/50 bg-emerald-500/10' : 'border-line bg-white/[0.02]'}`}>
                  <div className="flex items-center gap-3">
                    {d.is_continuity ? <Smartphone className="h-5 w-5 text-cyan" /> : <Video className="h-5 w-5 text-slate-400" />}
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold text-white">{d.name}</div>
                      <div className="text-xs text-slate-400">
                        index {d.index} · {d.device_type}{d.is_continuity ? ' · Continuity Camera' : ''}
                      </div>
                    </div>
                    {active ? (
                      <span className="chip border-emerald-400/40 text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" /> live</span>
                    ) : (
                      <button className="btn-primary px-3 py-1.5 text-xs" disabled={busy} onClick={() => connect(d.id, res[0], res[1])}>
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plug className="h-3.5 w-3.5" />} Use
                      </button>
                    )}
                  </div>
                  <div className="mt-2">
                    {thumb && thumb !== 'loading' && thumb !== 'error' ? (
                      <img src={thumb} alt={d.name} className="w-full rounded-lg border border-line" />
                    ) : (
                      <button className="text-xs text-cyan hover:underline" onClick={() => probe(d.index!)} disabled={thumb === 'loading'}>
                        {thumb === 'loading' ? 'Grabbing a frame…' : thumb === 'error' ? 'No frame - device busy or asleep. Retry' : 'Show a snapshot to confirm which camera this is'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            {sim && (
              <div className="rounded-xl border border-amber/40 bg-amber/5 p-3">
                <div className="flex items-center gap-3">
                  <FlaskConical className="h-5 w-5 text-amber" />
                  <div className="flex-1">
                    <div className="font-semibold text-amber">Simulated desk</div>
                    <div className="text-xs text-slate-400">Development only - a synthetic scene, clearly labelled in game.</div>
                  </div>
                  <button className="btn-ghost px-3 py-1.5 text-xs" disabled={busy || !!status?.is_simulated} onClick={() => connect('simulated')}>Use</button>
                </div>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2 pt-1 text-sm">
              <span className="text-slate-400">Resolution</span>
              {RESOLUTIONS.map((r) => (
                <button key={r.join()} onClick={() => setRes(r)} className={`rounded-lg border px-2.5 py-1 font-mono text-xs ${res.join() === r.join() ? 'border-cyan/60 text-cyan' : 'border-line text-slate-300'}`}>
                  {r[0]}×{r[1]}
                </button>
              ))}
              {status?.connected && !status.is_simulated && (
                <button className="btn-ghost ml-auto px-3 py-1.5 text-xs" onClick={() => connect(status.camera_id!, res[0], res[1])}>Apply</button>
              )}
            </div>
            <label className="block text-sm">
              <div className="flex justify-between text-slate-400">
                <span>Detection frequency</span>
                <span className="font-mono text-slate-200">{inferFps ?? pipeline?.target_detection_fps ?? 8} Hz</span>
              </div>
              <input type="range" min={1} max={15} step={1} className="w-full" value={inferFps ?? pipeline?.target_detection_fps ?? 8} onChange={(e) => saveRate(Number(e.target.value))} />
            </label>
            {status?.connected && (
              <button className="btn-danger w-full" onClick={disconnect}><Unplug className="h-4 w-4" /> Disconnect camera</button>
            )}
          </div>

          <div className="panel p-5">
            <div className="panel-title mb-3">Troubleshooting Continuity Camera</div>
            {perm === 'denied' && (
              <p className="mb-3 rounded-lg bg-rose-500/15 p-3 text-sm text-rose-100">
                Camera access is denied. Open <b>System Settings → Privacy &amp; Security → Camera</b>, enable the app that runs the backend
                (Terminal, iTerm or VS Code) and restart the backend.
              </p>
            )}
            <ol className="list-decimal space-y-2 pl-5 text-sm text-slate-300">
              {troubleshooting.map((t) => <li key={t}>{t}</li>)}
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
};

const Diag: React.FC<{ label: string; value: string; ok?: boolean }> = ({ label, value, ok }) => (
  <div>
    <div className="text-xs text-slate-500">{label}</div>
    <div className={`truncate font-mono font-semibold ${ok === undefined ? 'text-slate-100' : ok ? 'text-emerald-300' : 'text-amber'}`}>{value}</div>
  </div>
);
