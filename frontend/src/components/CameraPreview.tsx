import React, { useEffect, useState } from 'react';
import { Camera, FlaskConical, Smartphone, WifiOff } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import type { StreamVariant } from '../types/game';

/** Live MJPEG preview from the backend. One long-lived <img>, reconnected if the stream drops. */
export const CameraPreview: React.FC<{ variant?: StreamVariant; className?: string; showBadges?: boolean }> = ({
  variant = 'overlay',
  className = '',
  showBadges = true,
}) => {
  const camera = useGameStore((s) => s.vision?.camera);
  const pipeline = useGameStore((s) => s.vision?.pipeline);
  const [nonce, setNonce] = useState(0);
  const [failed, setFailed] = useState(false);
  const connected = camera?.connected ?? false;

  // Restart the stream when the camera (re)connects.
  useEffect(() => {
    setNonce((n) => n + 1);
    setFailed(false);
  }, [camera?.camera_id, connected]);

  useEffect(() => {
    if (!failed) return;
    const id = setTimeout(() => {
      setNonce((n) => n + 1);
      setFailed(false);
    }, 2000);
    return () => clearTimeout(id);
  }, [failed]);

  return (
    <div className={`relative overflow-hidden rounded-2xl border border-line bg-black ${className}`}>
      <img
        key={nonce}
        src={`/api/stream?variant=${variant}&n=${nonce}`}
        alt="Live desk camera"
        className="block aspect-video w-full object-contain"
        onError={() => setFailed(true)}
      />
      {showBadges && (
        <div className="absolute left-3 top-3 flex flex-wrap gap-2">
          {camera?.is_simulated ? (
            <span className="chip border-amber/50 bg-amber/20 text-amber">
              <FlaskConical className="h-3.5 w-3.5" /> SIMULATED CAMERA
            </span>
          ) : connected ? (
            <span className="chip border-emerald-400/40 bg-emerald-500/15 text-emerald-200">
              {camera?.is_continuity ? <Smartphone className="h-3.5 w-3.5" /> : <Camera className="h-3.5 w-3.5" />}
              {camera?.camera_name} · LIVE
            </span>
          ) : (
            <span className="chip border-rose-400/40 bg-rose-500/15 text-rose-200">
              <WifiOff className="h-3.5 w-3.5" /> {camera?.state === 'reconnecting' ? 'RECONNECTING' : 'NO CAMERA'}
            </span>
          )}
        </div>
      )}
      {showBadges && connected && (
        <div className="absolute bottom-3 left-3 flex gap-2 font-mono text-xs">
          <span className="rounded-md bg-black/70 px-2 py-1 text-cyan">cam {camera?.fps.toFixed(0)} fps</span>
          <span className="rounded-md bg-black/70 px-2 py-1 text-violet">detect {pipeline?.detection_fps.toFixed(1)} Hz</span>
          {camera?.resolution && (
            <span className="rounded-md bg-black/70 px-2 py-1 text-slate-300">{camera.resolution.join('×')}</span>
          )}
        </div>
      )}
    </div>
  );
};
