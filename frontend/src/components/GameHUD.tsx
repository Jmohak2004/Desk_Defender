import React from 'react';
import { Bug, Coins, Crosshair, DoorOpen, Gauge, HeartPulse, LayoutPanelLeft, Pause, Play, RotateCcw, Shield, Swords, Trophy, Video, Zap } from 'lucide-react';
import { useGameStore, type ViewMode } from '../store/gameStore';
import { act } from '../hooks/useGameSocket';
import { play } from '../utils/audio';
import type { AbilityName } from '../types/game';

const ABILITY_ICON: Record<AbilityName, React.ElementType> = { strike: Crosshair, emp: Zap, repair: HeartPulse };
const ABILITY_KEY: Record<AbilityName, string> = { strike: '1', emp: '2', repair: '3' };
const ABILITY_SHORT: Record<AbilityName, string> = { strike: 'Strike', emp: 'EMP', repair: 'Repair' };

export const GameHUD: React.FC = () => {
  const game = useGameStore((s) => s.game);
  const viewMode = useGameStore((s) => s.viewMode);
  const setViewMode = useGameStore((s) => s.setViewMode);
  const toggleDebug = useGameStore((s) => s.toggleDebug);
  const targeting = useGameStore((s) => s.targeting);
  const setTargeting = useGameStore((s) => s.setTargeting);
  const setPage = useGameStore((s) => s.setPage);
  const playerName = useGameStore((s) => s.prefs.playerName);

  const status = game?.status ?? 'idle';
  const hp = game ? game.base.health / game.base.max_health : 1;
  const wp = game?.wave_progress;

  const start = () => act('start', { player_name: playerName }).then((a) => a.ok && play('wave'));
  const useAbility = (name: AbilityName) => {
    if (name === 'strike') {
      setTargeting(targeting === 'strike' ? null : 'strike');
      return;
    }
    act('ability', { ability: name });
  };

  return (
    <div className="panel flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3">
      <div className="min-w-[210px] flex-1">
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="flex items-center gap-1.5 font-semibold text-slate-200"><Shield className="h-4 w-4 text-cyan" /> Core integrity</span>
          <span className={`font-mono font-bold ${hp > 0.5 ? 'text-cyan' : hp > 0.25 ? 'text-amber' : 'text-rose-400'}`}>
            {Math.round(game?.base.health ?? 100)} / {game?.base.max_health ?? 100}
          </span>
        </div>
        <div className="h-3 overflow-hidden rounded-full border border-line bg-black/50">
          <div
            className={`h-full transition-all duration-300 ${hp > 0.5 ? 'bg-gradient-to-r from-cyan to-violet' : hp > 0.25 ? 'bg-amber' : 'bg-rose-500'}`}
            style={{ width: `${hp * 100}%` }}
          />
        </div>
      </div>

      <Stat icon={Swords} label="Wave" value={`${game?.wave || '–'} / ${game?.total_waves ?? 8}`} sub={wp && status === 'running' ? `${wp.killed + wp.leaked}/${wp.total} resolved` : undefined} />
      <Stat icon={Trophy} label="Score" value={(game?.score ?? 0).toLocaleString()} />
      <Stat icon={Coins} label="Credits" value={`${game?.credits ?? 0}¢`} accent="text-amber" />
      <Stat icon={Gauge} label="AI director" value={game?.difficulty.label ?? 'Balanced'} sub={game ? `×${game.difficulty.value.toFixed(2)}` : undefined} accent="text-violet" />

      <div className="flex items-center gap-2">
        {game &&
          (Object.keys(game.abilities) as AbilityName[]).map((name) => {
            const ab = game.abilities[name];
            const Icon = ABILITY_ICON[name];
            const ready = ab.ready_in <= 0 && game.credits >= ab.cost && status === 'running';
            const pct = ab.ready_in > 0 ? ab.ready_in / ab.cooldown : 0;
            return (
              <button
                key={name}
                onClick={() => useAbility(name)}
                disabled={!ready}
                title={`${ab.label} — ${ab.cost}¢ (key ${ABILITY_KEY[name]})`}
                className={`relative flex h-14 w-[86px] flex-col items-center justify-center overflow-hidden rounded-xl border text-xs font-semibold transition ${
                  targeting === name ? 'border-amber bg-amber/25 text-amber' : 'border-line bg-white/[0.04] text-slate-100 hover:bg-white/10'
                } disabled:opacity-40`}
              >
                <div className="absolute inset-x-0 bottom-0 bg-white/10" style={{ height: `${pct * 100}%` }} />
                <Icon className="h-4 w-4" />
                <span>{ABILITY_SHORT[name]}</span>
                <span className="font-mono text-[11px] text-amber">{ab.ready_in > 0 ? `${ab.ready_in.toFixed(0)}s` : `${ab.cost}¢`}</span>
              </button>
            );
          })}
      </div>

      <div className="flex items-center gap-2">
        {(status === 'idle' || status === 'game_over' || status === 'victory') && (
          <button className="btn-primary" onClick={start}>
            <Play className="h-4 w-4" /> {status === 'idle' ? 'Start' : 'Play again'}
          </button>
        )}
        {status === 'running' && (
          <button className="btn-ghost" onClick={() => act('pause')}>
            <Pause className="h-4 w-4" /> Pause
          </button>
        )}
        {status === 'paused' && (
          <button className="btn-primary" onClick={() => act('resume')}>
            <Play className="h-4 w-4" /> Resume
          </button>
        )}
        {status !== 'idle' && (
          <button className="btn-ghost" onClick={() => act('restart', { player_name: playerName })} title="Restart from wave 1">
            <RotateCcw className="h-4 w-4" />
          </button>
        )}
        {status !== 'idle' && (
          <button className="btn-ghost" onClick={() => { act('exit'); setPage('home'); }} title="Exit to menu">
            <DoorOpen className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 rounded-xl border border-line bg-black/30 p-1">
        {([['split', LayoutPanelLeft, 'Split'], ['battlefield', Swords, 'Battle'], ['camera', Video, 'Camera']] as [ViewMode, React.ElementType, string][]).map(
          ([m, Icon, label]) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold ${viewMode === m ? 'bg-cyan/20 text-cyan' : 'text-slate-400 hover:text-white'}`}
            >
              <Icon className="h-4 w-4" /> {label}
            </button>
          ),
        )}
        <button onClick={toggleDebug} className="rounded-lg px-2 py-1.5 text-slate-400 hover:text-white" title="Debug overlay (D)">
          <Bug className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};

const Stat: React.FC<{ icon: React.ElementType; label: string; value: string; sub?: string; accent?: string }> = ({ icon: Icon, label, value, sub, accent }) => (
  <div className="min-w-[96px]">
    <div className="label flex items-center gap-1"><Icon className="h-3.5 w-3.5" /> {label}</div>
    <div className={`stat-value ${accent ?? ''}`}>{value}</div>
    {sub && <div className="font-mono text-xs text-slate-500">{sub}</div>}
  </div>
);
