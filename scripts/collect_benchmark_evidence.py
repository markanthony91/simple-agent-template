"""Collect only timing/path evidence for the synthetic benchmark threads."""

import json
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
TARGET = [
    "-p",
    "511a294c-8d6a-4906-bd26-e8e33011eac5",
    "-s",
    "861cf8e9-935f-4673-baf0-6bb438eac5fb",
    "-e",
    "production",
]


def command(args):
    return subprocess.run(
        ["railway", *args], capture_output=True, text=True, check=True
    ).stdout


def collect():
    reports = []
    for chat in json.loads((DOCS / "CHAT_BENCHMARK_RESULTS.json").read_text()):
        tid = chat["thread_id"]
        raw = command(
            [
                "logs",
                *TARGET,
                "--since",
                "2h",
                "--lines",
                "300",
                "--filter",
                tid,
                "--json",
            ]
        )
        events = []
        for line in raw.splitlines():
            data = json.loads(line)
            msg = re.sub(r"\x1b\[[0-9;]*m", "", data.get("message", ""))
            match = re.search(r"\brun_id=([^\s]+)", msg)
            run = match.group(1) if match else None
            if '"event": "TOOL_CALL"' in msg:
                entry = json.JSONDecoder().raw_decode(msg[msg.index("{") :])[0]
                if entry.get("status") == "success":
                    events.append(
                        {
                            "at": msg.split()[0],
                            "run_id": run,
                            "tool": entry["tool"],
                            "duration_ms": entry.get("duration_ms"),
                            "args": entry.get("args")
                            if entry["tool"].startswith("okf_")
                            else None,
                        }
                    )
            if "Background run succeeded" in msg:
                events.append(
                    {
                        "at": msg.split()[0],
                        "type": "run",
                        **dict(re.findall(r"(run_\w+)=([^\s]+)", msg)),
                    }
                )
        with urllib.request.urlopen(
            "https://langgraph-simple-agent-clean-production.up.railway.app/threads/"
            + tid
            + "/state",
            timeout=30,
        ) as response:
            messages = json.load(response)["values"]["messages"]
        batches = [
            [{"name": c["name"], "id": c["id"]} for c in m.get("tool_calls", [])]
            for m in messages
            if m.get("tool_calls")
        ]
        reports.append(
            {
                "scenario": chat["scenario"],
                "thread_id": tid,
                "tool_batches": batches,
                "events": events,
            }
        )
    (DOCS / "CHAT_SERVER_TIMINGS.json").write_text(json.dumps(reports, indent=2))
    metrics = json.loads(
        command(
            [
                "metrics",
                *TARGET,
                "--cpu",
                "--memory",
                "--since",
                "2h",
                "--raw",
                "--json",
            ]
        )
    )
    (DOCS / "RAILWAY_BENCHMARK_METRICS.json").write_text(json.dumps(metrics, indent=2))
    for report in reports:
        for run in [e for e in report["events"] if e.get("type") == "run"]:
            start = datetime.fromisoformat(run["run_started_at"])
            end = datetime.fromisoformat(run["run_ended_at"])
            tools = [
                e
                for e in report["events"]
                if e.get("tool") and e["run_id"] == run["run_id"]
            ]
            intervals = []
            for tool in tools:
                stop = datetime.fromisoformat(tool["at"])
                intervals.append(
                    (stop - timedelta(milliseconds=tool["duration_ms"]), stop)
                )
            merged = []
            for a, b in sorted(intervals):
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                else:
                    merged.append((a, b))
            tool_wall = sum((b - a).total_seconds() * 1000 for a, b in merged)
            resource = {}
            for name in ["CPU_USAGE", "MEMORY_USAGE_GB"]:
                points = [
                    x["value"]
                    for x in metrics["measurements"][name]
                    if start - timedelta(seconds=30)
                    <= datetime.fromisoformat(x["ts"])
                    <= end + timedelta(seconds=30)
                ]
                resource[name + "_max_near_run"] = max(points) if points else None
            run["tool_wall_ms"] = round(tool_wall, 2)
            run["remaining_exec_ms"] = round(float(run["run_exec_ms"]) - tool_wall, 2)
            run["resources"] = resource
        print(
            json.dumps(
                {
                    "scenario": report["scenario"],
                    "runs": [e for e in report["events"] if e.get("type") == "run"],
                }
            )
        )
    (DOCS / "CHAT_SERVER_TIMINGS.json").write_text(json.dumps(reports, indent=2))


if __name__ == "__main__":
    collect()
