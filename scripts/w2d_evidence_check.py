"""Check the evidence index and write a content manifest for the freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

REQUIRED = (
    "evidence/README.md",
    "evidence/compliance/index.md",
    "evidence/recovery/T19.txt",
    "evidence/recovery/T40.json",
    "evidence/faults/stream-kill_20261123T182353.json",
    "evidence/faults/minio-kill_20261123T182601.json",
    "evidence/benchmark/matrix.csv",
    "evidence/benchmark/summary.md",
    "evidence/tests/coverage.json",
    "evidence/deploy/clean-clone.log",
)

INDEXES = ("evidence/README.md", "evidence/compliance/index.md")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _is_git() -> bool:
    return (ROOT / ".git").exists()


def _tracked(paths: Iterable[str]) -> set[str]:
    """Return the subset of repository-relative paths tracked by git."""
    if not _is_git():
        return set(paths)
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--", *paths],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return set()
    if completed.returncode != 0:
        return set()
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def _links(path: Path) -> Iterable[Path]:
    text = path.read_text(encoding="utf-8")
    for target in LINK_RE.findall(text):
        target = target.strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = target.split("#", 1)[0]
        if not target:
            continue
        yield (path.parent / target).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only; never write a manifest (used by CI)",
    )
    args = parser.parse_args(argv)

    missing = [item for item in REQUIRED if not (ROOT / item).is_file()]
    broken: list[dict[str, str]] = []
    for index in INDEXES:
        path = ROOT / index
        if not path.is_file():
            continue
        for link in _links(path):
            if not link.exists():
                broken.append(
                    {
                        "index": index,
                        "target": str(link.relative_to(ROOT))
                        if link.is_relative_to(ROOT)
                        else str(link),
                    }
                )

    files = []
    for path in sorted(EVIDENCE.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if path.name.startswith("evidence-manifest_"):
            continue
        files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    evidence_paths = [item["path"] for item in files]
    tracked = _tracked(evidence_paths)
    untracked_evidence = sorted(set(evidence_paths) - tracked)
    required_untracked = [item for item in REQUIRED if item in untracked_evidence]

    result = (
        "PASS"
        if not missing
        and not broken
        and not untracked_evidence
        and not required_untracked
        else "FAIL"
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    commit = _commit()
    manifest = {
        "timestamp": stamp,
        "commit": commit,
        "result": result,
        "required_missing": missing,
        "required_untracked": required_untracked,
        "broken_links": broken,
        "untracked_evidence": untracked_evidence,
        "file_count": len(files),
        "files": files,
    }

    out: Path | None = None
    if not args.check:
        out = EVIDENCE / f"evidence-manifest_{stamp}_{commit}.json"
        out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "manifest": str(out.relative_to(ROOT)) if out else None,
                "result": result,
                "files": len(files),
                "required_missing": len(missing),
                "required_untracked": len(required_untracked),
                "broken_links": len(broken),
                "untracked_evidence": len(untracked_evidence),
            },
            indent=2,
        )
    )
    for item in missing:
        print(f"missing: {item}")
    for item in required_untracked:
        print(f"untracked required: {item}")
    for item in broken:
        print(f"broken: {item['index']} -> {item['target']}")
    for item in untracked_evidence:
        print(f"untracked evidence: {item}")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
