"""Portable paths for the public release layout."""

from __future__ import annotations

import os
from pathlib import Path


def release_root() -> Path:
    configured = os.environ.get("HIRETEST_RELEASE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def artifacts_root() -> Path:
    return release_root() / "artifacts"


def public_prompt_root() -> Path:
    return release_root() / "prompts" / "public_templates"


def data_workspace_root() -> Path:
    """Return the configured working-data directory or the local placeholder."""
    configured = os.environ.get("HIRETEST_DERIVED_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return release_root() / "data"


def generated_artifacts_root() -> Path:
    """Return a writable location that does not overwrite released artifacts."""
    return artifacts_root() / "generated"


def restricted_data_root() -> Path:
    configured = os.environ.get("HIRETEST_DATA_ROOT")
    if not configured:
        raise RuntimeError(
            "Set HIRETEST_DATA_ROOT to an authorized extracted data package. "
            "Raw student submissions are not included in the public repository."
        )
    return Path(configured).expanduser().resolve()
