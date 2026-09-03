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


def react_prompt_root() -> Path:
    return release_root() / "prompts" / "react_agent"


def restricted_data_root() -> Path:
    configured = os.environ.get("HIRETEST_DATA_ROOT")
    if not configured:
        raise RuntimeError(
            "Set HIRETEST_DATA_ROOT to an authorized extracted data package. "
            "Raw student submissions are not included in the public repository."
        )
    return Path(configured).expanduser().resolve()


def tool_path(env_name: str, relative_default: str) -> Path:
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser().resolve()
    return release_root() / "tools" / relative_default
