import React from 'react';
import { useGameStore } from '../store/gameStore';

const STEPS = [
  ['Mount the iPhone', 'Fix your iPhone above the desk, rear camera pointing straight down, in landscape. Keep it still for the whole game.'],
  ['Connect the camera', 'Camera Setup lists every camera macOS reports. Pick “iPhone Camera” and confirm the live picture.'],
  ['Calibrate', 'Click the four corners of your play area. The battlefield is that rectangle, flattened from above.'],
  ['Place objects', 'Books → barriers, bottles/cups → towers, boxes → fortifications, pencil holders/phones → support. Unknown items can be assigned any role.'],
  ['Defend', 'Enemies spawn from the left, top and bottom and path around your obstacles to the core on the right. Move objects any time - routes update live.'],
  ['Spend credits', 'Kills earn credits. Upgrade structures, or use Orbital Strike (1), EMP (2) and Repair (3). Objects added mid-game cost credits to power up.'],
];

const ENEMIES = [
  ['Scout', 'Fast and fragile. Picks the entrance and route with the least tower coverage.'],
  ['Tank', 'Slow and tough. Takes the shortest route regardless of towers and smashes through walls.'],
  ['Saboteur', 'Hunts your most valuable tower and disables it for a few seconds, then heads for the core.'],
  ['Boss', 'Appears in waves 5 and 8. Huge health and crushes structures around it - focus fire with several towers.'],
];

export const HowToPlayPage: React.FC = () => {
  const setPage = useGameStore((s) => s.setPage);
  return (
    <div className="mx-auto max-w-6xl space-y-6 py-6">
      <h1 className="font-display text-3xl font-black text-white">How to play</h1>
      <div className="grid gap-4 md:grid-cols-3">
        {STEPS.map(([t, d], i) => (
          <div key={t} className="panel p-5">
            <div className="font-display text-sm font-bold text-cyan">0{i + 1}</div>
            <div className="mt-1 text-lg font-bold text-white">{t}</div>
            <p className="mt-1 text-sm leading-relaxed text-slate-300">{d}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="panel p-5">
          <div className="panel-title mb-3">Enemy tactics</div>
          {ENEMIES.map(([n, d]) => (
            <p key={n} className="mb-2 text-sm text-slate-300"><b className="text-rose-300">{n}:</b> {d}</p>
          ))}
          <p className="mt-3 text-sm text-slate-400">
            The enemy AI is deterministic: each enemy scores candidate routes by travel time and expected tower damage, and the
            director adjusts the next wave (within fixed limits) from how much damage your core took.
          </p>
        </div>
        <div className="panel p-5">
          <div className="panel-title mb-3">Tips</div>
          <ul className="space-y-2 text-sm text-slate-300">
            <li>• If you wall the core off completely, enemies attack your weakest barrier to break through.</li>
            <li>• Barriers slow enemies that squeeze past them - put towers next to the gap.</li>
            <li>• Support objects boost every tower within their violet aura.</li>
            <li>• Low-confidence detections are marked in amber; click them to fix the role or remove false ones.</li>
            <li>• Recalibrate if the phone moves - the game warns you when it detects a camera shift.</li>
          </ul>
          <button className="btn-primary mt-4" onClick={() => setPage('camera')}>Set up camera</button>
        </div>
      </div>
    </div>
  );
};
