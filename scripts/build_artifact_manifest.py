"""Build the integrity manifest for the public HiReTest artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


RELEASE_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_ROOT = RELEASE_ROOT / "artifacts"
CASE_ROOT = ARTIFACTS_ROOT / "cases" / "Hiretest"
RESULT_ROOT = ARTIFACTS_ROOT / "results" / "Hiretest"
STANDARD_STAGES = ("1to2", "2to3", "3to4", "4to5", "5to6")


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def files(root: Path, pattern: str) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.glob(pattern), key=lambda item: item.name)


def stage_names() -> list[str]:
    detected = {path.name for path in CASE_ROOT.iterdir() if path.is_dir()} if CASE_ROOT.is_dir() else set()
    ordered = [stage for stage in STANDARD_STAGES if stage in detected]
    return ordered + sorted(detected.difference(STANDARD_STAGES))


def stage_record(stage: str) -> dict:
    case_dir = CASE_ROOT / stage
    cases = files(case_dir, "case*.txt")
    inputs = files(case_dir, "input*.txt")
    workbooks = files(RESULT_ROOT, f"analysis_{stage}*.xlsx")
    return {
        "stage": stage,
        "case_directory": case_dir.relative_to(RELEASE_ROOT).as_posix(),
        "case_count": len(cases),
        "input_count": len(inputs),
        "case_files": [{"path": path.name, "sha256": digest(path)} for path in cases],
        "input_files": [{"path": path.name, "sha256": digest(path)} for path in inputs],
        "result_workbooks": [
            {"path": path.relative_to(RELEASE_ROOT).as_posix(), "sha256": digest(path)}
            for path in workbooks
        ],
    }


def main() -> None:
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "artifact_source": "HiReTest main-method experimental outputs",
        "method": "HiReTest",
        "implementation_directory": "Hiretest",
        "stages": [stage_record(stage) for stage in stage_names()],
    }
    destination = ARTIFACTS_ROOT / "manifest.json"
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()
