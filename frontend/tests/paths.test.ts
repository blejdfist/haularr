import { describe, expect, it } from 'vitest';
import { crumbs } from '../src/lib/paths';

const paths = (p: string) => crumbs(p).map((c) => c.path);

describe('crumbs', () => {
  it('is empty for the roots view', () => expect(crumbs('')).toEqual([]));
  it('walks a POSIX path', () => {
    expect(paths('/')).toEqual(['/']);
    expect(paths('/data/incoming')).toEqual(['/', '/data', '/data/incoming']);
    expect(paths('/a\\b')).toEqual(['/', '/a\\b']);
  });
  it('walks a Windows drive path', () => {
    expect(paths('D:\\')).toEqual(['D:\\']);
    expect(paths('D:\\media\\tv')).toEqual(['D:\\', 'D:\\media', 'D:\\media\\tv']);
  });
  it('keeps a UNC share as one root', () => {
    expect(paths('\\\\nas\\share\\tv')).toEqual(['\\\\nas\\share\\', '\\\\nas\\share\\tv']);
  });
});
