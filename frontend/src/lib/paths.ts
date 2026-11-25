export interface Crumb {
  name: string;
  path: string;
}

/** Ancestors of an absolute server path, root first, ending at the path itself. '' gives []. */
export function crumbs(path: string): Crumb[] {
  if (!path) return [];
  // A leading slash means POSIX, where a backslash is an ordinary filename character.
  const sep = path.startsWith('/') ? '/' : '\\';
  const root = sep === '/' ? '/' : (path.match(/^(\\\\[^\\]+\\[^\\]+|[A-Za-z]:)\\?/)?.[0] ?? '');
  const base = root && !root.endsWith(sep) ? root + sep : root;
  const out: Crumb[] = base ? [{ name: base, path: base }] : [];
  let at = base;
  for (const name of path.slice(root.length).split(sep).filter(Boolean)) {
    at += at && !at.endsWith(sep) ? sep + name : name;
    out.push({ name, path: at });
  }
  return out;
}
