"""Verified multi-destination media offload (roadmap Phase 5).

- Each source file is read once and streamed to every destination.
- Copies land in a temp file and are renamed into place only after the
  destination has been re-read from disk and its hash matches the source.
- Existing destination files are never overwritten: an identical file is
  skipped (so offloads are resumable), a different one is reported as a
  conflict.
- Each destination gets ``OFFLOAD_MANIFEST_<timestamp>.json`` listing every
  file with its size and hash.

Hash: ``xxh3_128`` if the ``xxhash`` package is installed (fast), else
``sha256``. Either can be forced.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CHUNK = 8 * 1024 * 1024
SKIP_NAMES = {".DS_Store", "Thumbs.db"}


def new_hasher(algorithm: str):
    if algorithm == "xxh3_128":
        import xxhash

        return xxhash.xxh3_128()
    return hashlib.new(algorithm)


def default_algorithm() -> str:
    try:
        import xxhash  # noqa: F401

        return "xxh3_128"
    except ImportError:
        return "sha256"


def file_hash(path: Path, algorithm: str) -> str:
    h = new_hasher(algorithm)
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileResult:
    rel: str
    size: int
    digest: str
    status: dict[str, str] = field(default_factory=dict)  # dest -> copied/skipped/conflict/failed


@dataclass
class OffloadReport:
    algorithm: str
    files: list[FileResult]
    manifests: list[Path]

    @property
    def ok(self) -> bool:
        return all(s in ("copied", "skipped") for f in self.files for s in f.status.values())

    def problems(self) -> list[str]:
        return [f"{f.rel} -> {d}: {s}" for f in self.files for d, s in f.status.items() if s not in ("copied", "skipped")]


def _source_files(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*") if p.is_file() and p.name not in SKIP_NAMES and not p.name.startswith("._"))


def offload(
    source: str | Path,
    destinations: list[str | Path],
    algorithm: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> OffloadReport:
    src = Path(source)
    dests = [Path(d) for d in destinations]
    if not src.is_dir():
        raise ValueError(f"source {src} is not a directory")
    if not dests:
        raise ValueError("need at least one destination")
    for d in dests:
        if d.resolve() == src.resolve() or src.resolve() in d.resolve().parents:
            raise ValueError(f"destination {d} is inside the source")
        d.mkdir(parents=True, exist_ok=True)
    algorithm = algorithm or default_algorithm()

    results: list[FileResult] = []
    for path in _source_files(src):
        rel = path.relative_to(src).as_posix()
        if progress:
            progress(rel)
        targets: dict[Path, Path] = {}
        res = FileResult(rel, path.stat().st_size, "")
        for d in dests:
            out = d / rel
            if out.exists():
                res.status[str(d)] = "pending-compare"
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                targets[d] = out.with_name(out.name + ".partial")

        h = new_hasher(algorithm)
        handles = {d: open(tmp, "wb") for d, tmp in targets.items()}
        try:
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK):
                    h.update(chunk)
                    for fh in handles.values():
                        fh.write(chunk)
            for fh in handles.values():
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            for fh in handles.values():
                fh.close()
        res.digest = h.hexdigest()

        for d in dests:
            out = d / rel
            if d in targets:
                tmp = targets[d]
                if file_hash(tmp, algorithm) == res.digest:
                    os.replace(tmp, out)
                    res.status[str(d)] = "copied"
                else:
                    tmp.unlink(missing_ok=True)
                    res.status[str(d)] = "failed: verification mismatch"
            else:
                same = out.stat().st_size == res.size and file_hash(out, algorithm) == res.digest
                res.status[str(d)] = "skipped" if same else "conflict: different file already exists"
        results.append(res)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    manifests = []
    for d in dests:
        m = d / f"OFFLOAD_MANIFEST_{stamp}.json"
        m.write_text(json.dumps({
            "source": str(src.resolve()),
            "created": stamp,
            "algorithm": algorithm,
            "files": [{"path": r.rel, "size": r.size, "hash": r.digest, "status": r.status[str(d)]} for r in results],
        }, indent=2))
        manifests.append(m)
    return OffloadReport(algorithm, results, manifests)


def verify_manifest(manifest: str | Path) -> list[str]:
    """Re-hash everything a manifest lists (relative to its folder). Returns problems."""
    manifest = Path(manifest)
    data = json.loads(manifest.read_text())
    problems = []
    for entry in data["files"]:
        if entry["status"] not in ("copied", "skipped"):
            continue
        p = manifest.parent / entry["path"]
        if not p.exists():
            problems.append(f"missing: {entry['path']}")
        elif file_hash(p, data["algorithm"]) != entry["hash"]:
            problems.append(f"hash mismatch: {entry['path']}")
    return problems
