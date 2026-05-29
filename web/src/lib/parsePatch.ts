export interface PatchFile {
  path: string;
  added: number;
  removed: number;
  hunkLines: string[];
}

export function parsePatch(patch: string): PatchFile[] {
  if (!patch.trim()) return [];
  const lines = patch.split("\n");
  const files: PatchFile[] = [];
  let current: PatchFile | null = null;
  let inHunk = false;
  for (const ln of lines) {
    if (ln.startsWith("diff --git ")) {
      const m = /diff --git a\/(.+) b\/(.+)/.exec(ln);
      if (current) files.push(current);
      current = { path: m?.[2] ?? m?.[1] ?? "?", added: 0, removed: 0, hunkLines: [] };
      inHunk = false;
      continue;
    }
    if (!current) continue;
    if (ln.startsWith("@@")) { inHunk = true; current.hunkLines.push(ln); continue; }
    if (!inHunk) continue;
    current.hunkLines.push(ln);
    if (ln.startsWith("+") && !ln.startsWith("+++")) current.added += 1;
    else if (ln.startsWith("-") && !ln.startsWith("---")) current.removed += 1;
  }
  if (current) files.push(current);
  return files;
}
