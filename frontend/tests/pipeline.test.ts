import { describe, it, expect } from 'vitest';
import { jobSteps, PHASES } from '../src/lib/pipeline';

const states = (s: ReturnType<typeof jobSteps>) => s.map((x) => x.state);

describe('jobSteps', () => {
  it('has seven phases in order', () => {
    expect(PHASES.map((p) => p.label)).toEqual(['Download', 'Library', 'Transfer', 'Verify', 'Unpack', 'Import', 'Finish']);
  });
  it('running mid-pipeline', () => {
    expect(states(jobSteps({ status: 'running', stage: 'extract' })))
      .toEqual(['done', 'done', 'done', 'done', 'active', 'pending', 'pending']);
  });
  it('queued at the library check is active', () => {
    expect(jobSteps({ status: 'queued', stage: 'check_library' })[1].state).toBe('active');
  });
  it('downloading on the seedbox is active with progress', () => {
    expect(jobSteps({ status: 'waiting_source', stage: 'source_download' }, 40)[0]).toMatchObject({ state: 'active', progress: 40 });
  });
  it('waiting for the library', () => {
    expect(jobSteps({ status: 'waiting_library', stage: 'check_library' })[1]).toMatchObject({ state: 'waiting', reason: 'Not in library yet' });
  });
  it('waiting for approval', () => {
    expect(jobSteps({ status: 'waiting_approval', stage: 'check_library' })[1]).toMatchObject({ state: 'waiting', reason: 'Waiting for you to start it' });
  });
  it('waiting for fetch config', () => {
    const s = jobSteps({ status: 'waiting_transfer', stage: 'transfer', error_code: 'no_transfer_config' });
    expect(s[2]).toMatchObject({ state: 'waiting', reason: 'No fetch config on this source' });
  });
  it('failed uses error_detail as reason', () => {
    const s = jobSteps({ status: 'failed', stage: 'import', error_detail: 'no artist' });
    expect(states(s)).toEqual(['done', 'done', 'done', 'done', 'done', 'failed', 'pending']);
    expect(s[5].reason).toBe('no artist');
  });
  it('cancelled', () => {
    expect(jobSteps({ status: 'cancelled', stage: 'verify' })[3]).toMatchObject({ state: 'failed', reason: 'Cancelled' });
  });
  it('paused', () => {
    expect(jobSteps({ status: 'paused', stage: 'verify' })[3]).toMatchObject({ state: 'waiting', reason: 'Paused' });
  });
  it('completed is all done', () => {
    expect(states(jobSteps({ status: 'completed', stage: 'cleanup' }))).toEqual(Array(7).fill('done'));
  });
  it('progress only on active step', () => {
    expect(jobSteps({ status: 'running', stage: 'transfer' }, 40)[2].progress).toBe(40);
    expect(jobSteps({ status: 'waiting_transfer', stage: 'transfer' }, 40)[2].progress).toBeUndefined();
  });
  it('metered stages start at 0 before any progress arrives', () => {
    expect(jobSteps({ status: 'queued', stage: 'transfer' })[2].progress).toBe(0);
    expect(jobSteps({ status: 'running', stage: 'move' })[4].progress).toBeUndefined();
    expect(jobSteps({ status: 'running', stage: 'verify' })[3].progress).toBeUndefined();
  });
  it('extract progress shows on the unpack phase', () => {
    expect(jobSteps({ status: 'running', stage: 'extract' }, 30)[4].progress).toBe(30);
  });
  it('unknown stage falls back to first phase', () => {
    expect(jobSteps({ status: 'running', stage: 'bogus' })[0].state).toBe('active');
  });
});

import { currentRuns, trackRate, type RateSample } from '../src/lib/pipeline';

describe('currentRuns', () => {
  const run = (stage: string, started_at: string, status: string, attempt = 1) => ({ stage, started_at, status, attempt });
  it('restart hides the previous pass, even with higher attempt numbers', () => {
    const m = currentRuns([
      run('transfer', '2026-01-01T00:00:00', 'running', 3), // stale, old pass
      run('move', '2026-01-01T00:01:00', 'failed', 2),
      run('cleanup', '2026-01-01T00:02:00', 'succeeded'),
      run('check_library', '2026-01-02T00:00:00', 'succeeded'), // restart
      run('transfer', '2026-01-02T00:00:01', 'succeeded'),
      run('move', '2026-01-02T00:00:02', 'succeeded'),
      run('import', '2026-01-02T00:00:03', 'running'),
    ]);
    expect(m.get('transfer')?.status).toBe('succeeded');
    expect(m.get('move')?.status).toBe('succeeded');
    expect(m.get('import')?.status).toBe('running');
    expect(m.has('cleanup')).toBe(false);
  });

  it('runs with the same start time keep pipeline order', () => {
    const t = '2026-01-01T00:00:00';
    const runs = currentRuns([
      { stage: 'transfer', started_at: t, status: 'running' },
      { stage: 'check_library', started_at: t, status: 'succeeded' },
    ]);
    expect(runs.get('transfer')?.status).toBe('running');
  });
});

describe('trackRate', () => {
  function feed(points: [number, number][]) {
    let s: RateSample[] = [];
    let rate: number | undefined;
    for (const [got, t] of points) ({ samples: s, rate } = trackRate(s, got, t));
    return rate;
  }
  it('ignores idle time before the first bytes move', () => {
    // Drawer opens at t=0, nothing moves for 12s, then 10 MB/s.
    expect(feed([[0, 0], [0, 3000], [0, 6000], [0, 9000], [0, 12000], [30e6, 15000], [60e6, 18000]])).toBeCloseTo(10e6);
  });
  it('measures over the recent window only', () => {
    // 1 MB/s for a minute, then 10 MB/s.
    const pts: [number, number][] = [];
    for (let t = 0; t <= 60000; t += 3000) pts.push([t * 1000, t]);
    for (let t = 63000, got = 60e6 + 30e6; t <= 90000; t += 3000, got += 30e6) pts.push([got, t]);
    expect(feed(pts)).toBeCloseTo(10e6, -5);
  });
  it('starts over when the counter goes backwards', () => {
    expect(feed([[50e6, 0], [80e6, 3000], [0, 6000]])).toBeUndefined();
  });
});
