import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, MousePointerClick, RotateCcw, ScanSearch, Trash2 } from 'lucide-react';
import { api } from '../utils/api';
import { applyH, eventToLogical, perspectiveTransform, validateQuad, type Pt } from '../utils/coordinateMapping';
import { useGameStore } from '../store/gameStore';

const LABELS = ['Top-left', 'Top-right', 'Bottom-right', 'Bottom-left'];

interface CalibrationData {
  is_calibrated: boolean;
  points: Pt[] | null;
  frame_size: [number, number] | null;
  empty_desk_reference: boolean;
}

/** Four-corner desk calibration over the raw camera stream. Click to place, drag to adjust. */
export const CalibrationCanvas: React.FC<{ onConfirmed?: () => void }> = ({ onConfirmed }) => {
  const camera = useGameStore((s) => s.vision?.camera);
  const toast = useGameStore((s) => s.toast);
  const frame: [number, number] = (camera?.resolution as [number, number]) ?? [1920, 1080];
  const [points, setPoints] = useState<Pt[]>([]);
  const [drag, setDrag] = useState<number | null>(null);
  const [saved, setSaved] = useState<CalibrationData | null>(null);
  const [busy, setBusy] = useState(false);
  const [serverMsg, setServerMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const overlayRef = useRef<SVGSVGElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<CalibrationData>('/api/calibration');
      setSaved(data);
      if (data.points && data.frame_size) {
        const sx = frame[0] / data.frame_size[0];
        const sy = frame[1] / data.frame_size[1];
        setPoints(data.points.map(([x, y]) => [x * sx, y * sy]));
      }
    } catch (e) {
      setServerMsg({ ok: false, text: (e as Error).message });
    }
  }, [frame[0], frame[1]]);

  useEffect(() => {
    load();
  }, [load]);

  const localError = points.length === 4 ? validateQuad(points, frame) : null;

  const suggest = async () => {
    try {
      const s = await api<{ points: Pt[]; frame_size: [number, number]; message: string }>('/api/calibration/suggest');
      const sx = frame[0] / s.frame_size[0];
      const sy = frame[1] / s.frame_size[1];
      setPoints(s.points.map(([x, y]) => [x * sx, y * sy]));
      setServerMsg({ ok: true, text: s.message });
    } catch (e) {
      setServerMsg({ ok: false, text: (e as Error).message });
    }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await api('/api/calibration', { body: { points, frame_size: frame } });
      setServerMsg({ ok: true, text: 'Calibration saved. Detected objects now map onto the battlefield.' });
      toast('success', 'Desk calibrated');
      await load();
      onConfirmed?.();
    } catch (e) {
      setServerMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const captureEmpty = async () => {
    setBusy(true);
    try {
      const r = await api<{ message: string }>('/api/calibration/empty-desk', { method: 'POST' });
      setServerMsg({ ok: true, text: r.message });
      await load();
    } catch (e) {
      setServerMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const clearEmpty = async () => {
    await api('/api/calibration/empty-desk', { method: 'DELETE' });
    await load();
  };

  const toFrame = (e: React.PointerEvent) => eventToLogical(e, overlayRef.current as unknown as HTMLElement, frame[0], frame[1]);

  const onDown = (e: React.PointerEvent) => {
    const p = toFrame(e);
    const tol = frame[0] * 0.025;
    const idx = points.findIndex(([x, y]) => Math.hypot(x - p[0], y - p[1]) < tol);
    if (idx >= 0) {
      setDrag(idx);
      (e.target as Element).setPointerCapture(e.pointerId);
    } else if (points.length < 4) {
      setPoints([...points, p]);
    }
  };
  const onMove = (e: React.PointerEvent) => {
    if (drag === null) return;
    const [x, y] = toFrame(e);
    setPoints((prev) => prev.map((pt, i) => (i === drag ? [Math.max(0, Math.min(frame[0], x)), Math.max(0, Math.min(frame[1], y))] : pt)));
  };

  // Keyboard nudging of the last selected handle for precise placement.
  const [focusIdx, setFocusIdx] = useState(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (points.length !== 4 || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Tab'].includes(e.key)) return;
      if (e.key === 'Tab') {
        e.preventDefault();
        setFocusIdx((i) => (i + 1) % 4);
        return;
      }
      e.preventDefault();
      const step = e.shiftKey ? 10 : 2;
      const d: Pt = e.key === 'ArrowLeft' ? [-step, 0] : e.key === 'ArrowRight' ? [step, 0] : e.key === 'ArrowUp' ? [0, -step] : [0, step];
      setPoints((prev) => prev.map((pt, i) => (i === focusIdx ? [pt[0] + d[0], pt[1] + d[1]] : pt)));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [points.length, focusIdx]);

  // Battlefield grid projected through the homography, so mistakes are visible immediately.
  let gridLines: [Pt, Pt][] = [];
  if (points.length === 4 && !localError) {
    try {
      const Hm = perspectiveTransform([[0, 0], [1000, 0], [1000, 700], [0, 700]], points);
      for (let gx = 100; gx < 1000; gx += 100) gridLines.push([applyH(Hm, [gx, 0]), applyH(Hm, [gx, 700])]);
      for (let gy = 100; gy < 700; gy += 100) gridLines.push([applyH(Hm, [0, gy]), applyH(Hm, [1000, gy])]);
    } catch {
      gridLines = [];
    }
  }
  const handleR = frame[0] * 0.012;
  const stroke = frame[0] / 640;

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
      <div className="space-y-3">
        <div className="relative overflow-hidden rounded-2xl border border-line bg-black">
          <img src="/api/stream?variant=raw" alt="Raw camera" className="block aspect-video w-full object-contain" />
          <svg
            ref={overlayRef}
            viewBox={`0 0 ${frame[0]} ${frame[1]}`}
            preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={() => setDrag(null)}
          >
            {gridLines.map(([a, b], i) => (
              <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="rgba(167,139,250,0.55)" strokeWidth={stroke} />
            ))}
            {points.length >= 2 && (
              <polygon
                points={points.map((p) => p.join(',')).join(' ')}
                fill={localError ? 'rgba(251,113,133,0.15)' : 'rgba(34,211,238,0.12)'}
                stroke={localError ? '#fb7185' : '#22d3ee'}
                strokeWidth={stroke * 2}
              />
            )}
            {points.map(([x, y], i) => (
              <g key={i}>
                <circle cx={x} cy={y} r={handleR * 1.6} fill="rgba(0,0,0,0.45)" stroke={i === focusIdx ? '#fde047' : '#ffffff'} strokeWidth={stroke * 1.5} />
                <circle cx={x} cy={y} r={handleR * 0.35} fill="#22d3ee" />
                <text x={x > frame[0] * 0.7 ? x - handleR * 2 : x + handleR * 2} y={y > frame[1] * 0.85 ? y - handleR * 2.2 : y - handleR * 1.5} textAnchor={x > frame[0] * 0.7 ? 'end' : 'start'} fill="#e0f2fe" fontSize={frame[0] / 55} fontWeight={700} style={{ paintOrder: 'stroke', stroke: '#000', strokeWidth: stroke * 3 }}>
                  {i + 1}. {LABELS[i]}
                </text>
              </g>
            ))}
          </svg>
          {points.length < 4 && (
            <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/80 px-4 py-2 text-sm font-semibold text-cyan">
              <MousePointerClick className="mr-2 inline h-4 w-4" />
              Click the <b>{LABELS[points.length].toLowerCase()}</b> corner of your play area ({points.length + 1}/4)
            </div>
          )}
        </div>
        <p className="text-sm text-slate-400">
          Drag a corner to adjust it. For pixel-precise placement press <kbd className="rounded bg-white/10 px-1">Tab</kbd> to pick a corner and use the arrow keys (hold Shift for bigger steps).
          The violet grid shows how the battlefield will lie on your desk.
        </p>
      </div>

      <div className="space-y-4">
        <div className="panel space-y-3 p-5">
          <div className="panel-title">Corners</div>
          <ol className="space-y-1.5 font-mono text-sm">
            {LABELS.map((l, i) => (
              <li key={l} className={`flex justify-between ${i === focusIdx && points.length === 4 ? 'text-amber' : 'text-slate-300'}`}>
                <span>{i + 1}. {l}</span>
                <span>{points[i] ? `${Math.round(points[i][0])}, ${Math.round(points[i][1])}` : '—'}</span>
              </li>
            ))}
          </ol>
          {localError && <p className="rounded-lg bg-rose-500/15 p-3 text-sm text-rose-200">{localError}</p>}
          {serverMsg && (
            <p className={`rounded-lg p-3 text-sm ${serverMsg.ok ? 'bg-emerald-500/15 text-emerald-200' : 'bg-rose-500/15 text-rose-200'}`}>{serverMsg.text}</p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <button className="btn-ghost" onClick={suggest} disabled={!camera?.connected}>
              <ScanSearch className="h-4 w-4" /> Auto-detect
            </button>
            <button className="btn-ghost" onClick={() => { setPoints([]); setServerMsg(null); setFocusIdx(0); }}>
              <RotateCcw className="h-4 w-4" /> Reset
            </button>
          </div>
          <button className="btn-primary w-full" disabled={points.length !== 4 || !!localError || busy || !camera?.connected} onClick={confirm}>
            <CheckCircle2 className="h-4 w-4" /> {saved?.is_calibrated ? 'Recalibrate' : 'Confirm calibration'}
          </button>
          {saved?.is_calibrated && <p className="text-xs text-emerald-300">Saved calibration active · reloaded automatically on restart.</p>}
        </div>

        <div className="panel space-y-3 p-5">
          <div className="panel-title">Unknown-object detection</div>
          <p className="text-sm text-slate-400">
            YOLO recognises common items (books, bottles, cups, phones…) but not boxes or pencil holders. Clear the desk and capture
            a reference so anything new on it is detected as an <i>unknown object</i> that you can assign a role to.
          </p>
          <button className="btn-ghost w-full" onClick={captureEmpty} disabled={!saved?.is_calibrated || busy}>
            Capture empty desk
          </button>
          {saved?.empty_desk_reference && (
            <div className="flex items-center justify-between text-xs text-emerald-300">
              <span>Reference captured</span>
              <button className="text-slate-400 hover:text-rose-300" onClick={clearEmpty}>
                <Trash2 className="inline h-3.5 w-3.5" /> clear
              </button>
            </div>
          )}
        </div>

        <div className="panel p-5">
          <div className="panel-title mb-2">Top-down preview</div>
          {saved?.is_calibrated ? (
            <img src="/api/stream?variant=warped" alt="Warped battlefield" className="w-full rounded-lg border border-line" />
          ) : (
            <p className="text-sm text-slate-400">Confirm the corners to see your desk flattened into the battlefield.</p>
          )}
          <p className="mt-2 text-xs text-slate-500">Recalibrate whenever the phone or desk moves.</p>
        </div>
      </div>
    </div>
  );
};
