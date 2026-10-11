import React, { useEffect, useRef } from 'react';
import { useGameStore } from '../store/gameStore';
import { onGameEvents, sendAction, sendRaw } from '../hooks/useGameSocket';
import { ParticleSystem } from '../utils/particles';
import { eventToLogical } from '../utils/coordinateMapping';
import { play } from '../utils/audio';
import { api } from '../utils/api';
import type { Enemy, GameEvent, Structure, StructureRole } from '../types/game';

const W = 1000;
const H = 700;

export const ROLE_STYLE: Record<StructureRole, { color: string; dark: string; label: string; height: number }> = {
  barrier: { color: '#fbbf24', dark: '#92400e', label: 'Barrier', height: 16 },
  heavy_fortification: { color: '#fb923c', dark: '#7c2d12', label: 'Fortification', height: 26 },
  defense_tower: { color: '#22d3ee', dark: '#155e75', label: 'Tower', height: 22 },
  support_tower: { color: '#a78bfa', dark: '#4c1d95', label: 'Support', height: 20 },
  custom: { color: '#e2e8f0', dark: '#475569', label: 'Custom', height: 18 },
};

const ENEMY_COLOR: Record<string, string> = { scout: '#fb7185', tank: '#f43f5e', saboteur: '#e879f9', boss: '#ef4444' };
const INTENT_COLOR: Record<string, string> = {
  advancing: 'rgba(251,113,133,0.55)',
  flanking: 'rgba(167,139,250,0.65)',
  breaching: 'rgba(251,191,36,0.75)',
  sabotaging: 'rgba(232,121,249,0.75)',
};

interface Smooth { x: number; y: number; w?: number; h?: number }

function lerp(a: number, b: number, k: number) {
  return a + (b - a) * k;
}

export const Battlefield: React.FC<{ compact?: boolean }> = ({ compact }) => {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particles = useRef(new ParticleSystem());
  const smooth = useRef({ enemies: new Map<string, Smooth>(), structures: new Map<string, Smooth>(), proj: new Map<string, Smooth>() });
  const dragRef = useRef<{ id: string; last: number } | null>(null);
  const hoverRef = useRef<[number, number] | null>(null);
  const threatRef = useRef<{ version: number; data: { cols: number; rows: number; cell: number; threat: number[] } | null }>({ version: -1, data: null });

  const prefs = useGameStore((s) => s.prefs);
  const calibrated = useGameStore((s) => s.vision?.calibration.is_calibrated ?? false);
  const targeting = useGameStore((s) => s.targeting);
  const simDrag = useGameStore((s) => s.simDrag);
  const isSim = useGameStore((s) => s.vision?.camera.is_simulated ?? false);

  // Gameplay events -> particles + sound.
  useEffect(() => {
    return onGameEvents((events: GameEvent[]) => {
      const p = particles.current;
      for (const ev of events) {
        const x = Number(ev.x ?? 0);
        const y = Number(ev.y ?? 0);
        switch (ev.type) {
          case 'enemy_killed': {
            const boss = ev.etype === 'boss';
            p.burst(x, y, ENEMY_COLOR[String(ev.etype)] ?? '#fb7185', boss ? 60 : 18, boss ? 260 : 170, boss ? 5 : 3);
            p.ring(x, y, '#fde68a', boss ? 120 : 34, 0.45);
            if (Number(ev.reward) > 0) p.text(x, y - 14, `+${ev.reward}`, '#fde68a');
            play(boss ? 'boss_kill' : 'kill');
            if (boss) p.shake = 14;
            break;
          }
          case 'hit':
            p.burst(x, y, ev.k === 'heavy' ? '#e9d5ff' : '#a5f3fc', 4, 110, 2, 0.3);
            play('shoot');
            break;
          case 'base_hit':
            p.ring(x, y, '#fb7185', 90, 0.6);
            p.burst(x, y, '#fb7185', 24, 220, 3);
            p.shake = 12;
            play('base_hit');
            break;
          case 'structure_destroyed':
            p.debris(x, y, '#fbbf24', 22);
            p.ring(x, y, '#fb923c', 80);
            p.shake = 8;
            play('destroyed');
            break;
          case 'strike':
            p.flash(x, y, 'rgba(254,240,138,0.9)', Number(ev.radius) * 1.3);
            p.ring(x, y, '#fde047', Number(ev.radius) * 1.2, 0.7);
            p.burst(x, y, '#fde047', 40, 300, 4, 0.8);
            p.shake = 10;
            play('strike');
            break;
          case 'emp':
            p.ring(W / 2, H / 2, '#67e8f9', 900, 1.0);
            p.ring(W / 2, H / 2, '#a78bfa', 650, 0.8);
            play('emp');
            break;
          case 'repair':
            for (const s of useGameStore.getState().game?.structures ?? []) p.burst(s.x, s.y, '#6ee7b7', 8, 70, 3, 0.9);
            p.ring(x, y, '#6ee7b7', 120);
            play('repair');
            break;
          case 'sabotage':
            p.ring(x, y, '#e879f9', 60, 0.6);
            p.burst(x, y, '#e879f9', 16, 140, 2);
            play('sabotage');
            break;
          case 'structure_added':
          case 'structure_activated':
            p.ring(x, y, '#67e8f9', 70, 0.7);
            play('place');
            break;
          case 'role_changed':
            p.ring(x, y, '#a78bfa', 60, 0.6);
            break;
          case 'enemy_spawned':
            p.ring(x, y, '#fb7185', 36, 0.5);
            break;
        }
      }
    });
  }, []);

  // Threat heatmap (debug view) - refetched when the nav grid changes.
  useEffect(() => {
    if (!prefs.showThreat) return;
    const id = window.setInterval(async () => {
      const v = useGameStore.getState().game?.nav.version ?? -1;
      if (v === threatRef.current.version) return;
      try {
        const data = await api<{ cols: number; rows: number; cell: number; threat: number[] }>('/api/game/nav');
        threatRef.current = { version: v, data };
      } catch {
        /* backend busy - try next tick */
      }
    }, 700);
    return () => clearInterval(id);
  }, [prefs.showThreat]);

  // Render loop - reads the store directly so React does not re-render at 60 Hz.
  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext('2d')!;
    let raf = 0;
    let last = performance.now();
    let fpsAcc = 0;
    let fpsN = 0;

    const resize = () => {
      const wrap = wrapRef.current;
      if (!wrap) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const cssW = wrap.clientWidth;
      const cssH = (cssW * H) / W;
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      canvas.style.height = `${cssH}px`;
    };
    resize();
    const ro = new ResizeObserver(resize);
    if (wrapRef.current) ro.observe(wrapRef.current);

    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      fpsAcc += dt;
      fpsN++;
      if (fpsAcc >= 1) {
        (window as unknown as { __renderFps: number }).__renderFps = fpsN / fpsAcc;
        fpsAcc = 0;
        fpsN = 0;
      }
      draw(ctx, canvas, dt, now / 1000);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  function draw(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, dt: number, t: number) {
    const st = useGameStore.getState();
    const game = st.game;
    const prefsNow = st.prefs;
    const p = particles.current;
    p.update(dt);

    const scale = canvas.width / W;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const sx = p.shake ? (Math.random() - 0.5) * p.shake : 0;
    const sy = p.shake ? (Math.random() - 0.5) * p.shake : 0;
    ctx.setTransform(scale, 0, 0, scale, sx * scale, sy * scale);

    // Background: translucent so the warped desk image underneath shows through.
    const showDesk = prefsNow.showDeskTexture && st.vision?.calibration.is_calibrated;
    ctx.fillStyle = showDesk ? 'rgba(5,8,16,0.72)' : '#070b14';
    ctx.fillRect(-20, -20, W + 40, H + 40);
    ctx.strokeStyle = 'rgba(148,163,184,0.07)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= W; x += 50) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    for (let y = 0; y <= H; y += 50) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    ctx.strokeStyle = 'rgba(34,211,238,0.35)';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, W - 2, H - 2);

    if (prefsNow.showThreat && threatRef.current.data) {
      const d = threatRef.current.data;
      const max = Math.max(1, ...d.threat);
      for (let i = 0; i < d.threat.length; i++) {
        if (d.threat[i] <= 0) continue;
        const r = Math.floor(i / d.cols);
        const c = i % d.cols;
        ctx.fillStyle = `rgba(239,68,68,${(0.35 * d.threat[i]) / max})`;
        ctx.fillRect(c * d.cell, r * d.cell, d.cell, d.cell);
      }
    }

    if (!game) {
      ctx.fillStyle = '#94a3b8';
      ctx.font = '600 22px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('Connecting to game server...', W / 2, H / 2);
      return;
    }

    // Spawn portals
    for (const [x, y] of game.spawn_points) {
      const pulse = 4 * Math.sin(t * 3 + x + y);
      const g = ctx.createRadialGradient(x, y, 2, x, y, 34 + pulse);
      g.addColorStop(0, 'rgba(251,113,133,0.55)');
      g.addColorStop(1, 'rgba(251,113,133,0)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, 34 + pulse, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(251,113,133,0.8)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, 14, t * 2, t * 2 + Math.PI * 1.3);
      ctx.stroke();
    }

    // Smooth structure positions (animates physical moves).
    const sMap = smooth.current.structures;
    const kS = 1 - Math.exp(-dt * 7);
    const seenS = new Set<string>();
    for (const s of game.structures) {
      seenS.add(s.id);
      const cur = sMap.get(s.id);
      if (!cur) sMap.set(s.id, { x: s.x, y: s.y, w: s.w, h: s.h });
      else {
        cur.x = lerp(cur.x, s.x, kS);
        cur.y = lerp(cur.y, s.y, kS);
        cur.w = lerp(cur.w!, s.w, kS);
        cur.h = lerp(cur.h!, s.h, kS);
      }
    }
    for (const id of sMap.keys()) if (!seenS.has(id)) sMap.delete(id);

    const selected = st.selectedObjectId;

    // Aura / range rings
    for (const s of game.structures) {
      const pos = sMap.get(s.id)!;
      const isSel = s.object_id === selected;
      if (!s.active || s.destroyed) continue;
      if (s.behavior === 'support' && (prefsNow.showRanges || isSel)) {
        ctx.fillStyle = 'rgba(167,139,250,0.06)';
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, s.buff_radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = 'rgba(167,139,250,0.35)';
        ctx.setLineDash([6, 8]);
        ctx.lineDashOffset = -t * 15;
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (s.behavior === 'attack' && (prefsNow.showRanges || isSel)) {
        ctx.strokeStyle = isSel ? 'rgba(103,232,249,0.8)' : 'rgba(34,211,238,0.16)';
        ctx.lineWidth = isSel ? 2 : 1;
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, s.range, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    // Buff links
    for (const sup of game.structures) {
      if (sup.behavior !== 'support' || !sup.active || sup.destroyed) continue;
      const a = sMap.get(sup.id)!;
      for (const tw of game.structures) {
        if (!tw.buffed) continue;
        const b = sMap.get(tw.id)!;
        if (Math.hypot(a.x - b.x, a.y - b.y) > sup.buff_radius) continue;
        ctx.strokeStyle = 'rgba(167,139,250,0.55)';
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 6]);
        ctx.lineDashOffset = -t * 30;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Enemy smoothing
    const eMap = smooth.current.enemies;
    const kE = 1 - Math.exp(-dt * 16);
    const seenE = new Set<string>();
    for (const e of game.enemies) {
      seenE.add(e.id);
      const cur = eMap.get(e.id);
      if (!cur) eMap.set(e.id, { x: e.x, y: e.y });
      else {
        cur.x = lerp(cur.x, e.x, kE);
        cur.y = lerp(cur.y, e.y, kE);
      }
    }
    for (const id of eMap.keys()) if (!seenE.has(id)) eMap.delete(id);

    // Paths
    if (prefsNow.showPaths) {
      for (const e of game.enemies) {
        if (!e.path.length) continue;
        const pos = eMap.get(e.id)!;
        ctx.strokeStyle = INTENT_COLOR[e.intent] ?? 'rgba(255,255,255,0.25)';
        ctx.lineWidth = e.type === 'boss' ? 3 : 1.6;
        ctx.setLineDash([5, 7]);
        ctx.lineDashOffset = -t * 40;
        ctx.beginPath();
        ctx.moveTo(pos.x, pos.y);
        for (const [x, y] of e.path) ctx.lineTo(x, y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // Structures (2.5D, painter's order by y)
    const ordered = [...game.structures].sort((a, b) => a.y - b.y);
    for (const s of ordered) drawStructure(ctx, s, sMap.get(s.id)!, t, s.object_id === selected);

    drawBase(ctx, game.base, t);

    for (const e of [...game.enemies].sort((a, b) => a.y - b.y)) drawEnemy(ctx, e, eMap.get(e.id)!, t);

    // Projectiles
    const pMap = smooth.current.proj;
    const seenP = new Set<string>();
    for (const pr of game.projectiles) {
      seenP.add(pr.id);
      const cur = pMap.get(pr.id);
      const pos = cur ? { x: lerp(cur.x, pr.x, kE), y: lerp(cur.y, pr.y, kE) } : { x: pr.x, y: pr.y };
      pMap.set(pr.id, pos);
      const ang = Math.atan2(pr.ty - pos.y, pr.tx - pos.x);
      const heavy = pr.k === 'heavy';
      ctx.strokeStyle = heavy ? 'rgba(233,213,255,0.9)' : 'rgba(165,243,252,0.9)';
      ctx.lineWidth = heavy ? 4 : 2.5;
      ctx.shadowColor = heavy ? '#c084fc' : '#22d3ee';
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.moveTo(pos.x - Math.cos(ang) * 14, pos.y - Math.sin(ang) * 14);
      ctx.lineTo(pos.x, pos.y);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    for (const id of pMap.keys()) if (!seenP.has(id)) pMap.delete(id);

    p.draw(ctx);

    // Simulated object handles (dev mode only)
    if (st.simDrag && st.vision?.camera.is_simulated && st.vision.sim_objects) {
      for (const o of st.vision.sim_objects) {
        ctx.strokeStyle = 'rgba(251,191,36,0.95)';
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 2;
        ctx.strokeRect(o.x - o.w / 2, o.y - o.h / 2, o.w, o.h);
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(251,191,36,0.95)';
        ctx.font = '600 12px Inter';
        ctx.textAlign = 'center';
        ctx.fillText(`SIM ${o.kind}`, o.x, o.y - o.h / 2 - 6);
      }
    }

    // Ability targeting reticle
    const hover = hoverRef.current;
    if (st.targeting === 'strike' && hover && game.abilities.strike) {
      const r = game.abilities.strike.radius;
      ctx.strokeStyle = '#fde047';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 6]);
      ctx.lineDashOffset = -t * 30;
      ctx.beginPath();
      ctx.arc(hover[0], hover[1], r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(253,224,71,0.12)';
      ctx.fill();
    }

    // Status overlays
    if (game.status === 'paused' || game.status === 'idle') {
      ctx.fillStyle = 'rgba(5,7,13,0.55)';
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#e2e8f0';
      ctx.textAlign = 'center';
      ctx.font = '800 44px Orbitron';
      ctx.fillText(game.status === 'paused' ? 'PAUSED' : 'ARRANGE YOUR DESK', W / 2, H / 2 - 6);
      ctx.font = '500 18px Inter';
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(game.status === 'paused' ? 'Press Space or Resume to continue' : 'Place books, bottles, cups and boxes, then press Start', W / 2, H / 2 + 30);
    }
    if (game.nav.no_path && game.status === 'running') {
      ctx.fillStyle = 'rgba(251,191,36,0.9)';
      ctx.font = '700 15px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('Core fully walled off - enemies are breaching your weakest barrier!', W / 2, 26);
    }
  }

  // ---------------------------------------------------------------- input
  const toLogical = (e: React.PointerEvent) => eventToLogical(e, canvasRef.current!, W, H);

  const onPointerDown = async (e: React.PointerEvent) => {
    const [x, y] = toLogical(e);
    const st = useGameStore.getState();
    if (st.targeting) {
      const ability = st.targeting;
      st.setTargeting(null);
      const ack = await sendAction('ability', { ability, x, y });
      if (!ack.ok) st.toast('warning', ack.message);
      return;
    }
    if (st.simDrag && st.vision?.camera.is_simulated) {
      const hit = st.vision.sim_objects?.find((o) => Math.abs(o.x - x) <= o.w / 2 + 6 && Math.abs(o.y - y) <= o.h / 2 + 6);
      if (hit) {
        dragRef.current = { id: hit.id, last: 0 };
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        return;
      }
    }
    const hit = [...(st.game?.structures ?? [])]
      .reverse()
      .find((s) => Math.abs(s.x - x) <= Math.max(s.w / 2, 18) + 4 && Math.abs(s.y - y) <= Math.max(s.h / 2, 18) + 4);
    st.select(hit ? hit.object_id : null);
    if (hit) play('click');
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const pt = toLogical(e);
    hoverRef.current = pt;
    const d = dragRef.current;
    if (d) {
      const now = performance.now();
      if (now - d.last > 50) {
        d.last = now;
        sendRaw('sim_move', { sim_id: d.id, x: Math.max(0, Math.min(W, pt[0])), y: Math.max(0, Math.min(H, pt[1])) });
      }
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (d) {
      const [x, y] = toLogical(e);
      sendRaw('sim_move', { sim_id: d.id, x: Math.max(0, Math.min(W, x)), y: Math.max(0, Math.min(H, y)) });
      dragRef.current = null;
    }
  };

  const cursor = targeting ? 'crosshair' : simDrag && isSim ? 'grab' : 'pointer';

  return (
    <div ref={wrapRef} className={`relative w-full overflow-hidden rounded-2xl border border-cyan/25 bg-abyss shadow-glow ${compact ? '' : ''}`}>
      {prefs.showDeskTexture && calibrated && (
        <img src="/api/stream?variant=warped" alt="" className="pointer-events-none absolute inset-0 h-full w-full object-fill opacity-60 saturate-50" />
      )}
      <canvas
        ref={canvasRef}
        className="relative block w-full touch-none select-none"
        style={{ cursor }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => (hoverRef.current = null)}
      />
    </div>
  );
};

// ------------------------------------------------------------------ drawing helpers
function drawStructure(ctx: CanvasRenderingContext2D, s: Structure, pos: Smooth, t: number, selected: boolean) {
  const style = ROLE_STYLE[s.role] ?? ROLE_STYLE.custom;
  const w = Math.max(24, pos.w ?? s.w);
  const h = Math.max(24, pos.h ?? s.h);
  const x = pos.x;
  const y = pos.y;
  const offline = !s.active || s.destroyed;
  const disabled = s.disabled_for > 0;
  const color = s.destroyed ? '#57534e' : !s.active ? '#64748b' : style.color;
  const dark = s.destroyed ? '#292524' : !s.active ? '#334155' : style.dark;
  const H3 = s.destroyed ? 4 : style.height;

  ctx.save();
  ctx.globalAlpha = s.stale ? 0.45 + 0.25 * Math.sin(t * 8) : 1;

  // drop shadow
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  ctx.beginPath();
  ctx.ellipse(x + 6, y + h / 2 + 2, w / 2 + 4, Math.max(8, h * 0.18), 0, 0, Math.PI * 2);
  ctx.fill();

  if (s.behavior === 'block') {
    // extruded block: front face + top face
    ctx.fillStyle = dark;
    ctx.fillRect(x - w / 2, y + h / 2 - H3, w, H3);
    ctx.fillStyle = color;
    ctx.globalAlpha *= 0.92;
    roundRect(ctx, x - w / 2, y - h / 2 - H3, w, h, 6);
    ctx.fill();
    ctx.globalAlpha = s.stale ? 0.5 : 1;
    if (!s.destroyed) {
      ctx.save();
      roundRect(ctx, x - w / 2, y - h / 2 - H3, w, h, 6);
      ctx.clip();
      ctx.strokeStyle = 'rgba(0,0,0,0.18)';
      ctx.lineWidth = 6;
      for (let k = -h; k < w + h; k += 18) {
        ctx.beginPath();
        ctx.moveTo(x - w / 2 + k, y - h / 2 - H3);
        ctx.lineTo(x - w / 2 + k - h, y + h / 2 - H3);
        ctx.stroke();
      }
      ctx.restore();
    } else {
      ctx.fillStyle = '#a8a29e';
      for (let k = 0; k < 6; k++) ctx.fillRect(x - w / 2 + ((k * 37) % w), y - h / 2 + ((k * 23) % h) - H3, 6, 5);
    }
    ctx.strokeStyle = selected ? '#ffffff' : 'rgba(255,255,255,0.35)';
    ctx.lineWidth = selected ? 3 : 1.2;
    roundRect(ctx, x - w / 2, y - h / 2 - H3, w, h, 6);
    ctx.stroke();
  } else {
    // cylinder tower
    const r = Math.max(16, Math.min(w, h) / 2);
    ctx.fillStyle = dark;
    ctx.fillRect(x - r, y - H3, r * 2, H3);
    ctx.beginPath();
    ctx.ellipse(x, y, r, r * 0.55, 0, 0, Math.PI);
    ctx.fill();
    const g = ctx.createRadialGradient(x - r * 0.3, y - H3 - r * 0.3, 2, x, y - H3, r);
    g.addColorStop(0, '#ffffff');
    g.addColorStop(0.25, color);
    g.addColorStop(1, dark);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(x, y - H3, r, r * 0.55, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = selected ? '#ffffff' : 'rgba(255,255,255,0.45)';
    ctx.lineWidth = selected ? 3 : 1.2;
    ctx.stroke();
    if (s.behavior === 'attack' && !offline) {
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 7;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x, y - H3);
      ctx.lineTo(x + Math.cos(s.aim) * (r + 8), y - H3 + Math.sin(s.aim) * (r + 8) * 0.55);
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.lineCap = 'butt';
    }
    if (s.behavior === 'support' && !offline) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      for (let k = 0; k < 3; k++) {
        ctx.globalAlpha = 0.5 + 0.5 * Math.sin(t * 4 + k);
        ctx.beginPath();
        ctx.ellipse(x, y - H3 - 6 - k * 6, r * (0.8 - k * 0.2), r * 0.3, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }

  // Health bar
  const frac = Math.max(0, s.health / s.max_health);
  const bw = Math.max(36, Math.min(80, w));
  const by = y - h / 2 - H3 - 14;
  ctx.fillStyle = 'rgba(0,0,0,0.65)';
  ctx.fillRect(x - bw / 2, by, bw, 5);
  ctx.fillStyle = frac > 0.5 ? '#34d399' : frac > 0.25 ? '#fbbf24' : '#fb7185';
  ctx.fillRect(x - bw / 2, by, bw * frac, 5);

  // Labels
  ctx.textAlign = 'center';
  ctx.font = '700 12px Inter';
  ctx.fillStyle = '#f8fafc';
  ctx.shadowColor = 'rgba(0,0,0,0.9)';
  ctx.shadowBlur = 4;
  const lvl = s.level > 1 ? ` ★${s.level}` : '';
  ctx.fillText(`${s.detected_class}${lvl}`, x, y + h / 2 + 16);
  ctx.font = '600 11px "JetBrains Mono"';
  ctx.fillStyle = style.color;
  const tag = s.destroyed ? 'DESTROYED' : !s.active ? `OFFLINE · needs ${s.cost}¢` : disabled ? `SABOTAGED ${s.disabled_for.toFixed(1)}s` : s.stale ? 'TRACKING LOST' : `${style.label} · ${Math.round(s.confidence * 100)}%`;
  ctx.fillStyle = s.destroyed || disabled ? '#fb7185' : !s.active || s.stale ? '#fbbf24' : style.color;
  ctx.fillText(tag, x, y + h / 2 + 30);
  ctx.shadowBlur = 0;
  if (disabled && !s.destroyed) {
    ctx.strokeStyle = '#e879f9';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let k = 0; k < 5; k++) {
      const a = t * 9 + k * 1.3;
      ctx.moveTo(x + Math.cos(a) * 10, y - H3 + Math.sin(a) * 6);
      ctx.lineTo(x + Math.cos(a + 0.6) * 26, y - H3 + Math.sin(a + 0.6) * 14);
    }
    ctx.stroke();
  }
  ctx.restore();
}

function drawBase(ctx: CanvasRenderingContext2D, b: { x: number; y: number; radius: number; health: number; max_health: number }, t: number) {
  const frac = Math.max(0, b.health / b.max_health);
  const pulse = 1 + 0.06 * Math.sin(t * 4);
  const g = ctx.createRadialGradient(b.x, b.y, 4, b.x, b.y, b.radius * 2.2);
  g.addColorStop(0, frac > 0.3 ? 'rgba(103,232,249,0.6)' : 'rgba(251,113,133,0.6)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(b.x, b.y, b.radius * 2.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#0b1220';
  ctx.strokeStyle = '#67e8f9';
  ctx.lineWidth = 3;
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    const r = b.radius * pulse;
    if (i === 0) ctx.moveTo(b.x + Math.cos(a) * r, b.y + Math.sin(a) * r);
    else ctx.lineTo(b.x + Math.cos(a) * r, b.y + Math.sin(a) * r);
  }
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.strokeStyle = 'rgba(167,139,250,0.9)';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.arc(b.x, b.y, b.radius * 0.6, -t * 2, -t * 2 + Math.PI * 1.3);
  ctx.stroke();
  ctx.fillStyle = '#e0f2fe';
  ctx.beginPath();
  ctx.arc(b.x, b.y, 8 + 2 * Math.sin(t * 6), 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = 'rgba(0,0,0,0.7)';
  ctx.fillRect(b.x - 40, b.y + b.radius + 10, 80, 7);
  ctx.fillStyle = frac > 0.5 ? '#22d3ee' : frac > 0.25 ? '#fbbf24' : '#fb7185';
  ctx.fillRect(b.x - 40, b.y + b.radius + 10, 80 * frac, 7);
  ctx.font = '800 12px Orbitron';
  ctx.textAlign = 'center';
  ctx.fillStyle = '#e0f2fe';
  ctx.fillText('CORE', b.x, b.y + b.radius + 32);
}

function drawEnemy(ctx: CanvasRenderingContext2D, e: Enemy, pos: Smooth, t: number) {
  const color = ENEMY_COLOR[e.type] ?? '#fb7185';
  const r = e.r;
  const bob = Math.sin(t * 8 + e.x * 0.05) * 1.5;
  const x = pos.x;
  const y = pos.y - 4 + bob;
  ctx.save();
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  ctx.beginPath();
  ctx.ellipse(pos.x + 3, pos.y + r * 0.6, r, r * 0.4, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.translate(x, y);
  ctx.shadowColor = color;
  ctx.shadowBlur = e.type === 'boss' ? 24 : 10;
  ctx.fillStyle = e.stunned ? '#67e8f9' : color;
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  if (e.type === 'scout') {
    ctx.rotate(e.heading);
    ctx.moveTo(r * 1.3, 0);
    ctx.lineTo(-r * 0.9, r * 0.85);
    ctx.lineTo(-r * 0.4, 0);
    ctx.lineTo(-r * 0.9, -r * 0.85);
    ctx.closePath();
  } else if (e.type === 'tank') {
    ctx.rotate(e.heading);
    roundRect(ctx, -r, -r * 0.8, r * 2, r * 1.6, 5);
  } else if (e.type === 'saboteur') {
    ctx.rotate(t * 3);
    ctx.moveTo(0, -r * 1.2);
    ctx.lineTo(r, 0);
    ctx.lineTo(0, r * 1.2);
    ctx.lineTo(-r, 0);
    ctx.closePath();
  } else {
    for (let i = 0; i < 12; i++) {
      const a = (Math.PI / 6) * i + t * 0.8;
      const rr = i % 2 ? r * 0.82 : r * 1.12;
      if (i === 0) ctx.moveTo(Math.cos(a) * rr, Math.sin(a) * rr);
      else ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
    }
    ctx.closePath();
  }
  ctx.fill();
  ctx.stroke();
  ctx.shadowBlur = 0;
  if (e.type === 'tank') {
    ctx.fillStyle = '#1f2937';
    ctx.fillRect(-r * 0.2, -r * 0.25, r * 1.3, r * 0.5);
  }
  ctx.restore();

  const frac = Math.max(0, e.health / e.max_health);
  const bw = Math.max(22, r * 2.2);
  ctx.fillStyle = 'rgba(0,0,0,0.7)';
  ctx.fillRect(x - bw / 2, y - r - 11, bw, 4);
  ctx.fillStyle = frac > 0.5 ? '#34d399' : frac > 0.25 ? '#fbbf24' : '#fb7185';
  ctx.fillRect(x - bw / 2, y - r - 11, bw * frac, 4);
  if (e.attacking) {
    ctx.fillStyle = '#fbbf24';
    ctx.font = '700 11px Inter';
    ctx.textAlign = 'center';
    ctx.fillText('⚒', x, y - r - 15);
  }
  if (e.type === 'boss') {
    ctx.font = '800 11px Orbitron';
    ctx.fillStyle = '#fecaca';
    ctx.textAlign = 'center';
    ctx.fillText('BOSS', x, y + r + 16);
  }
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}
