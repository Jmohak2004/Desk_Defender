import { useCallback, useEffect, useState } from 'react';
import { api } from '../utils/api';
import { useGameStore } from '../store/gameStore';
import type { CameraDevice, CameraStatus } from '../types/game';

/** Camera discovery + connection via REST; live status comes from the WebSocket vision channel. */
export function useCameraState() {
  const [devices, setDevices] = useState<CameraDevice[]>([]);
  const [status, setStatus] = useState<CameraStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const liveCamera = useGameStore((s) => s.vision?.camera ?? null);

  const refresh = useCallback(async () => {
    try {
      const [list, st] = await Promise.all([
        api<CameraDevice[]>('/api/cameras'),
        api<CameraStatus>('/api/camera/status'),
      ]);
      setDevices(list);
      setStatus(st);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const connect = useCallback(
    async (cameraId: number | string, width?: number, height?: number) => {
      setBusy(true);
      setError(null);
      try {
        const st = await api<CameraStatus>('/api/camera/connect', { body: { camera_id: cameraId, width, height } });
        setStatus(st);
        return true;
      } catch (e) {
        setError((e as Error).message);
        await refresh();
        return false;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  const disconnect = useCallback(async () => {
    setBusy(true);
    try {
      setStatus(await api<CameraStatus>('/api/camera/disconnect', { method: 'POST' }));
    } finally {
      setBusy(false);
    }
  }, []);

  const merged: CameraStatus | null = liveCamera ? { ...status, ...liveCamera } as CameraStatus : status;
  return { devices, status: merged, troubleshooting: status?.troubleshooting ?? [], busy, error, refresh, connect, disconnect };
}
