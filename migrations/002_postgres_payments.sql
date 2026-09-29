CREATE TABLE IF NOT EXISTS runtime.payment_agreements (
  agreement_id varchar(200) PRIMARY KEY,
  origin_session_id varchar(200) NOT NULL
    REFERENCES runtime.sessions(id) ON DELETE CASCADE,
  data jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS payment_agreements_origin_idx
  ON runtime.payment_agreements (origin_session_id);

CREATE TABLE IF NOT EXISTS runtime.payment_instructions (
  payment_id varchar(200) PRIMARY KEY,
  agreement_id varchar(200) NOT NULL
    REFERENCES runtime.payment_agreements(agreement_id) ON DELETE CASCADE,
  method text NOT NULL CHECK (method IN ('pix', 'boleto')),
  installment_number integer NOT NULL CHECK (installment_number BETWEEN 1 AND 360),
  data jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (agreement_id, method, installment_number)
);

CREATE INDEX IF NOT EXISTS sessions_context_idx
  ON runtime.sessions (tenant_id, portfolio_id, customer_id, debt_id)
  WHERE tenant_id IS NOT NULL;
