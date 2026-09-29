"""Make the in-memory runtime queue poll interval configurable."""

import hashlib
from importlib.metadata import distribution
from pathlib import Path

ORIGINAL = "bf5ba26875a7a7bc8c54ecc600d51fda5c4aa3c357b827d5020a6da5d3cc0aa1"
PATCHED = "fe9ba0644cb16e875fd6439df7c1c82ba14b2fc18407983b049ac87ed2ee7b0e"


def apply_patch(target: Path) -> None:
    source = target.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest == PATCHED:
        return
    if digest != ORIGINAL:
        raise RuntimeError("Unsupported runtime queue source; review dependency upgrade")
    text = source.decode().replace("import json\n", "import json\nimport os\n", 1).replace(
        "            await asyncio.sleep(0.5)",
        '            await asyncio.sleep(float(os.getenv("LANGGRAPH_QUEUE_POLL_SECONDS", "0.5")))',
        1,
    )
    result = text.encode()
    if hashlib.sha256(result).hexdigest() != PATCHED:
        raise RuntimeError("Runtime queue patch verification failed")
    target.write_bytes(result)


if __name__ == "__main__":
    package = distribution("langgraph-runtime-inmem")
    if package.version != "0.34.0":
        raise RuntimeError("Queue patch requires langgraph-runtime-inmem 0.34.0")
    apply_patch(Path(package.locate_file("langgraph_runtime_inmem/ops.py")))
    print("Runtime queue poll verified (langgraph-runtime-inmem 0.34.0)")
