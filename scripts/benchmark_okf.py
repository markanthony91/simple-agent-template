"""Read-only OKF search benchmark; candidate exists only in this process's RAM.

PYTHONPATH=src python scripts/benchmark_okf.py --root /path/to/bundle --rounds 30
No sessions, assistants, receipts, or document files are written.
"""

import argparse
import gc
import hashlib
import json
import math
import random
import statistics
import time
from pathlib import Path

from simple_agent.services.okf_service import OKFService


class MemoryIndex:
    """Precompute existing lexical tokens, preserving the runtime's ranking."""

    def __init__(self, service):
        self.service = service
        self.documents = {}
        self.postings = {}
        for path in service.list_files().splitlines():
            if Path(path).name.lower() in service.RESERVED_MARKDOWN:
                continue
            content = service.read_file(path)
            self.documents[path] = (
                content,
                service._search_tokens(f"{path}\n{content}"),
                [
                    (number, line.strip(), service._search_tokens(line))
                    for number, line in enumerate(content.splitlines(), 1)
                    if not line.startswith("OKF_CANONICAL_PATH:")
                ],
            )
            for token in self.documents[path][1]:
                self.postings.setdefault(token, set()).add(path)

    def search(self, query, scope=""):
        tokens = self.service._search_tokens(query)
        if not tokens:
            raise ValueError("Search query cannot be empty")
        cleaned = ""
        if scope:
            try:
                cleaned = self.service.canonical_directory(scope)
            except FileNotFoundError:
                cleaned = self.service._collapse_duplicate_root(scope.strip("/"))
        ranked = []
        candidates = set().union(*(self.postings.get(token, set()) for token in tokens))
        for path in candidates:
            _, document_tokens, lines = self.documents[path]
            if cleaned and not path.startswith(cleaned + "/"):
                continue
            score = len(tokens & document_tokens)
            if not score:
                continue
            number, line, line_tokens = max(lines, key=lambda row: len(tokens & row[2]))
            ranked.append(
                (score, len(tokens & line_tokens), path, f"{path}:{number}: {line}")
            )
        ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
        matches = [row[3] for row in ranked[: self.service.max_results]]
        return f"OKF_CANONICAL_SCOPE: {cleaned or '<root>'}\n\n" + (
            "\n".join(matches) if matches else "No OKF matches found."
        )


CASES = [
    (
        "cash_pix",
        "will-bank cartao_de_credito negociação cash pix",
        "COMPANIES",
        "politica-negociacao.md",
    ),
    (
        "boleto",
        "will-bank cartao_de_credito negociação boleto",
        "COMPANIES",
        "parcelamento.md",
    ),
    (
        "three_installments",
        "will-bank cartao_de_credito 3x",
        "COMPANIES",
        "parcelamento.md",
    ),
    (
        "five_installments",
        "will-bank cartao_de_credito parcelamento 5 parcelas",
        "COMPANIES",
        "parcelamento.md",
    ),
    (
        "cash_discount",
        "will bank desconto à vista",
        "COMPANIES",
        "politica-negociacao.md",
    ),
    ("dispute", "não reconhece dívida", "GLOBAL", None),
    ("third_party", "terceiro familiar", "GLOBAL", None),
    ("no_match", "zzbenchmissingunambiguous", "COMPANIES", None),
]


def summary(samples):
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


def timed(call):
    start = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - start) * 1000


def digest(root):
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.md")):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def benchmark(root, rounds):
    service = OKFService(root)
    file_reads = [0]
    original_read = service.read_file

    def counted_read(*args, **kwargs):
        file_reads[0] += 1
        return original_read(*args, **kwargs)

    service.read_file = counted_read
    before = digest(root)
    index, build_ms = timed(lambda: MemoryIndex(service))
    output = {
        "bundle_id": root.name,
        "markdown_files": len(service.list_files().splitlines()),
        "indexed_concepts": len(index.documents),
        "indexed_tokens": len(index.postings),
        "index_build_ms": round(build_ms, 3),
        "rounds_per_case": rounds,
        "cache_condition": "warm OS file cache; randomized sequential alternating engines",
        "cases": [],
    }
    total = {"filesystem": [], "memory": []}
    rng = random.Random(20260925)
    for label, query, scope, expected in CASES:
        reference = service.search(query, scope)
        assert index.search(query, scope) == reference, label
        samples = {"filesystem": [], "memory": []}
        read_counts = {"filesystem": [], "memory": []}
        for _ in range(rounds):
            engines = [("filesystem", service.search), ("memory", index.search)]
            rng.shuffle(engines)
            for name, search in engines:
                file_reads[0] = 0
                result, elapsed = timed(lambda: search(query, scope))
                assert result == reference, (label, name)
                read_counts[name].append(file_reads[0])
                if name == "memory":
                    assert file_reads[0] == 0, "Index unexpectedly reread documents"
                samples[name].append(elapsed)
                total[name].append(elapsed)
        paths = [
            line.split(":", 1)[0]
            for line in reference.splitlines()[2:]
            if ".md:" in line
        ]
        case = {
            "case": label,
            "filesystem": summary(samples["filesystem"]),
            "memory": summary(samples["memory"]),
            "identical_results": True,
            "file_reads_per_query": {
                name: sorted(set(counts)) for name, counts in read_counts.items()
            },
            "top_result": paths[0] if paths else None,
            "expected_policy_rank": next(
                (
                    i
                    for i, p in enumerate(paths, 1)
                    if expected and p.endswith("/" + expected)
                ),
                None,
            ),
        }
        output["cases"].append(case)
        print(json.dumps({"progress": case}), flush=True)
    output["aggregate"] = {name: summary(values) for name, values in total.items()}
    reads = []
    cached_reads = []
    target = next(
        p
        for p in index.documents
        if p.endswith("/will-bank/CARTAO_DE_CREDITO/policies/parcelamento.md")
    )
    for _ in range(rounds):
        text, elapsed = timed(lambda: service.read_file(target))
        cached, cached_elapsed = timed(lambda: index.documents[target][0])
        assert text == cached
        reads.append(elapsed)
        cached_reads.append(cached_elapsed)
    output["policy_read"] = {
        "filesystem": summary(reads),
        "memory": summary(cached_reads),
    }
    gc.collect()
    output["bundle_content_unchanged"] = before == digest(root)
    assert output["bundle_content_unchanged"]
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=30)
    args = parser.parse_args()
    assert args.rounds > 0
    print("RESULT " + json.dumps(benchmark(args.root, args.rounds)))
