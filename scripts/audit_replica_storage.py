"""Read-only parity evidence for the filesystem-backed parts of an OSS replica."""

import argparse
import hashlib
import json
import os
from pathlib import Path


def fingerprint(root: Path) -> dict:
    digest = hashlib.sha256()
    files = size = 0

    def visit(directory: Path) -> None:
        nonlocal files, size
        for path in sorted(directory.iterdir()):
            if path.is_symlink():
                raise ValueError("unexpected_symlink_in_replica_storage")
            relative = os.fsencode(path.relative_to(root))
            digest.update(len(relative).to_bytes(8, "big") + relative)
            if path.is_dir():
                digest.update(b"D")
                visit(path)
            elif path.is_file():
                with path.open("rb") as source:
                    digest.update(b"F" + hashlib.file_digest(source, "sha256").digest())
                    size += os.fstat(source.fileno()).st_size
                files += 1
            else:
                raise ValueError("unexpected_special_file_in_replica_storage")

    if not root.is_dir() or root.is_symlink():
        raise ValueError("missing_or_symlinked_replica_root")
    visit(root)
    return {"files": files, "bytes": size, "sha256": digest.hexdigest()}


def postgres_state(okf_root: Path, scope: int | None) -> dict:
    import psycopg

    with psycopg.connect(os.environ["SESSION_DATABASE_URL"], connect_timeout=5) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        db.execute("SET LOCAL statement_timeout = '10s'")
        capacity = db.execute(
            """SELECT current_setting('max_connections')::int,
                      current_setting('superuser_reserved_connections')::int,
                      coalesce(current_setting('reserved_connections', true)::int, 0),
                      count(*) FILTER (WHERE backend_type='client backend' AND pid<>pg_backend_pid()),
                      (SELECT rolconnlimit FROM pg_roles WHERE rolname=current_user),
                      (SELECT datconnlimit FROM pg_database WHERE datname=current_database())
                 FROM pg_stat_activity"""
        ).fetchone()
        scope_filter = (
            " AND s.state->>'portfolio_scope_id' = %s" if scope is not None else ""
        )
        params = (str(scope),) if scope is not None else ()
        pins = {
            row[0]
            for row in db.execute(
                """SELECT DISTINCT state->>'snapshot_id' FROM runtime.sessions s
                    WHERE state->>'snapshot_id' IS NOT NULL"""
                + scope_filter,
                params,
            )
        }
        receipts = db.execute(
            """SELECT r.snapshot_id, r.path, r.content_hash, count(*)
                 FROM okf.receipts r JOIN runtime.sessions s ON s.id=r.session_id
                WHERE true"""
            + scope_filter
            + " GROUP BY 1, 2, 3",
            params,
        ).fetchall()
    pins.update(row[0] for row in receipts)
    bundles = {
        p.name: p
        for p in (okf_root / "bundles").iterdir()
        if (p / "index.md").is_file()
    }
    invalid_receipts = 0
    for snapshot, name, expected_hash, count in receipts:
        directory = bundles.get(snapshot)
        path = (directory / name).resolve() if directory else None
        if (
            not path
            or not path.is_relative_to(directory.resolve())
            or not path.is_file()
        ):
            invalid_receipts += count
        elif (
            hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            != expected_hash
        ):
            invalid_receipts += count
    maximum, super_reserved, reserved, clients, role_limit, database_limit = capacity
    return {
        "max_connections": maximum,
        "superuser_reserved_connections": super_reserved,
        "reserved_connections": reserved,
        "other_client_connections": clients,
        "cluster_headroom": maximum - super_reserved - reserved - clients,
        "role_connection_limit": role_limit,
        "database_connection_limit": database_limit,
        "scope": scope,
        "references_sha256": hashlib.sha256(
            json.dumps([scope, sorted(pins), sorted(receipts)]).encode()
        ).hexdigest(),
        "receipts": sum(count for _, _, _, count in receipts),
        "receipts_missing_or_changed": invalid_receipts,
        "distinct_session_or_receipt_pins": len(pins),
        "pins_missing_index": sum(snapshot not in bundles for snapshot in pins),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="also check session/receipt pins and connection budget",
    )
    parser.add_argument(
        "--compare", type=Path, help="require identical trees to a prior report"
    )
    parser.add_argument(
        "--scope",
        type=int,
        help="limit PostgreSQL pin and receipt checks to one portfolio",
    )
    args = parser.parse_args()
    if args.scope is not None and (not args.postgres or args.scope < 1):
        parser.error("--scope requires --postgres and a positive portfolio ID")
    roots = {
        "okf": Path(os.getenv("OKF_DATA_ROOT", "/data/okf")),
        "simulator": Path(os.getenv("SIMULATOR_ROOT", "/data/simulator")),
        "tools": Path(os.getenv("TOOL_REGISTRY_ROOT", "/data/tools")),
    }
    trees = {name: fingerprint(path) for name, path in roots.items()}
    report = {"trees": trees}
    ok = True
    if args.postgres:
        state = postgres_state(roots["okf"], args.scope)
        report["postgres"] = state
        ok = state["pins_missing_index"] == state["receipts_missing_or_changed"] == 0
    if args.compare:
        baseline = json.loads(args.compare.read_text())
        expected = baseline["trees"]
        if args.postgres:
            report["same_references"] = (
                baseline.get("postgres", {}).get("references_sha256")
                == state["references_sha256"]
            )
            ok = ok and report["same_references"]
        mismatches = sorted(
            name
            for name in trees.keys() | expected.keys()
            if trees.get(name) != expected.get(name)
        )
        report["different_trees"] = mismatches
        ok = ok and not mismatches
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
