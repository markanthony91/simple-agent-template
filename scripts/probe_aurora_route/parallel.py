"""Four independent SSE clients. Default to read-only scope and schema preflight."""

import hashlib
import json
import sys
from uuid import UUID

from railway_probe import HERE, TARGETS, railway_json

PG = """
import os,json,psycopg
from psycopg.rows import dict_row
with psycopg.connect(os.environ['SESSION_DATABASE_URL'], row_factory=dict_row,
                     options='-c default_transaction_read_only=on -c statement_timeout=5000') as db:
    have_start = db.execute("SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_schema='langgraph' AND table_name='oss_runs' AND column_name='started_at') AS ok").fetchone()['ok']
    out = {'started_at_available':have_start}
    if have_start:
        out['sample'] = db.execute(SQL, (json.dumps(ROWS), AID)).fetchone()
    print('SAFE '+json.dumps(out))
"""
SQL = """
WITH probes AS (
  SELECT * FROM jsonb_to_recordset(%s::jsonb)
    AS p(ordinal int,thread uuid, run uuid, first_text_ms int)
), measured AS (
  SELECT p.ordinal,r.run_id,p.first_text_ms,r.status,r.created_at,r.started_at,r.updated_at
  FROM probes p
  JOIN langgraph.oss_runs r ON r.run_id=p.run AND r.thread_id=p.thread
  JOIN langgraph.oss_threads t ON t.thread_id=p.thread
  WHERE t.metadata->>'zerai_scope_id'='7' AND r.assistant_id=%s
    AND t.metadata->>'assistant_id'=r.assistant_id
), terminal AS (
  SELECT * FROM measured WHERE started_at IS NOT NULL
    AND status IN ('succeeded','failed','cancelled') AND updated_at >= started_at
), durations AS (
  SELECT m.*, extract(epoch FROM m.started_at-m.created_at)*1000 AS queue_ms,
         min(created_at) OVER () AS baseline,
         (SELECT count(*) FROM terminal t WHERE t.started_at<=m.started_at
            AND t.updated_at>m.started_at) AS active_at_start
  FROM terminal m
)
SELECT (SELECT count(*) FROM measured) AS matched, count(*) AS terminal,
       count(*) FILTER (WHERE status='succeeded') AS succeeded,
       max(active_at_start) AS peak_overlap,
       round(greatest(0,extract(epoch FROM min(updated_at)-max(started_at))*1000)::numeric,1)::float AS common_overlap_ms,
       round((percentile_cont(.95) WITHIN GROUP (ORDER BY queue_ms))::numeric,1)::float AS queue_p95_ms,
       round((percentile_cont(.95) WITHIN GROUP (ORDER BY first_text_ms))::numeric,1)::float AS sse_first_text_p95_ms,
       jsonb_agg(jsonb_build_object('turn',ordinal,'queue_ms',round(queue_ms,1),
           'start_offset_ms',round(1000*extract(epoch FROM started_at-baseline),1),
           'end_offset_ms',round(1000*extract(epoch FROM updated_at-baseline),1),
           'status',status) ORDER BY ordinal) AS run_intervals
FROM durations
"""
PLAYGROUND = "efb21236-bdc2-4d74-94e1-bc60de92f9a6"


def main(mode):
    source = (
        "const MODE=" + json.dumps(mode) + ";\n" + (HERE / "parallel.cjs").read_text()
    )
    out = railway_json(PLAYGROUND, "node -e", source)
    assistant = str(UUID(out.pop("assistant")))
    rows = []
    for i, turn in enumerate(out.get("turns", []), 1):
        thread = str(UUID(turn.pop("thread")))
        run = turn.pop("run")
        rows.append(
            dict(
                ordinal=i,
                thread=thread,
                run=str(UUID(run)) if run else None,
                first_text_ms=turn["first_text_ms"],
            )
        )
        turn["turn"] = i
        turn["thread_hash"] = hashlib.sha256(thread.encode()).hexdigest()[:16]
        if run:
            turn["run_hash"] = hashlib.sha256(run.encode()).hexdigest()[:16]
    # Flush results before accessing PostgreSQL so a read failure retains client evidence.
    print(json.dumps({"client": out}, ensure_ascii=False), flush=True)
    service, runtime, _ = TARGETS["route"]
    src = f"SQL={SQL!r}\nROWS={rows!r}\nAID={assistant!r}\n" + PG
    print(
        json.dumps(
            {"database": railway_json(service, runtime, src)}, ensure_ascii=False
        ),
        flush=True,
    )


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) == 2 else "preflight"
    if mode not in {"preflight", "canary"}:
        raise SystemExit("Use preflight (read only) or canary (four live turns)")
    main(mode)
