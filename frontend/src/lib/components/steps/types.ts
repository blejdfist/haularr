export type StepState = 'done' | 'skipped' | 'active' | 'waiting' | 'failed' | 'pending';

export interface Step {
  key: string;
  label: string;
  state: StepState;
  /** 0-100, shown on the current step while active. */
  progress?: number;
  /** Why the step is waiting/failed; shown behind a warning icon. */
  reason?: string;
}

/** Current step: first not done/skipped, else the last one. */
export function currentIndex(steps: Step[]): number {
  const i = steps.findIndex((s) => s.state !== 'done' && s.state !== 'skipped');
  return i === -1 ? steps.length - 1 : i;
}
