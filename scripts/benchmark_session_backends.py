"""Compare SQLite and PostgreSQL with synthetic OKF and identity tool calls."""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
import time
from pathlib import Path
from uuid import uuid4


POLICY_PATH = "INSTITUTIONS/fastpay/policy.md"
POLICY = """---
type: Policy
status: published
institution: FastPay
product: cartao_de_credito
---
# Synthetic benchmark policy
No customer data is used by this benchmark.
"""


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def main() -> None:
    if not os.getenv("SESSION_DATABASE_URL", "").strip():
        raise SystemExit("SESSION_DATABASE_URL_required")
    iterations = max(3, int(os.getenv("BENCHMARK_ITERATIONS", "20")))
    prefix = f"canary-{uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="session-backend-benchmark-") as root:
        os.environ["OKF_DATA_ROOT"] = str(Path(root) / "okf")
        os.environ["SIMULATOR_ROOT"] = str(Path(root) / "simulator")
        os.environ["SESSION_ROOT"] = str(Path(root) / "sessions")

        from langchain.tools import ToolRuntime
        from langchain_core.messages import HumanMessage

        from simple_agent.services.okf_store import PersistentOKFStore
        from simple_agent.services.session_store import SessionStore
        from simple_agent.services.simulator_store import SimulatorStore
        from simple_agent.tools import collection_tools, okf_tools

        okf_store = PersistentOKFStore()
        okf_store.import_bundle(
            "postgres-canary", "0.2", {"index.md": "# Test", POLICY_PATH: POLICY}
        )
        okf_tools.store = okf_store

        def runtime(key: str) -> ToolRuntime:
            return ToolRuntime(
                state={
                    "messages": [HumanMessage(content="12345678900", id="synthetic")]
                },
                context={},
                config={"configurable": {"thread_id": key}},
                stream_writer=lambda _: None,
                tool_call_id="benchmark",
                store=None,
            )

        def measure(backend: str) -> dict[str, dict[str, float]]:
            os.environ["SESSION_BACKEND"] = backend
            contract_key = f"{prefix}-{backend}-contract"
            contract_store = SessionStore()
            fixture = SimulatorStore().load()
            fixture.setdefault("creditor_name", fixture["institution"])
            fixture.setdefault("phone", "+5511999999999")
            if not contract_store.create(contract_key, fixture, demo=True):
                raise RuntimeError("synthetic_demo_create_failed")
            if contract_store.create(contract_key, fixture, demo=True):
                raise RuntimeError("synthetic_demo_idempotency_failed")
            with contract_store.transaction(contract_key) as state:
                state["rollback_marker"] = "preserved"
            try:
                with contract_store.transaction(contract_key) as state:
                    state["rollback_marker"] = "must_not_commit"
                    raise RuntimeError("synthetic_rollback")
            except RuntimeError as error:
                if str(error) != "synthetic_rollback":
                    raise
            if contract_store.read(contract_key)["rollback_marker"] != "preserved":
                raise RuntimeError("synthetic_transaction_rollback_failed")
            if not contract_store.reset_demo(contract_key):
                raise RuntimeError("synthetic_demo_reset_failed")
            unbound_key = f"{contract_key}-unbound"
            if not contract_store.ensure_unbound(unbound_key):
                raise RuntimeError("synthetic_unbound_create_failed")
            if contract_store.ensure_unbound(unbound_key):
                raise RuntimeError("synthetic_unbound_idempotency_failed")
            SessionStore().read(f"{prefix}-{backend}-warmup")
            samples: dict[str, list[float]] = {
                "session_transaction": [],
                "okf_read": [],
                "verify_identity": [],
            }
            for index in range(iterations):
                key = f"{prefix}-{backend}-{index}"
                started = time.perf_counter()
                with SessionStore().transaction(key) as state:
                    state["benchmark"] = True
                samples["session_transaction"].append(
                    (time.perf_counter() - started) * 1000
                )

                started = time.perf_counter()
                okf_tools.okf_read.func(path=POLICY_PATH, runtime=runtime(key))
                samples["okf_read"].append((time.perf_counter() - started) * 1000)

                identity_key = f"{key}-identity"
                started = time.perf_counter()
                result = json.loads(
                    collection_tools.verify_and_get_customer.func(
                        cpf="12345678900",
                        full_name="João da Silva",
                        runtime=runtime(identity_key),
                    )
                )
                if result.get("verified") is not True:
                    raise RuntimeError("synthetic_identity_benchmark_failed")
                samples["verify_identity"].append(
                    (time.perf_counter() - started) * 1000
                )
            return {
                name: {
                    "p50_ms": round(statistics.median(values), 2),
                    "p95_ms": round(percentile(values, 0.95), 2),
                }
                for name, values in samples.items()
            }

        import psycopg

        try:
            results = {backend: measure(backend) for backend in ("sqlite", "postgres")}
        finally:
            with psycopg.connect(os.environ["SESSION_DATABASE_URL"]) as db:
                db.execute(
                    "DELETE FROM runtime.sessions WHERE id LIKE %s", (f"{prefix}%",)
                )
        print(json.dumps({"iterations": iterations, "results": results}, indent=2))


if __name__ == "__main__":
    main()
