#!/opt/venv/bin/python
"""Operator control CLI for a running Palworld container."""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional


if not hasattr(signal, "SIGCONT"):
    signal.SIGCONT = signal.SIGTERM  # type: ignore[attr-defined]


def read_start_ticks(pid: int) -> Optional[int]:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields_after_comm = stat_text.rsplit(")", 1)[1].split()
        return int(fields_after_comm[19])
    except (OSError, ValueError, IndexError):
        return None


def load_state(runtime_dir: Path) -> dict:
    state_file = runtime_dir / "server-state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("Palworld runtime state is not available") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read Palworld runtime state: {exc}") from exc

    try:
        state["pid"] = int(state["pid"])
        state["pgid"] = int(state["pgid"])
        state["process_start_ticks"] = int(state["process_start_ticks"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Palworld runtime state is incomplete") from exc
    return state


def validate_process(state: dict) -> None:
    actual_ticks = read_start_ticks(state["pid"])
    if actual_ticks is None:
        raise RuntimeError("Palworld process is not running")
    if actual_ticks != state["process_start_ticks"]:
        raise RuntimeError("Stale Palworld process identity; refusing control action")


def show_status(runtime_dir: Path) -> int:
    state = load_state(runtime_dir)
    validate_process(state)
    print(json.dumps(state, sort_keys=True))
    return 0


def resume(runtime_dir: Path) -> int:
    state = load_state(runtime_dir)
    validate_process(state)
    if state.get("state") != "paused":
        raise RuntimeError(f"Server is not paused (state={state.get('state')})")

    os.killpg(state["pgid"], signal.SIGCONT)
    marker = runtime_dir / "manual-resume"
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(str(time.time()), encoding="utf-8")
    os.replace(temporary, marker)
    print("Palworld resume requested")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="palworld-control")
    parser.add_argument("command", choices=("status", "resume"))
    args = parser.parse_args()
    runtime_dir = Path(os.getenv("PALWORLD_RUNTIME_DIR", "/run/palworld"))

    try:
        if args.command == "status":
            return show_status(runtime_dir)
        return resume(runtime_dir)
    except RuntimeError as exc:
        print(f"palworld-control: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
