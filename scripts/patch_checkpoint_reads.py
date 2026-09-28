"""Avoid redundant checkpoint reloads in langgraph-runtime-inmem 0.34.0."""

import hashlib
from importlib.metadata import distribution
from pathlib import Path

ORIGINAL = "616ca90a6c0292e1b7bdb80a877e929eeae08a0e6f5f28de2f470e39f87e8643"
PATCHED = "2d22ad2c7d442e055a102b0035172f0e2609bba7b45fd2513ff2e3f9522588d2"


def apply_patch(target: Path) -> None:
    source = target.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest == PATCHED:
        return
    if digest != ORIGINAL:
        raise RuntimeError("Unsupported checkpoint source; review dependency upgrade")
    text = source.decode()
    text = (
        text.replace(
            "        __persistence_hook__: Callable[[PersistentDict], None] | None = None,",
            "        __persistence_hook__: Callable[[PersistentDict], None] | None = None,\n"
            "        __load_persistence__: bool = True,",
        )
        .replace(
            "factory=factory if not DISABLE_FILE_PERSISTENCE else defaultdict,",
            "factory=(\n                factory\n"
            "                if __load_persistence__ and not DISABLE_FILE_PERSISTENCE\n"
            "                else defaultdict\n            ),",
        )
        .replace(
            "            serde=Serializer(__unpack_ext_hook__=ext_hook),",
            "            serde=Serializer(__unpack_ext_hook__=ext_hook),\n"
            "            # Read views share the singleton; only its owner restores and flushes.\n"
            "            __load_persistence__=False,",
        )
    )
    result = text.encode()
    if hashlib.sha256(result).hexdigest() != PATCHED:
        raise RuntimeError("Checkpoint patch verification failed")
    target.write_bytes(result)


if __name__ == "__main__":
    package = distribution("langgraph-runtime-inmem")
    if package.version != "0.34.0":
        raise RuntimeError("Checkpoint patch requires langgraph-runtime-inmem 0.34.0")
    apply_patch(Path(package.locate_file("langgraph_runtime_inmem/checkpoint.py")))
    print("Checkpoint read reuse verified (langgraph-runtime-inmem 0.34.0)")
