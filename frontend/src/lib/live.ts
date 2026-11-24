// One shared SSE connection to /api/v1/events; pages subscribe instead of polling.
//
// Snapshots carry state markers (a jobs version, a log counter), not one-off events, so
// nothing is lost while disconnected: the first snapshot after a reconnect differs from the
// last one seen, and subscribers reload.

export type LiveJob = { id: string; status: string; stage: string; progress: number | null };
export type Snapshot = { version: string; logs: number; jobs: LiveJob[] };
type Listener = (s: Snapshot) => void;

const listeners = new Set<Listener>();
let es: EventSource | null = null;
let retry: ReturnType<typeof setTimeout> | undefined;
let watchdog: ReturnType<typeof setInterval> | undefined;
let delay = 1000;
let lastMessage = 0;

// The server sends a snapshot every 2s. Silence for this long means a half-open stream
// (e.g. a proxy that never closed our side when the backend died): drop it and reconnect.
const STALE_MS = 10_000;

function disconnect() {
  es?.close();
  es = null;
  clearInterval(watchdog);
  watchdog = undefined;
  clearTimeout(retry);
  retry = undefined;
}

function reconnectLater() {
  disconnect();
  retry = setTimeout(connect, delay);
  delay = Math.min(delay * 2, 30_000);
}

function connect() {
  retry = undefined;
  lastMessage = Date.now();
  es = new EventSource('/api/v1/events');
  es.addEventListener('snapshot', (ev) => {
    lastMessage = Date.now();
    delay = 1000;
    let s: Snapshot;
    try {
      s = JSON.parse((ev as MessageEvent).data);
    } catch {
      return; // malformed snapshot
    }
    for (const fn of listeners) fn(s);
  });
  es.onerror = () => {
    // While readyState is CONNECTING the browser retries by itself. A failed reconnect
    // (backend down, proxy error) closes the stream for good, so retry with backoff here.
    if (es?.readyState === EventSource.CLOSED) reconnectLater();
  };
  watchdog = setInterval(() => {
    if (Date.now() - lastMessage > STALE_MS) reconnectLater();
  }, 2000);
}

/** Call `fn` with every snapshot. Returns an unsubscribe function. */
export function onSnapshot(fn: Listener): () => void {
  listeners.add(fn);
  if (!es && !retry) connect();
  return () => {
    listeners.delete(fn);
    if (!listeners.size) disconnect();
  };
}

/**
 * Call `fn` whenever `pick(snapshot)` differs from the last value seen, including the first
 * snapshot (covers changes between a page's initial load and the stream opening).
 */
export function onChange<T>(pick: (s: Snapshot) => T, fn: (s: Snapshot) => void): () => void {
  let seen = false;
  let last: T;
  return onSnapshot((s) => {
    const v = pick(s);
    if (!seen || v !== last) fn(s);
    seen = true;
    last = v;
  });
}
