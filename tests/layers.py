"""Automatic test-layer discovery for local runs and CI.

Test files stay flat for unittest compatibility. New tests are classified by
name conventions so adding a test no longer requires editing a central map.
"""

from __future__ import annotations

from pathlib import Path

ALL_LAYERS = ("unit", "contract", "conformance", "integration", "host", "smoke")
SMOKE = {"test_package.py", "test_eval_harness.py", "test_smoke.py"}
CONTRACT = {"test_public_interfaces.py", "test_runtime_host_contract.py"}
INTEGRATION_MARKERS = (
    "e2e", "absorb", "attention", "astrbot", "continuity", "dream_eval",
    "failure", "group", "privacy", "identity", "lineage", "migration",
    "kernel", "recall", "self_impression", "reinforcement", "run_recorder",
    "runtime_", "temporal", "webui", "console",
)


def _test_files() -> list[Path]:
    return sorted(Path(__file__).resolve().parent.glob("test_*.py"))


def _layer_for(path: Path) -> str:
    name = path.name
    if name in SMOKE:
        return "smoke"
    if name in CONTRACT or name.endswith("_contract.py"):
        return "contract"
    if "conformance" in name:
        return "conformance"
    if name.endswith("_host.py"):
        return "host"
    if any(marker in name for marker in INTEGRATION_MARKERS):
        return "integration"
    return "unit"


def files_for(layer: str) -> tuple[str, ...]:
    """Return test file names for one layer; all means every discovered test."""
    files = _test_files()
    if layer == "all":
        return tuple(path.name for path in files)
    if layer not in ALL_LAYERS:
        raise ValueError(f"unknown test layer: {layer}")
    return tuple(path.name for path in files if _layer_for(path) == layer)
