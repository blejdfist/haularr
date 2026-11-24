// Live change streams (SSE under /api/v1/events/...). Streams carry changes only; current state
// comes from the regular endpoints. Subscribers refetch state in `open`, which runs on every
// (re)connect, so whatever changed while disconnected is picked up.
//
// Uses fetch rather than EventSource so the auth token goes in a header (not the URL, where it
// would land in access logs), and so reconnects are under our control.

import { goto } from '$app/navigation';
import { getAuthToken, setAuthToken } from '$lib/api/client';

export type JobEvent = {
  id: string;
  status: string;
  stage: string;
  error_code: string | null;
  download_bytes_done: number;
  download_bytes_total: number;
  stage_progress: { bytes_done?: number; bytes_total?: number } | null;
  progress: number | null;
};

type Handlers = { open?: () => void } & Record<string, ((data: any) => void) | undefined>;

// Servers send a keepalive at least every 15s; silence beyond this means a dead connection
// (e.g. a proxy that kept our side open after the backend died).
const STALE_MS = 40_000;

type Conn = { subs: Set<Handlers>; stop: () => void };
const conns = new Map<string, Conn>();

function start(path: string, conn: Conn) {
  let ctrl: AbortController;
  let stopped = false;
  let delay = 1000;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const alive = () => {
    clearTimeout(watchdog);
    watchdog = setTimeout(() => ctrl.abort(), STALE_MS);
  };

  async function run() {
    ctrl = new AbortController();
    alive();
    try {
      const token = getAuthToken();
      const res = await fetch(`/api/v1${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: ctrl.signal,
      });
      if (res.status === 401) {
        setAuthToken(null);
        goto('/login/');
        return;
      }
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      delay = 1000;
      for (const h of conn.subs) h.open?.();

      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        alive();
        buf += value;
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, i);
          buf = buf.slice(i + 2);
          let kind = 'message';
          let data = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) kind = line.slice(6).trim();
            else if (line.startsWith('data:')) data += line.slice(5).trim();
          }
          if (!data) continue; // keepalive comment
          let parsed: unknown;
          try {
            parsed = JSON.parse(data);
          } catch {
            continue;
          }
          for (const h of conn.subs) h[kind]?.(parsed);
        }
      }
    } catch {
      /* network error, abort or bad status: retry below */
    }
    clearTimeout(watchdog);
    if (stopped) return;
    retry = setTimeout(run, delay);
    delay = Math.min(delay * 2, 10_000);
  }

  conn.stop = () => {
    stopped = true;
    clearTimeout(retry);
    clearTimeout(watchdog);
    ctrl?.abort();
  };
  run();
}

/**
 * Subscribe to a stream such as `/events/jobs`. Each handler key is an event name; `open` runs
 * on every (re)connect. Subscribers to the same path share one connection. Returns unsubscribe.
 */
export function subscribe(path: string, handlers: Handlers): () => void {
  let conn = conns.get(path);
  if (!conn) {
    conn = { subs: new Set(), stop: () => {} };
    conns.set(path, conn);
    start(path, conn);
  }
  conn.subs.add(handlers);
  const c = conn;
  return () => {
    c.subs.delete(handlers);
    if (c.subs.size) return;
    c.stop();
    conns.delete(path);
  };
}

/** Run `fn` now, or once more after the current run if called while one is in flight. */
export function coalesce(fn: () => Promise<unknown>): () => void {
  let running = false;
  let again = false;
  return async () => {
    if (running) {
      again = true;
      return;
    }
    running = true;
    try {
      do {
        again = false;
        await fn();
      } while (again);
    } finally {
      running = false;
    }
  };
}
