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
  it('unknown stage falls back to first phase', () => {
    expect(jobSteps({ status: 'running', stage: 'bogus' })[0].state).toBe('active');
  });
});
