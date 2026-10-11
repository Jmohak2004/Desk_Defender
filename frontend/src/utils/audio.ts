// Tiny WebAudio synth - no audio assets needed. Sounds are rate-limited per type.
import { useGameStore } from '../store/gameStore';

let ctx: AudioContext | null = null;
const lastPlayed: Record<string, number> = {};

function audio(): AudioContext | null {
  const { sound } = useGameStore.getState().prefs;
  if (!sound) return null;
  if (!ctx) {
    try {
      ctx = new AudioContext();
    } catch {
      return null;
    }
  }
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

function tone(freq: number, dur: number, type: OscillatorType, gain: number, slideTo?: number, delay = 0) {
  const a = audio();
  if (!a) return;
  const vol = useGameStore.getState().prefs.volume;
  const t = a.currentTime + delay;
  const o = a.createOscillator();
  const g = a.createGain();
  o.type = type;
  o.frequency.setValueAtTime(freq, t);
  if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
  g.gain.setValueAtTime(gain * vol, t);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(a.destination);
  o.start(t);
  o.stop(t + dur + 0.02);
}

function noise(dur: number, gain: number) {
  const a = audio();
  if (!a) return;
  const vol = useGameStore.getState().prefs.volume;
  const buf = a.createBuffer(1, Math.floor(a.sampleRate * dur), a.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
  const src = a.createBufferSource();
  const g = a.createGain();
  const f = a.createBiquadFilter();
  f.type = 'lowpass';
  f.frequency.value = 900;
  src.buffer = buf;
  g.gain.value = gain * vol;
  src.connect(f).connect(g).connect(a.destination);
  src.start();
}

export type Sfx = 'shoot' | 'kill' | 'boss_kill' | 'base_hit' | 'wave' | 'destroyed' | 'strike' | 'emp' | 'repair' | 'click' | 'victory' | 'defeat' | 'sabotage' | 'place';

export function play(sfx: Sfx) {
  const now = performance.now();
  const minGap = sfx === 'shoot' ? 70 : sfx === 'kill' ? 40 : 120;
  if (now - (lastPlayed[sfx] ?? 0) < minGap) return;
  lastPlayed[sfx] = now;
  switch (sfx) {
    case 'shoot': tone(880, 0.06, 'square', 0.03, 520); break;
    case 'kill': tone(420, 0.12, 'triangle', 0.08, 160); noise(0.08, 0.05); break;
    case 'boss_kill': tone(220, 0.6, 'sawtooth', 0.12, 40); noise(0.5, 0.15); break;
    case 'base_hit': tone(120, 0.35, 'sawtooth', 0.15, 50); noise(0.25, 0.12); break;
    case 'wave': tone(523, 0.12, 'triangle', 0.1); tone(784, 0.18, 'triangle', 0.1, undefined, 0.12); break;
    case 'destroyed': noise(0.4, 0.15); tone(160, 0.3, 'square', 0.06, 60); break;
    case 'strike': tone(1200, 0.1, 'sine', 0.08, 300); noise(0.45, 0.2); break;
    case 'emp': tone(200, 0.5, 'sine', 0.12, 1600); break;
    case 'repair': tone(660, 0.1, 'sine', 0.08); tone(990, 0.15, 'sine', 0.08, undefined, 0.1); break;
    case 'click': tone(1400, 0.03, 'square', 0.03); break;
    case 'sabotage': tone(300, 0.25, 'sawtooth', 0.06, 900); break;
    case 'place': tone(600, 0.08, 'triangle', 0.06, 900); break;
    case 'victory': [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.25, 'triangle', 0.1, undefined, i * 0.14)); break;
    case 'defeat': [392, 330, 262, 196].forEach((f, i) => tone(f, 0.3, 'sawtooth', 0.07, undefined, i * 0.18)); break;
  }
}
