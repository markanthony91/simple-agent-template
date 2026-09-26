"""Local synthetic offer benchmark. No network, real customer data or production writes."""

import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix="offer-benchmark-") as root:
        for name in (
            "OKF_DATA_ROOT",
            "SESSION_ROOT",
            "SIMULATOR_ROOT",
            "TOOL_REGISTRY_ROOT",
        ):
            os.environ[name] = str(Path(root) / name)
        os.environ["LLM_BASE_URL"] = "http://127.0.0.1:1/v1"
        os.environ["LLM_API_KEY"] = "synthetic"
        os.environ["LANGSMITH_TRACING"] = "false"
        from simple_agent.services.okf_store import PersistentOKFStore
        from simple_agent.tools.payment_tools import generate_payment_offer
        from tests.unit_tests.test_pilot_journeys import seed, read_policy, PATH
        from tests.unit_tests.test_collection_identity_gates import (
            runtime,
            verify,
            call,
        )

        seed(PersistentOKFStore(), approve=True)
        for kind, method, count, phrase in [
            ("cash", "pix", 1, "Quero à vista no PIX"),
            ("installment", "boleto", 3, "Quero em 3 parcelas no boleto"),
        ]:
            durations, reads = [], []
            for n in range(20):
                rt = runtime(f"benchmark-{kind}-{n}", phrase)
                assert verify(rt)["verified"]
                read_policy(rt)
                original = Path.read_text
                accessed = []

                def counted(path, *args, **kwargs):
                    if str(path).endswith(PATH):
                        accessed.append(1)
                    return original(path, *args, **kwargs)

                with patch.object(Path, "read_text", counted):
                    started = time.perf_counter()
                    result = call(
                        generate_payment_offer,
                        rt,
                        payment_type=kind,
                        method=method,
                        installments=count,
                        policy_path=PATH,
                    )
                    durations.append((time.perf_counter() - started) * 1000)
                assert result["created"]
                reads.append(len(accessed))
            print(
                json.dumps(
                    {
                        "method": method,
                        "runs": len(durations),
                        "median_ms": round(statistics.median(durations), 3),
                        "policy_reads": sorted(set(reads)),
                    }
                )
            )


if __name__ == "__main__":
    main()
