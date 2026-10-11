// Small fetch wrapper that turns FastAPI error payloads into readable messages.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailToText(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: string }).msg) : String(d)))
      .join('; ');
  }
  return 'Request failed';
}

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: options.method ?? (options.body !== undefined ? 'POST' : 'GET'),
      headers: options.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the backend on port 8000. Is it running? (./start.sh)');
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detailToText(detail) || `HTTP ${res.status}`);
  }
  return data as T;
}
