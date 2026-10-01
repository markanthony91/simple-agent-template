-- Catalog tables missing from the PostgreSQL session/payment canary.
-- No application is connected to this dedicated database yet.
CREATE TABLE runtime.tenants (
  id text PRIMARY KEY,
  name text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE runtime.portfolios (
  id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES runtime.tenants(id),
  name text NOT NULL,
  creditor_name text NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (tenant_id, id)
);

CREATE TABLE runtime.customers (
  id text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES runtime.tenants(id),
  full_name text NOT NULL,
  cpf text NOT NULL,
  phone text NOT NULL,
  birth_date text NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (tenant_id, id)
);

CREATE TABLE runtime.debts (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  portfolio_id text NOT NULL,
  customer_id text NOT NULL,
  product text NOT NULL,
  current_amount text NOT NULL,
  days_overdue integer NOT NULL,
  data jsonb NOT NULL,
  eligibility jsonb NOT NULL,
  identity_policy jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, portfolio_id)
    REFERENCES runtime.portfolios(tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id)
    REFERENCES runtime.customers(tenant_id, id)
);

CREATE TABLE runtime.session_contexts (
  session_id varchar(200) PRIMARY KEY REFERENCES runtime.sessions(id),
  tenant_id text NOT NULL,
  portfolio_id text NOT NULL,
  customer_id text NOT NULL,
  debt_id text NOT NULL,
  created_at timestamptz NOT NULL,
  FOREIGN KEY (tenant_id, portfolio_id)
    REFERENCES runtime.portfolios(tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id)
    REFERENCES runtime.customers(tenant_id, id),
  FOREIGN KEY (tenant_id, debt_id)
    REFERENCES runtime.debts(tenant_id, id)
);

CREATE INDEX session_contexts_customer_debt_idx
  ON runtime.session_contexts (tenant_id, portfolio_id, customer_id, debt_id);
