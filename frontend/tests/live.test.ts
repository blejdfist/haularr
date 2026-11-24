import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

class FakeES {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static all: FakeES[] = [];
  readyState = FakeES.OPEN;
  onerror: (() => void) | null = null;
  private handlers: ((ev: { data: string }) => void)[] = [];
  constructor(public url: string) {
    FakeES.all.push(this);
  }
  addEventListener(_type: string, fn: (ev: { data: string }) => void) {
    this.handlers.push(fn);
  }
  close() {
    this.readyState = FakeES.CLOSED;
  }
  send(version: string) {
    for (const h of this.handlers) h({ data: JSON.stringify({ version, logs: 0, jobs: [] }) });
  }
  fail() {
    this.readyState = FakeES.CLOSED; // reconnect refused: the browser gives up
    this.onerror?.();
  }
}

describe('live', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    FakeES.all = [];
    vi.stubGlobal('EventSource', FakeES);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('reloads after a reconnect when jobs changed while disconnected', async () => {
    const { onChange } = await import('../src/lib/live');
    const fn = vi.fn();
    const off = onChange((s) => s.version, fn);

    FakeES.all[0].send('3:a');
    expect(fn).toHaveBeenCalledTimes(1); // first snapshot
    FakeES.all[0].send('3:a');
    expect(fn).toHaveBeenCalledTimes(1); // unchanged: no reload

    FakeES.all[0].fail(); // connection lost; a job is created meanwhile
    vi.advanceTimersByTime(1000);
    expect(FakeES.all).toHaveLength(2); // reconnected

    FakeES.all[1].send('4:b');
    expect(fn).toHaveBeenCalledTimes(2);
    off();
    expect(FakeES.all[1].readyState).toBe(FakeES.CLOSED);
  });

  it('shares one connection and backs off between failed reconnects', async () => {
    const { onSnapshot } = await import('../src/lib/live');
    const offA = onSnapshot(() => {});
    const offB = onSnapshot(() => {});
    expect(FakeES.all).toHaveLength(1);

    FakeES.all[0].fail();
    vi.advanceTimersByTime(1000);
    FakeES.all[1].fail();
    vi.advanceTimersByTime(1000);
    expect(FakeES.all).toHaveLength(2); // second retry waits 2s
    vi.advanceTimersByTime(1000);
    expect(FakeES.all).toHaveLength(3);
    offA();
    offB();
  });

  it('reconnects a stream that went silent without an error', async () => {
    const { onChange } = await import('../src/lib/live');
    const fn = vi.fn();
    const off = onChange((s) => s.version, fn);
    FakeES.all[0].send('1:a');
    vi.advanceTimersByTime(12_000); // no snapshots, no error: half-open
    expect(FakeES.all[0].readyState).toBe(FakeES.CLOSED);
    vi.advanceTimersByTime(1000);
    expect(FakeES.all).toHaveLength(2);
    FakeES.all[1].send('2:b');
    expect(fn).toHaveBeenCalledTimes(2);
    off();
  });
});
