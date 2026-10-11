import React from 'react';
import { ArrowRight } from 'lucide-react';
import { CalibrationCanvas } from '../components/CalibrationCanvas';
import { useGameStore } from '../store/gameStore';

export const CalibrationPage: React.FC = () => {
  const setPage = useGameStore((s) => s.setPage);
  const calibrated = useGameStore((s) => s.vision?.calibration.is_calibrated ?? false);
  const connected = useGameStore((s) => s.vision?.camera.connected ?? false);
  return (
    <div className="mx-auto max-w-7xl space-y-5 py-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="label">Step 2 of 2</div>
          <h1 className="font-display text-3xl font-black text-white">Desk calibration</h1>
          <p className="mt-1 max-w-3xl text-slate-400">
            Click the four corners of the area you want to play on, clockwise from the top-left. A sheet of paper, desk mat or tape marks
            make this easy. The camera must stay fixed while you play - recalibrate if it moves.
          </p>
        </div>
        <button className="btn-primary" disabled={!calibrated} onClick={() => setPage('game')}>
          Go to battlefield <ArrowRight className="h-4 w-4" />
        </button>
      </div>
      {!connected && (
        <div className="rounded-xl border border-amber/40 bg-amber/10 p-4 text-sm text-amber">
          No live camera. <button className="underline" onClick={() => setPage('camera')}>Connect a camera first.</button>
        </div>
      )}
      <CalibrationCanvas />
    </div>
  );
};
