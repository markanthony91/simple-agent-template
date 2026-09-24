"""Seed only a temporary local sandbox explicitly selected by the operator."""

import os
from pathlib import Path
from simple_agent.services.okf_store import PersistentOKFStore

root = Path(os.environ["OKF_DATA_ROOT"]).resolve()
if not str(root).startswith("/tmp/runtime-e2e-"):
    raise SystemExit("Refusing to seed outside the temporary E2E sandbox")
policy = """---
type: Policy
status: published
institution: FastPay
product: cartao_de_credito
negotiation:
  max_installments: 10
  max_discount_percentage: "20"
  offer_discount_percentage: "10"
  payment_types: [cash, installment]
---
# Synthetic policy
Test only. Up to ten installments, twenty percent ceiling.
"""
PersistentOKFStore().import_bundle(
    "synthetic",
    "0.2",
    {
        "index.md": "# Test\n[Policy](INSTITUTIONS/fastpay/policy.md)",
        "INSTITUTIONS/fastpay/policy.md": policy,
    },
)
