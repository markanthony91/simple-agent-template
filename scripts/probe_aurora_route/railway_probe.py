import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = "511a294c-8d6a-4906-bd26-e8e33011eac5"
TARGETS = {
    "gateway": ("7dee96d9-0c14-4a9c-8b7f-4d2358e2ea91", "node -e", "gateway.cjs"),
    "route": (
        "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec",
        "/app/.venv/bin/python -c",
        "route.py",
    ),
}


def railway_json(service, runtime, source):
    command = [
        "railway",
        "ssh",
        "-p",
        PROJECT,
        "-e",
        "production",
        "-s",
        service,
        runtime + " " + shlex.quote(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=290)
    lines = [
        line[5:] for line in result.stdout.splitlines() if line.startswith("SAFE ")
    ]
    if len(lines) != 1:
        error = next(
            (
                line
                for line in (result.stdout + result.stderr).splitlines()
                if line.startswith("safe_error ")
            ),
            "",
        )
        raise SystemExit(
            f"No sanitized response from {service} (exit {result.returncode}, {error})"
        )
    record = json.loads(lines[0])
    return record


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        raise SystemExit("Usage: python3 railway_probe.py gateway|route")
    service, runtime, filename = TARGETS[sys.argv[1]]
    print(
        json.dumps(
            railway_json(service, runtime, (HERE / filename).read_text()), indent=2
        )
    )
