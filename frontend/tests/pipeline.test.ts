import { describe, it, expect } from 'vitest';
import { jobSteps, PHASES } from '../src/lib/pipeline';

const states = (s: ReturnType<typeof jobSteps>) => s.map((x) => x.state);

describe('jobSteps', () => {
  it('has five phases in order', () => {
    expect(PHASES.map((p) => p.label)).toEqual(['Fetch', 'Check', 'Unpack', 'Import', 'Finish']);
  });
  it('running mid-pipeline', () => {
    expect(states(jobSteps({ status: 'running', stage: 'extract' })))
      .toEqual(['done', 'done', 'active', 'pending', 'pending']);
  });
  it('queued at first stage is active', () => {
    expect(jobSteps({ status: 'queued', stage: 'resolve_source' })[0].state).toBe('active');
  });
  it('waiting for fetch config', () => {
    const s = jobSteps({ status: 'waiting_source', stage: 'download', error_code: 'no_transfer_config' });
    expect(s[0]).toMatchObject({ state: 'waiting', reason: 'No fetch config on this source' });
  });
  it('failed uses error_detail as reason', () => {
    const s = jobSteps({ status: 'failed', stage: 'import', error_detail: 'no artist' });
    expect(states(s)).toEqual(['done', 'done', 'done', 'failed', 'pending']);
    expect(s[3].reason).toBe('no artist');
  });
  it('cancelled', () => {
    expect(jobSteps({ status: 'cancelled', stage: 'verify' })[1]).toMatchObject({ state: 'failed', reason: 'Cancelled' });
  });
  it('paused', () => {
    expect(jobSteps({ status: 'paused', stage: 'verify' })[1]).toMatchObject({ state: 'waiting', reason: 'Paused' });
  });
  it('completed is all done', () => {
    expect(states(jobSteps({ status: 'completed', stage: 'cleanup' }))).toEqual(Array(5).fill('done'));
  });
  it('progress only on active step', () => {
    expect(jobSteps({ status: 'running', stage: 'download' }, 40)[0].progress).toBe(40);
    expect(jobSteps({ status: 'waiting_source', stage: 'download' }, 40)[0].progress).toBeUndefined();
  });
  it('extract progress shows on the unpack phase', () => {
    expect(jobSteps({ status: 'running', stage: 'extract' }, 30)[2].progress).toBe(30);
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
      run('download', '2026-01-01T00:00:00', 'running', 3), // stale, old pass
      run('publish', '2026-01-01T00:01:00', 'failed', 2),
      run('confirm_import', '2026-01-01T00:02:00', 'succeeded'),
      run('resolve_source', '2026-01-02T00:00:00', 'succeeded'), // restart
      run('download', '2026-01-02T00:00:01', 'succeeded'),
      run('publish', '2026-01-02T00:00:02', 'succeeded'),
      run('import', '2026-01-02T00:00:03', 'running'),
    ]);
    expect(m.get('download')?.status).toBe('succeeded');
    expect(m.get('publish')?.status).toBe('succeeded');
    expect(m.get('import')?.status).toBe('running');
    expect(m.has('confirm_import')).toBe(false);
  });

  it('runs with the same start time keep pipeline order', () => {
    const t = '2026-01-01T00:00:00';
    const runs = currentRuns([
      { stage: 'download', started_at: t, status: 'running' },
      { stage: 'resolve_source', started_at: t, status: 'succeeded' },
    ]);
    expect(runs.get('download')?.status).toBe('running');
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
