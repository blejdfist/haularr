import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api/client', () => ({ getAuthToken: () => 't', setAuthToken: vi.fn() }));

// Each fetch returns a stream the test pushes text into, or ends.
type Fake = { push: (s: string) => void; end: () => void; signal: AbortSignal; headers: any };
let calls: Fake[] = [];

function fakeFetch(_url: string, init: RequestInit) {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => (ctrl = c) });
  const enc = new TextEncoder();
  const fake: Fake = {
    push: (s) => ctrl.enqueue(enc.encode(s)),
    end: () => ctrl.close(),
    signal: init.signal!,
    headers: init.headers,
  };
  init.signal!.addEventListener('abort', () => ctrl.error(new Error('aborted')));
  calls.push(fake);
  return Promise.resolve(new Response(body, { status: 200 }));
}

const flush = () => vi.advanceTimersByTimeAsync(0);

describe('live', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    calls = [];
    vi.stubGlobal('fetch', vi.fn(fakeFetch));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('dispatches events, sends the token, and reopens after the stream drops', async () => {
    const { subscribe } = await import('../src/lib/live');
    const open = vi.fn();
    const job = vi.fn();
    const off = subscribe('/events/jobs', { open, job });
    await flush();
    expect(open).toHaveBeenCalledTimes(1);
    expect(calls[0].headers.Authorization).toBe('Bearer t');

    calls[0].push('event: job\ndata: {"id":"a"');
    calls[0].push('}\n\n: keepalive\n\n');
    await flush();
    expect(job).toHaveBeenCalledWith({ id: 'a' });

    calls[0].end(); // backend went away; a job is created meanwhile
    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toHaveLength(2);
    expect(open).toHaveBeenCalledTimes(2); // subscriber refetches state, picking up the new job
    off();
    expect(calls[1].signal.aborted).toBe(true);
  });

  it('shares one connection per path', async () => {
    const { subscribe } = await import('../src/lib/live');
    const offA = subscribe('/events/jobs', {});
    const offB = subscribe('/events/jobs', {});
    await flush();
    expect(calls).toHaveLength(1);
    offA();
    expect(calls[0].signal.aborted).toBe(false);
    offB();
    expect(calls[0].signal.aborted).toBe(true);
  });

  it('drops a stream that went silent and reconnects', async () => {
    const { subscribe } = await import('../src/lib/live');
    const off = subscribe('/events/jobs', {});
    await flush();
    await vi.advanceTimersByTimeAsync(41_000);
    expect(calls[0].signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toHaveLength(2);
    off();
  });
});
