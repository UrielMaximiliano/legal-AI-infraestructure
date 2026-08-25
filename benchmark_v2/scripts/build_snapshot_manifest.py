"""Build a content-addressed manifest for a local benchmark snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(root: Path, source_label: str | None = None) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    groups: dict[tuple[int, str], list[str]] = defaultdict(list)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        digest = sha256_file(path)
        relative = path.relative_to(root).as_posix()
        record = {
            "relative_path": relative,
            "bytes": stat.st_size,
            "sha256": digest,
            "mtime_ns": stat.st_mtime_ns,
            "source": source_label or "local_snapshot",
        }
        records.append(record)
        groups[(stat.st_size, digest)].append(relative)
    duplicate_groups = [
        {"bytes": size, "sha256": digest, "paths": paths}
        for (size, digest), paths in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]))
        if len(paths) > 1
    ]
    return {
        "schema_version": "benchmark-v2-snapshot-manifest-1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()),
        "file_count": len(records),
        "total_bytes": sum(int(item["bytes"]) for item in records),
        "unique_content_count": len(groups),
        "duplicate_content_group_count": len(duplicate_groups),
        "files": records,
        "duplicate_content_groups": duplicate_groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-label", default=None)
    args = parser.parse_args()
    manifest = build_manifest(args.snapshot_root, args.source_label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("file_count", "total_bytes", "unique_content_count", "duplicate_content_group_count")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
