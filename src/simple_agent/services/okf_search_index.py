"""Bounded process-local lexical indexes for immutable published OKF bundles."""

from collections import OrderedDict
from threading import Lock
from sys import getsizeof
from pathlib import Path

from simple_agent.tool_timing import count_event, timed_phase


def prepare_document(path, content, tokenize, query_tokens=None):
    tokens = tokenize(f"{path}\n{content}")
    if query_tokens is not None and not (query_tokens & tokens):
        return tokens, ()
    return (
        tokens,
        tuple(
            (number, line.strip(), tokenize(line))
            for number, line in enumerate(content.splitlines(), 1)
            if not line.startswith("OKF_CANONICAL_PATH:")
        ),
    )


def retained_size(value, seen=None):
    """Estimate Python object bytes, counting shared objects only once."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = getsizeof(value)
    if isinstance(value, dict):
        size += sum(
            retained_size(k, seen) + retained_size(v, seen) for k, v in value.items()
        )
    elif isinstance(value, (tuple, list, set, frozenset)):
        size += sum(retained_size(item, seen) for item in value)
    return size


class SearchIndex:
    def __init__(self, service, byte_limit):
        self.documents = {}
        self.postings = {}
        source_chars = 0
        for path in service.list_files().splitlines():
            if (
                not path.endswith(".md")
                or Path(path).name.lower() in service.RESERVED_MARKDOWN
            ):
                continue
            try:
                content = service.read_file(path)
            except FileNotFoundError:
                continue
            source_chars += len(content)
            # Bound construction as well as retained entries; oversized bundles
            # continue through the unchanged filesystem search.
            if source_chars > 2_000_000 or len(self.documents) >= 2000:
                raise OverflowError("search_index_source_limit")
            document = prepare_document(path, content, service._search_tokens)
            self.documents[path] = document
            for token in document[0]:
                self.postings.setdefault(token, set()).add(path)
            if len(self.documents) % 64 == 0:
                if retained_size((self.documents, self.postings)) > byte_limit:
                    raise OverflowError("search_index_memory_limit")
        self.size = retained_size((self.documents, self.postings))
        if self.size > byte_limit:
            raise OverflowError("search_index_memory_limit")

    def candidates(self, tokens, scope):
        paths = set().union(*(self.postings.get(token, ()) for token in tokens))
        for path in paths:
            if not scope or path.startswith(scope + "/"):
                yield path, self.documents[path]


class SearchIndexCache:
    def __init__(self, max_bytes=32 * 1024 * 1024, max_bundles=2):
        self.max_bytes = max_bytes
        self.max_bundles = max_bundles
        self.entries = OrderedDict()
        self.size = 0
        self.lock = Lock()

    def get(self, service):
        # The absolute root includes the storage domain and immutable bundle ID.
        key = (str(service.root), service.max_chars_per_file)
        with timed_phase("okf_cache_wait"):
            self.lock.acquire()
        try:
            if key in self.entries:
                self.entries.move_to_end(key)
                index = self.entries[key]
                count_event(
                    "okf_cache_hit" if index is not None else "okf_cache_bypass"
                )
                return index
            count_event("okf_cache_miss")
            # ponytail: serialize cold builds to bound peak memory; warm searches
            # run outside this lock. Use per-bundle builds if measured contention warrants it.
            with timed_phase("okf_index_build"):
                try:
                    index = SearchIndex(service, self.max_bytes)
                except OverflowError:
                    index = None
                    count_event("okf_cache_bypass")
            added = index.size if index is not None else 0
            while self.entries and (
                len(self.entries) >= self.max_bundles
                or self.size + added > self.max_bytes
            ):
                _, previous = self.entries.popitem(last=False)
                self.size -= previous.size if previous is not None else 0
                count_event("okf_cache_eviction")
            self.entries[key] = index
            self.size += added
            return index
        finally:
            self.lock.release()


SEARCH_INDEX_CACHE = SearchIndexCache()
