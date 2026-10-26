"""Forget active Relationship Artifacts before rolling back to an older binary."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifact import revise  # noqa: E402
from store import open_store  # noqa: E402


def deactivate_relationships(db_path: str) -> tuple[int, int, int]:
    """Forget active relationship heads through CAS without deleting evidence."""
    store = open_store(str(db_path))
    try:
        active = store.artifacts.list(family="relationship", state="active")
        forgotten = 0
        failed = 0
        for art in active:
            replacement = revise(art, state="forgotten")
            try:
                store.artifacts.commit(
                    replacement,
                    expected_revision=art.header.revision,
                    op="forget",
                    reason="offline relationship rollback",
                    source_ids=tuple(replacement.header.lineage.sources),
                )
            except Exception:  # noqa: BLE001 - report bounded counts only
                failed += 1
            else:
                forgotten += 1
        return len(active), forgotten, failed
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forget active Relationship Artifacts before binary rollback."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--confirmed", action="store_true", required=True)
    args = parser.parse_args(argv)
    active, forgotten, failed = deactivate_relationships(args.db)
    print(f"active={active} forgotten={forgotten} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
