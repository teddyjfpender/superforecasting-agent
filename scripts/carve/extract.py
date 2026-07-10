"""AST extractor for a moves-only carve.

Given a source file and a set of top-level function/class names, compute their
exact source ranges (decorator-aware, via ``end_lineno``) and:
  --list         print name -> (start,end) line ranges
  --emit-bodies  write the concatenated verbatim bodies (in file order) to stdout
  --strip OUT    write a copy of the file with those ranges removed to OUT

Verbatim: bytes are sliced from the original text, never reformatted (the Arc-D
"never regex, never reflow" rule). Registration blocks inside a function are NOT
top-level defs — replace those with the delegate call by hand.

Usage:
  python scripts/carve/extract.py FILE --emit-bodies fn1 fn2 ...
  python scripts/carve/extract.py FILE --strip NEWCORE fn1 fn2 ...
  python scripts/carve/extract.py FILE --list fn1 fn2 ...
"""
from __future__ import annotations

import ast
import sys


def ranges(path: str, names: set[str]) -> list[tuple[str, int, int]]:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in names:
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                found.append((node.name, start, node.end_lineno))
    return sorted(found, key=lambda t: t[1])


def main() -> None:
    path = sys.argv[1]
    mode = sys.argv[2]
    if mode == "--strip":
        out_path = sys.argv[3]
        names = set(sys.argv[4:])
    else:
        out_path = None
        names = set(sys.argv[3:])

    found = ranges(path, names)
    missing = names - {n for n, _, _ in found}
    if missing:
        print(f"ERROR: not found as top-level defs: {sorted(missing)}", file=sys.stderr)
        raise SystemExit(2)

    lines = open(path, encoding="utf-8").read().splitlines(keepends=True)

    if mode == "--list":
        for name, s, e in found:
            print(f"{name}\t{s}\t{e}\t({e - s + 1} lines)")
        return

    if mode == "--emit-bodies":
        chunks = []
        for name, s, e in found:
            chunks.append("".join(lines[s - 1:e]))
        sys.stdout.write("\n\n".join(chunks))
        return

    if mode == "--strip":
        remove = set()
        for _, s, e in found:
            # also swallow up to 2 blank separator lines AFTER the block
            end = e
            while end < len(lines) and lines[end].strip() == "":
                end += 1
                if end - e >= 2:
                    break
            for i in range(s - 1, end):
                remove.add(i)
        kept = [ln for i, ln in enumerate(lines) if i not in remove]
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
        print(f"stripped {len(remove)} lines -> {out_path}")
        return

    print(f"unknown mode {mode}", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
