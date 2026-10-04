"""Write THIRD_PARTY_NOTICES.txt: the licenses of everything the packaged app carries.

The app bundles other people's code (the Python packages in backend/requirements.txt
and what they need, and the npm packages built into the page, including the fonts
and the Lucide icon used as the logo). Most licenses ask for their notice to travel
with copies, so the release zips include this file next to the app's own LICENSE.

    python packaging/make_notices.py [--out PATH]

Run it where the app's requirements are installed (CI does, after `pip install`
and `npm ci`). It reads package metadata and license files; nothing is downloaded.
"""

import argparse
import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE)[^/]*$", re.I)


def _name(requirement):
    """The package name in a requirement line such as "httpx>=0.2 ; extra == 'x'"."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


def _requirements(path):
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.append(_name(line))
    return names


def _applies_here(marker):
    """Does a requirement's environment marker (sys_platform == "darwin"...) hold on
    this machine? Unreadable markers count as yes: listing too much is harmless."""
    try:
        from packaging.markers import Marker

        return Marker(marker).evaluate({"extra": ""})
    except Exception:  # noqa: BLE001
        return True


def python_packages():
    """name -> distribution, for the requirements and everything they need at run time."""
    wanted = _requirements(ROOT / "backend" / "requirements.txt")
    found = {}
    while wanted:
        name = wanted.pop()
        if name in found:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # a platform-specific package that is not installed here
        found[name] = dist
        for requirement in dist.requires or []:
            # Skip extras and other platforms' packages: they are not in this build.
            if "extra ==" in requirement:
                continue
            marker = requirement.partition(";")[2].strip()
            if marker and not _applies_here(marker):
                continue
            dependency = _name(requirement)
            if dependency:
                wanted.append(dependency)
    return found


def python_entries():
    entries = []
    for name, dist in sorted(python_packages().items()):
        meta = dist.metadata
        license_name = (meta.get("License-Expression") or meta.get("License") or "").strip()
        if not license_name or len(license_name) > 100 or "\n" in license_name:
            classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
            license_name = ", ".join(classifiers) or "see the license text"
        texts = []
        for file in dist.files or []:
            if LICENSE_FILE.search(str(file).replace("\\", "/")):
                try:
                    texts.append(file.locate().read_bytes().decode("utf-8", errors="replace").strip())
                except OSError:
                    pass
        entries.append((f"{meta['Name']} {meta['Version']}", license_name, texts))
    return entries


def npm_entries():
    """The frontend's production dependencies (what `vite build` puts in the page)."""
    frontend = ROOT / "frontend"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        listing = subprocess.run(
            [npm, "ls", "--omit=dev", "--all", "--json"], cwd=frontend, capture_output=True, text=True, check=False
        ).stdout
        tree = json.loads(listing)
    except (OSError, ValueError):
        return []

    entries, seen = [], set()

    def walk(dependencies, base):
        for name, info in (dependencies or {}).items():
            # npm hoists most packages to the top; a clash is kept beside its parent.
            path = next(
                (c for c in (base / "node_modules" / name, frontend / "node_modules" / name) if (c / "package.json").is_file()),
                None,
            )
            if path is None:
                continue
            package = json.loads((path / "package.json").read_text(encoding="utf-8"))
            label = f"{package.get('name', name)} {package.get('version', '')}".strip()
            if label not in seen:
                seen.add(label)
                license_name = package.get("license")
                if isinstance(license_name, dict):
                    license_name = license_name.get("type")
                texts = [
                    f.read_text(encoding="utf-8", errors="replace").strip()
                    for f in sorted(path.iterdir())
                    if f.is_file() and LICENSE_FILE.search(f.name)
                ]
                entries.append((label, license_name or "see the license text", texts))
            walk(info.get("dependencies"), path)

    walk(tree.get("dependencies"), frontend)
    return sorted(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT / "packaging" / "build" / "THIRD_PARTY_NOTICES.txt"))
    args = parser.parse_args()

    sections = [
        ("Python packages", python_entries()),
        ("Packages built into the web page (npm)", npm_entries()),
    ]
    lines = [
        "Lit Review includes the following third-party software.",
        "Each is used under the license shown, and its notice is reproduced below.",
        "",
    ]
    for title, entries in sections:
        lines += ["=" * 78, title, "=" * 78, ""]
        for label, license_name, texts in entries:
            lines += ["-" * 78, f"{label}  ({license_name})", "-" * 78]
            lines += [t for t in dict.fromkeys(texts)] or ["(no license file was shipped with this package)"]
            lines.append("")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{sum(len(e) for _, e in sections)} packages listed in {out}")


if __name__ == "__main__":
    main()
