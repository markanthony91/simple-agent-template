"""Conservative path validation for NEW RAW drafts, not a published migration."""

from pathlib import PurePosixPath

ROOTS = {"GLOBAL", "PRODUCTS", "INSTITUTIONS"}


def ingestion_path(path: str, action: str, domain: str, existing: set[str]) -> str:
    """Keep exact existing identities; canonicalize new roots or reject collisions."""
    if action in {"append", "noop"} and path in existing:
        return path
    parts = list(PurePosixPath(path).parts)
    if parts[0].upper() not in ROOTS:
        parts.insert(0, domain)
    parts[0] = parts[0].upper()
    if any(part.upper() in ROOTS for part in parts[1:]):
        raise ValueError("nested_domain_root_requires_review")
    canonical = "/".join(parts)
    # Never silently retarget an append or shadow an old concept with a new case.
    if any(p.casefold() == canonical.casefold() and p != canonical for p in existing):
        raise ValueError("concept_case_conflict_requires_review")
    directories = {str(parent) for p in existing for parent in PurePosixPath(p).parents}
    for parent in PurePosixPath(canonical).parents:
        name = str(parent)
        if name not in directories and any(
            p.casefold() == name.casefold() for p in directories
        ):
            raise ValueError("directory_case_conflict_requires_review")
    return canonical
