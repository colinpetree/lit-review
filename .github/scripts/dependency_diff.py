"""Lists which Python and npm packages changed since the previous release, as
Markdown for the release notes and the workflow's job summary.

Why: backend/requirements.txt pins only the packages it lists. The packages
those pull in (httpx2, pydantic, google-auth, ...) are not pinned, and every
build installs fresh, so a release can pick up a new version of one with
nobody noticing. Showing exactly what moved is the next best thing to a lock.
Copied from personal-website's .github/scripts/dependency-diff.py, with one
Python section per platform (each build leg freezes its own environment).

Usage:
  python dependency_diff.py --pip Windows OLD_FREEZE NEW_FREEZE \
                            --pip macOS-Intel OLD_FREEZE NEW_FREEZE \
                            --npm-old OLD_LOCK --npm-new NEW_LOCK

An OLD_* path may point to a missing file (first release); that section then
says "No previous release to compare with".
"""
import argparse
import json
import os
import re


def read_freeze(path):
    if not path or not os.path.exists(path):
        return None
    pkgs = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^([A-Za-z0-9_.\-]+)==([^\s;]+)', line.strip())
            if m:
                pkgs[m.group(1).lower().replace('_', '-')] = m.group(2)
    return pkgs


def read_lock(path):
    """Top-level installed packages from an npm v2/v3 lockfile."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        lock = json.load(f)
    pkgs = {}
    for key, info in (lock.get('packages') or {}).items():
        # "node_modules/react" but not nested "node_modules/a/node_modules/b"
        if key.startswith('node_modules/') and key.count('node_modules/') == 1:
            pkgs[key[len('node_modules/'):]] = info.get('version', '?')
    return pkgs


def diff(old, new):
    rows = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        if a is None:
            rows.append(f'| {name} | (new) | {b} |')
        elif b is None:
            rows.append(f'| {name} | {a} | (removed) |')
        else:
            major = a.split('.')[0] != b.split('.')[0]
            rows.append(f'| {name}{" **(major)**" if major else ""} | {a} | {b} |')
    return rows


def section(title, old, new):
    out = [f'### {title}', '']
    if old is None:
        out += ['No previous release to compare with.', '']
        return out
    rows = diff(old, new or {})
    if not rows:
        out += ['No changes.', '']
        return out
    out += ['| Package | Before | Now |', '|---|---|---|', *rows, '']
    return out


def report(pip_pairs, npm_old, npm_new):
    lines = ['## Dependency changes since the previous release', '']
    for label, old, new in pip_pairs:
        lines += section(f'Python, {label} (exact versions frozen into the app)', read_freeze(old), read_freeze(new))
    lines += section('npm (frontend/package-lock.json, top-level installs)', read_lock(npm_old), read_lock(npm_new))
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--pip', nargs=3, action='append', default=[], metavar=('LABEL', 'OLD', 'NEW'))
    p.add_argument('--npm-old')
    p.add_argument('--npm-new', required=True)
    a = p.parse_args(argv)
    print(report(a.pip, a.npm_old, a.npm_new))


if __name__ == '__main__':
    main()
