import React from 'react';
import { ArrowRight, Lightbulb, LineChart, TrendingDown, TrendingUp, Minus } from 'lucide-react';
import { useGameStore } from '../store/gameStore';
import { act } from '../hooks/useGameSocket';
import { play } from '../utils/audio';
import type { WaveSummary } from '../types/game';

export const SummaryStats: React.FC<{ s: WaveSummary }> = ({ s }) => {
  const items: [string, string][] = [
    ['Enemies defeated', `${s.enemies_defeated} / ${s.enemies_total}`],
    ['Reached core', `${s.enemies_leaked}`],
    ['Damage received', `${s.damage_received}`],
    ['Core health', `${s.base_health_remaining} / ${s.base_health_max}`],
    ['Score earned', s.score_earned.toLocaleString()],
    ['Structures used', `${s.structures_used}`],
    ['Route length', `×${s.route_length_ratio.toFixed(2)}`],
    ['AI difficulty', `${s.ai_difficulty} (×${s.ai_difficulty_value})`],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k} className="rounded-xl border border-line bg-black/30 p-3">
          <div className="text-xs text-slate-400">{k}</div>
          <div className="mt-1 font-mono text-lg font-bold text-white">{v}</div>
        </div>
      ))}
    </div>
  );
};

export const WaveSummaryModal: React.FC = () => {
  const game = useGameStore((s) => s.game);
  if (!game || game.status !== 'wave_ended' || !game.last_summary) return null;
  const s = game.last_summary;
  const DiffIcon = s.difficulty_change === 'up' ? TrendingUp : s.difficulty_change === 'down' ? TrendingDown : Minus;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-3xl animate-fade-up space-y-5 p-6">
        <div className="flex items-end justify-between">
          <div>
            <div className="label">Wave report</div>
            <h2 className="font-display text-3xl font-black text-white">Wave {s.wave_number} cleared</h2>
          </div>
          <div className="text-right">
            <div className="label">Bonus</div>
            <div className="font-mono text-xl font-bold text-amber">+{s.wave_clear_bonus ?? 0}</div>
          </div>
        </div>
        <SummaryStats s={s} />
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-cyan/25 bg-cyan/5 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-bold text-cyan"><LineChart className="h-4 w-4" /> How your layout played out</div>
            <ul className="space-y-1.5 text-sm text-slate-200">{s.strategy_impact.map((t) => <li key={t}>• {t}</li>)}</ul>
          </div>
          <div className="rounded-xl border border-amber/25 bg-amber/5 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-bold text-amber"><Lightbulb className="h-4 w-4" /> Suggestions</div>
            <ul className="space-y-1.5 text-sm text-slate-200">{s.suggestions.map((t) => <li key={t}>• {t}</li>)}</ul>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-sm text-violet">
            <DiffIcon className="h-4 w-4" /> AI director {s.difficulty_change === 'up' ? 'raised' : s.difficulty_change === 'down' ? 'eased' : 'kept'} the difficulty
          </span>
          <span className="text-sm text-slate-400">Rearrange your desk now - the next wave starts when you are ready.</span>
          <button className="btn-primary" onClick={() => act('next_wave').then((a) => a.ok && play('wave'))}>
            Start wave {s.wave_number + 1} <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
