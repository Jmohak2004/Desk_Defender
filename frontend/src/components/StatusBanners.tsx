import React from 'react';
import { AlertTriangle, Camera, Crosshair, FlaskConical, Move } from 'lucide-react';
import { useGameStore } from '../store/gameStore';

/** Prominent warnings that affect gameplay: camera trouble, moved camera, lost objects, sim mode. */
export const StatusBanners: React.FC = () => {
  const vision = useGameStore((s) => s.vision);
  const targeting = useGameStore((s) => s.targeting);
  const setPage = useGameStore((s) => s.setPage);
  const banners: { key: string; tone: string; icon: React.ElementType; text: React.ReactNode }[] = [];
  const cam = vision?.camera;
  if (cam && !cam.connected) {
    banners.push({
      key: 'cam',
      tone: 'border-rose-400/50 bg-rose-500/15 text-rose-100',
      icon: Camera,
      text: (
        <>
          {cam.state === 'reconnecting' ? 'Camera stream lost - reconnecting automatically. ' : 'No camera connected. '}
          {cam.error && <span className="opacity-80">{cam.error} </span>}
          <button className="underline" onClick={() => setPage('camera')}>Open Camera Setup</button>
        </>
      ),
    });
  }
  if (vision?.pipeline.camera_motion.state === 'moved') {
    banners.push({
      key: 'moved',
      tone: 'border-amber/60 bg-amber/15 text-amber',
      icon: Move,
      text: (
        <>
          The camera seems to have moved since calibration ({(vision.pipeline.camera_motion.shift * 100).toFixed(1)}% shift). Object positions may be off.{' '}
          <button className="underline" onClick={() => setPage('calibration')}>Recalibrate</button>
        </>
      ),
    });
  }
  const lost = vision?.objects.filter((o) => o.confirmed && o.is_stale) ?? [];
  if (lost.length) {
    banners.push({
      key: 'lost',
      tone: 'border-amber/40 bg-amber/10 text-amber',
      icon: AlertTriangle,
      text: `Lost sight of ${lost.map((o) => o.detected_class).join(', ')} - structure removed in ${Math.min(...lost.map((o) => o.removal_in ?? 0)).toFixed(1)}s unless it reappears.`,
    });
  }
  if (cam?.is_simulated) {
    banners.push({ key: 'sim', tone: 'border-amber/40 bg-amber/10 text-amber', icon: FlaskConical, text: 'SIMULATED development camera - detections come from a synthetic desk, not a real camera.' });
  }
  if (targeting) {
    banners.push({ key: 'target', tone: 'border-amber/60 bg-amber/20 text-amber', icon: Crosshair, text: 'Click the battlefield to fire the Orbital Strike (Esc to cancel).' });
  }
  if (!banners.length) return null;
  return (
    <div className="space-y-2">
      {banners.map(({ key, tone, icon: Icon, text }) => (
        <div key={key} className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium ${tone}`}>
          <Icon className="h-4 w-4 shrink-0" /> <span>{text}</span>
        </div>
      ))}
    </div>
  );
};
