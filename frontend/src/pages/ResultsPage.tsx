import React, { useEffect, useState } from 'react';
import { Home, RotateCcw, Trophy } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import { act } from '../hooks/useGameSocket';
import { api } from '../utils/api';
import { SummaryStats } from '../components/WaveSummaryModal';
import type { HighScore } from '../types/game';

export const ResultsPage: React.FC = () => {
  const result = useGameStore((s) => s.game?.final_result);
  const setPage = useGameStore((s) => s.setPage);
  const playerName = useGameStore((s) => s.prefs.playerName);
  const [scores, setScores] = useState<HighScore[]>([]);

  useEffect(() => {
    api<HighScore[]>('/api/highscores').then(setScores).catch(() => {});
  }, [result?.score]);

  if (!result) {
    return (
      <div className="mx-auto max-w-xl py-20 text-center text-slate-400">
        No finished game yet. <button className="text-cyan underline" onClick={() => setPage('game')}>Go to the battlefield</button>
      </div>
    );
  }
  const win = result.outcome === 'victory';
  const rank = scores.findIndex((s) => s.score === result.score && s.name === result.player) + 1;

  return (
    <div className="mx-auto max-w-5xl space-y-6 py-6">
      <div className="panel p-8 text-center">
        <div className="label">{win ? 'All waves cleared' : `Core destroyed on wave ${result.wave_reached}`}</div>
        <h1 className={`mt-2 font-display text-6xl font-black ${win ? 'text-cyan' : 'text-rose-400'} neon-text`}>{win ? 'VICTORY' : 'DEFEAT'}</h1>
        <div className="mt-4 font-mono text-4xl font-bold text-white">{result.score.toLocaleString()}</div>
        <div className="text-slate-400">
          {result.kills} kills · wave {result.wave_reached}/{result.total_waves} · final AI difficulty ×{result.difficulty}
          {rank > 0 && <span className="text-amber"> · #{rank} on the leaderboard</span>}
        </div>
        <div className="mt-6 flex justify-center gap-3">
          <button className="btn-primary" onClick={() => act('restart', { player_name: playerName }).then((a) => a.ok && setPage('game'))}>
            <RotateCcw className="h-4 w-4" /> Play again
          </button>
          <button className="btn-ghost" onClick={() => setPage('scores')}><Trophy className="h-4 w-4" /> High scores</button>
          <button className="btn-ghost" onClick={() => setPage('home')}><Home className="h-4 w-4" /> Home</button>
        </div>
      </div>
      {result.waves.map((w) => (
        <div key={w.wave_number} className="panel space-y-3 p-5">
          <div className="panel-title">Wave {w.wave_number}</div>
          <SummaryStats s={w} />
          <ul className="space-y-1 text-sm text-slate-300">{w.strategy_impact.map((t) => <li key={t}>• {t}</li>)}</ul>
        </div>
      ))}
    </div>
  );
};
