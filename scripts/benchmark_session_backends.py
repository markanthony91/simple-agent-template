"""Compare SQLite and PostgreSQL with synthetic OKF and identity tool calls."""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4


POLICY_PATH = "INSTITUTIONS/fastpay/policy.md"
POLICY = """---
type: Policy
status: published
institution: FastPay
product: cartao_de_credito
effective_from: "2026-01-01T00:00:00Z"
effective_until: "2027-01-01T00:00:00Z"
negotiation:
  max_installments: 3
  max_discount_percentage: "0"
  offer_discount_percentage: "0"
  payment_types: [cash, installment]
payment:
  methods: [pix, boleto]
  methods_by_payment_type:
    cash: [pix, boleto]
    installment: [boleto]
  delivery_channels: [email]
---
# Synthetic benchmark policy
No customer data is used by this benchmark.

## Payment terms

Up to three synthetic boleto installments, with no discount.
"""


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def main() -> None:
    if not os.getenv("SESSION_DATABASE_URL", "").strip():
        raise SystemExit("SESSION_DATABASE_URL_required")
    iterations = max(3, int(os.getenv("BENCHMARK_ITERATIONS", "20")))
    workers = max(1, int(os.getenv("BENCHMARK_CONCURRENCY", "4")))
    prefix = f"canary-{uuid4().hex}"
    benchmark_root = os.getenv("BENCHMARK_ROOT", "").strip() or None
    if benchmark_root and not Path(benchmark_root).is_dir():
        raise SystemExit("BENCHMARK_ROOT_must_exist")
    with tempfile.TemporaryDirectory(
        prefix="session-backend-benchmark-", dir=benchmark_root
    ) as root:
        os.environ["OKF_DATA_ROOT"] = str(Path(root) / "okf")
        os.environ["SIMULATOR_ROOT"] = str(Path(root) / "simulator")

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

        def mark_session(store, key: str) -> None:
            with store.transaction(key) as state:
                state["benchmark"] = True

        def runtime(
            key: str, text: str = "12345678900", message_id: str = "synthetic"
        ) -> ToolRuntime:
            return ToolRuntime(
                state={"messages": [HumanMessage(content=text, id=message_id)]},
                context={},
                config={"configurable": {"thread_id": key}},
                stream_writer=lambda _: None,
                tool_call_id="benchmark",
                store=None,
            )

        def measure(
            label: str,
            backend: str,
            journal: str = "",
            synchronous: str = "",
        ) -> dict:
            from simple_agent.graph import calculator, utc_now
            from simple_agent.tools import payment_tools

            os.environ["SESSION_BACKEND"] = backend
            os.environ["SESSION_ROOT"] = str(Path(root) / "sessions" / label)
            if journal:
                os.environ["SESSION_SQLITE_JOURNAL_MODE"] = journal
                os.environ["SESSION_SQLITE_SYNCHRONOUS"] = synchronous
            else:
                os.environ.pop("SESSION_SQLITE_JOURNAL_MODE", None)
                os.environ.pop("SESSION_SQLITE_SYNCHRONOUS", None)
            contract_key = f"{prefix}-{label}-contract"
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
            contract_rt = runtime(contract_key)
            verified = json.loads(
                collection_tools.verify_and_get_customer.func(
                    cpf="12345678900",
                    full_name="João da Silva",
                    runtime=contract_rt,
                )
            )
            if verified.get("verified") is not True:
                raise RuntimeError("synthetic_demo_identity_failed")
            okf_tools.okf_read.func(path=POLICY_PATH, runtime=contract_rt)
            contract_offer = json.loads(
                payment_tools.generate_payment_offer.func(
                    payment_type="installment",
                    installments=3,
                    method="boleto",
                    policy_path=POLICY_PATH,
                    runtime=runtime(
                        contract_key,
                        "Quero pagar em três parcelas por boleto",
                        "contract-payment",
                    ),
                )
            )
            if contract_offer.get("created") is not True:
                raise RuntimeError("synthetic_demo_payment_failed")
            if not json.loads(
                payment_tools.get_boleto_second_copy.func(runtime=contract_rt)
            ).get("found"):
                raise RuntimeError("synthetic_demo_second_copy_failed")
            attacker = f"{contract_key}-attacker"
            try:
                with SessionStore().transaction(
                    attacker, persist_payments=True
                ) as state:
                    state["agreements"]["copy"] = contract_offer["agreement"]
            except ValueError as error:
                if str(error) != "agreement_origin_mismatch":
                    raise
            else:
                raise RuntimeError("synthetic_payment_origin_guard_failed")
            if SessionStore().exists(attacker):
                raise RuntimeError("synthetic_payment_origin_rollback_failed")
            if not contract_store.reset_demo(contract_key):
                raise RuntimeError("synthetic_demo_payment_reset_failed")
            reset_copy = json.loads(
                payment_tools.get_boleto_second_copy.func(runtime=contract_rt)
            )
            if reset_copy.get("reason") != "identity_verification_required":
                raise RuntimeError("synthetic_demo_payment_reset_leaked")
            unbound_key = f"{contract_key}-unbound"
            if not contract_store.ensure_unbound(unbound_key):
                raise RuntimeError("synthetic_unbound_create_failed")
            if contract_store.ensure_unbound(unbound_key):
                raise RuntimeError("synthetic_unbound_idempotency_failed")
            SessionStore().read(f"{prefix}-{label}-warmup")
            samples: dict[str, list[float]] = {
                "utc_now": [],
                "calculator": [],
                "session_transaction": [],
                "okf_index": [],
                "okf_list": [],
                "okf_search": [],
                "okf_read": [],
                "okf_read_section": [],
                "verify_identity": [],
                "generate_payment_offer": [],
                "get_boleto_second_copy": [],
                "get_payment_status": [],
            }

            def timed(name: str, function):
                started = time.perf_counter()
                result = function()
                samples[name].append((time.perf_counter() - started) * 1000)
                return result

            for index in range(iterations):
                timed("utc_now", lambda: utc_now.invoke({}))
                timed("calculator", lambda: calculator.invoke({"expression": "17*19"}))

                key = f"{prefix}-{label}-{index}"
                timed(
                    "session_transaction",
                    lambda: mark_session(SessionStore(), key),
                )
                rt = runtime(key)
                timed("okf_index", lambda: okf_tools.okf_index.func(runtime=rt))
                timed("okf_list", lambda: okf_tools.okf_list.func(runtime=rt))
                timed(
                    "okf_search",
                    lambda: okf_tools.okf_search.func(
                        query="synthetic benchmark", runtime=rt
                    ),
                )
                timed(
                    "okf_read",
                    lambda: okf_tools.okf_read.func(path=POLICY_PATH, runtime=rt),
                )
                timed(
                    "okf_read_section",
                    lambda: okf_tools.okf_read_section.func(
                        path=POLICY_PATH, heading="Payment terms", runtime=rt
                    ),
                )

                identity_key = f"{key}-identity"
                result = json.loads(
                    timed(
                        "verify_identity",
                        lambda: collection_tools.verify_and_get_customer.func(
                            cpf="12345678900",
                            full_name="João da Silva",
                            runtime=runtime(identity_key),
                        ),
                    )
                )
                if result.get("verified") is not True:
                    raise RuntimeError("synthetic_identity_benchmark_failed")

                payment_key = f"{key}-payment"
                payment_rt = runtime(payment_key)
                verified = json.loads(
                    collection_tools.verify_and_get_customer.func(
                        cpf="12345678900",
                        full_name="João da Silva",
                        runtime=payment_rt,
                    )
                )
                if verified.get("verified") is not True:
                    raise RuntimeError("synthetic_payment_identity_failed")
                okf_tools.okf_read.func(path=POLICY_PATH, runtime=payment_rt)
                offer = json.loads(
                    timed(
                        "generate_payment_offer",
                        lambda: payment_tools.generate_payment_offer.func(
                            payment_type="installment",
                            installments=3,
                            method="boleto",
                            policy_path=POLICY_PATH,
                            runtime=runtime(
                                payment_key,
                                "Quero pagar em três parcelas por boleto",
                                f"payment-{index}",
                            ),
                        ),
                    )
                )
                if offer.get("created") is not True:
                    raise RuntimeError(f"synthetic_payment_offer_failed:{offer}")
                second_copy = json.loads(
                    timed(
                        "get_boleto_second_copy",
                        lambda: payment_tools.get_boleto_second_copy.func(
                            runtime=payment_rt
                        ),
                    )
                )
                if second_copy.get("found") is not True:
                    raise RuntimeError(
                        f"synthetic_second_copy_failed:{backend}:{second_copy}"
                    )
                status = json.loads(
                    timed(
                        "get_payment_status",
                        lambda: payment_tools.get_payment_status.func(
                            payment_id=offer["payment"]["payment_id"],
                            runtime=payment_rt,
                        ),
                    )
                )
                if status.get("found") is not True:
                    raise RuntimeError("synthetic_payment_status_failed")
            measured = {
                name: {
                    "p50_ms": round(statistics.median(values), 2),
                    "p95_ms": round(percentile(values, 0.95), 2),
                }
                for name, values in samples.items()
            }
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(
                    pool.map(
                        lambda index: mark_session(
                            SessionStore(), f"{prefix}-{label}-concurrent-{index}"
                        ),
                        range(iterations),
                    )
                )
            duration = time.perf_counter() - started
            return {
                "operations": measured,
                "concurrency": {
                    "workers": workers,
                    "operations": iterations,
                    "duration_ms": round(duration * 1000, 2),
                    "operations_per_second": round(iterations / duration, 2),
                },
            }

        import psycopg

        try:
            variants = (
                ("sqlite_delete_full", "sqlite", "DELETE", "FULL"),
                ("sqlite_wal_full", "sqlite", "WAL", "FULL"),
                ("sqlite_wal_normal", "sqlite", "WAL", "NORMAL"),
                ("postgres", "postgres", "", ""),
            )
            results = {
                label: measure(label, backend, journal, synchronous)
                for label, backend, journal, synchronous in variants
            }
        finally:
            with psycopg.connect(os.environ["SESSION_DATABASE_URL"]) as db:
                db.execute(
                    "DELETE FROM runtime.sessions WHERE id LIKE %s", (f"{prefix}%",)
                )
        print(
            json.dumps(
                {"iterations": iterations, "concurrency": workers, "results": results},
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
