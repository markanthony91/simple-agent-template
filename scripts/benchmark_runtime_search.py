"""Reproducible synthetic benchmark; temporary documents, no production access."""

import json
import math
import random
import statistics
import tempfile
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from simple_agent.services.okf_service import OKFService
from simple_agent.services.okf_search_index import SEARCH_INDEX_CACHE
from simple_agent.tool_timing import capture_timing


def summary(values):
    return {
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(sorted(values)[math.ceil(len(values) * 0.95) - 1], 3),
    }


def main():
    rng = random.Random(20260926)
    with tempfile.TemporaryDirectory(prefix="synthetic-okf-bench-") as directory:
        root = Path(directory)
        for branch in ("COMPANIES", "GLOBAL"):
            (root / branch).mkdir()
        for number in range(519):
            branch = "COMPANIES" if number < 100 else "GLOBAL"
            (root / branch / f"concept-{number:04}.md").write_text(
                "---\ntype: Policy\nstatus: published\n---\n"
                + f"# Conceito sintético {number}\n"
                + "\n".join(
                    f"Regra {line}: informação sintética sobre "
                    + (
                        "parcelamento boleto cartão"
                        if number % 2
                        else "desconto PIX à vista"
                    )
                    + f". Referência {number}-{line}."
                    for line in range(12)
                ),
                encoding="utf-8",
            )
        file_service = OKFService(root)
        memory_service = OKFService(root, immutable_bundle=True)
        start = perf_counter()
        with capture_timing() as cold:
            memory_service.search("parcelamento", "COMPANIES")
        build_ms = (perf_counter() - start) * 1000
        cases = []
        for query, scope in [
            ("parcelamento", "COMPANIES"),
            ("desconto pix", "COMPANIES"),
            ("informação", "GLOBAL"),
            ("missingtoken", ""),
        ]:
            expected = file_service.search(query, scope)
            samples = {"filesystem": [], "cached": []}
            with patch.object(
                memory_service, "read_file", side_effect=AssertionError("warm reread")
            ):
                for _ in range(20):
                    engines = [("filesystem", file_service), ("cached", memory_service)]
                    rng.shuffle(engines)
                    for name, service in engines:
                        started = perf_counter()
                        actual = service.search(query, scope)
                        samples[name].append((perf_counter() - started) * 1000)
                        assert actual == expected
            cases.append(
                {
                    "query": query,
                    "scope": scope,
                    **{name: summary(values) for name, values in samples.items()},
                }
            )
        print(
            json.dumps(
                {
                    "corpus": "synthetic-519-concepts",
                    "cold_ms": round(build_ms, 3),
                    "retained_index_bytes": SEARCH_INDEX_CACHE.size,
                    "equivalent_comparisons": 160,
                    "warm_document_reads": 0,
                    "cold_counters": cold["counters"],
                    "cases": cases,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
