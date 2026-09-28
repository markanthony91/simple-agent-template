"""Resolve navigation context from actual directories in the session's OKF snapshot.

This identifies a branch, not a commercial policy or permission to make an offer.
"""

from pathlib import Path

from simple_agent.services.okf_service import OKFService
from simple_agent.services.okf_store import PersistentOKFStore


def customer_knowledge(state: dict) -> dict:
    fixture = state["fixture"]
    company = fixture.get("company") or fixture.get("debt", {}).get("company")
    context = {
        "company": company,
        "company_source": "customer" if company else None,
        "okf_directory": None,
        "okf_context_status": "unavailable",
    }
    snapshot = state.get("snapshot_id")
    if not snapshot:
        return context
    try:
        service = OKFService(PersistentOKFStore().bundle_root(snapshot))

        def key(value):
            return service._normalize(str(value or "")).replace(" ", "")

        def children(directory, name=None):
            directories, _ = service._get_child_directories_and_concepts(directory)
            for path in directories:
                if name is None or key(Path(path).name) == key(name):
                    # Preserve on-disk spelling and enforce the bundle boundary.
                    yield service.canonical_directory(path)

        institution = fixture.get("institution")
        product = fixture.get("product")
        matches = []
        if key(institution) and key(product):
            for companies in children("", "COMPANIES"):
                for operator in children(companies, company):
                    for institutions in children(operator, "INSTITUTIONS"):
                        for creditor in children(institutions, institution):
                            for directory in children(creditor, product):
                                matches.append((Path(operator).name, directory))
                                if len(matches) > 1:
                                    context["okf_context_status"] = "ambiguous"
                                    return context
        context["okf_context_status"] = "not_found"
        if matches:
            matched_company, directory = matches[0]
            context.update(
                company=company or matched_company,
                company_source="customer" if company else "okf_snapshot",
                okf_directory=directory,
                okf_context_status="resolved",
            )
    except (OSError, ValueError):
        # Unavailable knowledge must not turn successful identity verification
        # into an error. Normal OKF navigation remains available to the agent.
        context["okf_context_status"] = "unavailable"
    return context
