import { useEffect } from 'react';
import { useGameStore } from '../store/gameStore';
import type { GameEvent, GameSnapshot, VisionSnapshot } from '../types/game';

// One WebSocket for the whole app (module singleton), with auto-reconnect,
// sequence tracking and promise-based acks for client actions.

type EventListener = (events: GameEvent[]) => void;
type Ack = { ok: boolean; message: string };

const listeners = new Set<EventListener>();
const pending = new Map<string, { resolve: (a: Ack) => void; timer: number }>();
let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
let retries = 0;
let requestCounter = 0;
let users = 0;

export function onGameEvents(fn: EventListener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function handleMessage(raw: string) {
  let msg: { type: string; seq: number; ts: number; [k: string]: unknown };
  try {
    msg = JSON.parse(raw);
  } catch {
    return;
  }
  const store = useGameStore.getState();
  if (typeof msg.seq === 'number' && msg.seq <= store.lastSeq && msg.type !== 'hello') return; // stale / duplicate
  const now = Date.now();
  useGameStore.setState({ lastSeq: msg.seq, lastMessageAt: now, latencyMs: Math.max(0, now - msg.ts * 1000) });

  switch (msg.type) {
    case 'state': {
      useGameStore.setState({ game: msg.game as GameSnapshot });
      const events = (msg.events as GameEvent[]) ?? [];
      if (events.length) listeners.forEach((l) => l(events));
      break;
    }
    case 'vision':
      useGameStore.setState({ vision: msg as unknown as VisionSnapshot });
      break;
    case 'ack': {
      const id = msg.request_id as string | undefined;
      const entry = id ? pending.get(id) : undefined;
      if (entry) {
        clearTimeout(entry.timer);
        pending.delete(id!);
        entry.resolve({ ok: Boolean(msg.ok), message: String(msg.message ?? '') });
      }
      break;
    }
    case 'error':
      store.toast('error', `Server rejected message: ${String(msg.message)}`);
      break;
  }
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${window.location.host}/ws/game`);
  socket = ws;
  useGameStore.setState({ socket: 'connecting' });
  ws.onopen = () => {
    retries = 0;
    useGameStore.setState({ socket: 'open', lastSeq: 0 });
  };
  ws.onmessage = (e) => handleMessage(e.data);
  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    useGameStore.setState({ socket: 'closed' });
    pending.forEach((p) => p.resolve({ ok: false, message: 'Connection lost' }));
    pending.clear();
    if (users > 0) {
      const delay = Math.min(5000, 500 * 2 ** retries++);
      reconnectTimer = window.setTimeout(connect, delay);
    }
  };
}

/** Sends an action over the socket; resolves with the server ack. */
export function sendAction(action: string, payload: Record<string, unknown> = {}): Promise<Ack> {
  return new Promise((resolve) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      resolve({ ok: false, message: 'Not connected to the game server' });
      return;
    }
    const request_id = `r${++requestCounter}`;
    const timer = window.setTimeout(() => {
      pending.delete(request_id);
      resolve({ ok: false, message: 'Server did not answer in time' });
    }, 4000);
    pending.set(request_id, { resolve, timer });
    socket.send(JSON.stringify({ action, request_id, ...payload }));
  });
}

/** Fire-and-forget (used for high-rate messages such as simulated-object drags). */
export function sendRaw(action: string, payload: Record<string, unknown>) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ action, ...payload }));
}

/** Keeps the socket open while at least one component uses it. */
export function useGameSocket() {
  useEffect(() => {
    users++;
    connect();
    return () => {
      users--;
      if (users === 0) {
        if (reconnectTimer) clearTimeout(reconnectTimer);
        socket?.close();
        socket = null;
      }
    };
  }, []);
}

/** Sends an action and reports failures as a toast. */
export async function act(action: string, payload: Record<string, unknown> = {}, successText?: string) {
  const ack = await sendAction(action, payload);
  const { toast } = useGameStore.getState();
  if (!ack.ok) toast('warning', ack.message || `${action} failed`);
  else if (successText) toast('success', successText);
  return ack;
}
