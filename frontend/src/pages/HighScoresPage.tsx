import React, { useEffect, useState } from 'react';
import { Trophy } from 'lucide-react';
import { api } from '../utils/api';
import type { HighScore } from '../types/game';

export const HighScoresPage: React.FC = () => {
  const [scores, setScores] = useState<HighScore[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api<HighScore[]>('/api/highscores').then(setScores).catch((e) => setErr(e.message));
  }, []);
  return (
    <div className="mx-auto max-w-4xl py-6">
      <div className="panel p-6">
        <div className="mb-4 flex items-center gap-2 font-display text-2xl font-black text-white"><Trophy className="h-6 w-6 text-amber" /> High scores</div>
        {err && <p className="text-rose-300">{err}</p>}
        {scores && scores.length === 0 && <p className="text-slate-400">No games finished yet - defend your desk to get on the board.</p>}
        {scores && scores.length > 0 && (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-slate-500">
              <tr><th className="py-2">#</th><th>Player</th><th className="text-right">Score</th><th className="text-right">Wave</th><th className="text-right">Kills</th><th>Result</th><th>Date</th></tr>
            </thead>
            <tbody>
              {scores.map((s, i) => (
                <tr key={i} className="border-t border-line">
                  <td className={`py-2.5 font-mono ${i < 3 ? 'text-amber' : 'text-slate-400'}`}>{i + 1}</td>
                  <td className="font-semibold text-white">{s.name}</td>
                  <td className="text-right font-mono text-cyan">{s.score.toLocaleString()}</td>
                  <td className="text-right font-mono">{s.wave}</td>
                  <td className="text-right font-mono">{s.kills}</td>
                  <td className={s.outcome === 'victory' ? 'text-emerald-300' : 'text-rose-300'}>{s.outcome}</td>
                  <td className="text-slate-400">{s.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
