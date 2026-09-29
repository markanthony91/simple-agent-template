CREATE SCHEMA IF NOT EXISTS runtime;
CREATE SCHEMA IF NOT EXISTS okf;
CREATE SCHEMA IF NOT EXISTS langgraph;

CREATE TABLE IF NOT EXISTS runtime.sessions (
  id varchar(200) PRIMARY KEY,
  tenant_id text,
  portfolio_id text,
  customer_id text,
  debt_id text,
  state jsonb NOT NULL,
  version bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sessions_tenant_portfolio_idx
  ON runtime.sessions (tenant_id, portfolio_id)
  WHERE tenant_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sessions_customer_idx
  ON runtime.sessions (customer_id)
  WHERE customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sessions_debt_idx
  ON runtime.sessions (debt_id)
  WHERE debt_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sessions_updated_at_idx
  ON runtime.sessions (updated_at DESC);

CREATE TABLE IF NOT EXISTS okf.snapshots (
  id varchar(120) PRIMARY KEY,
  status text NOT NULL CHECK (status IN ('draft', 'published', 'archived')),
  content_hash text NOT NULL,
  file_count integer NOT NULL DEFAULT 0 CHECK (file_count >= 0),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS snapshots_status_published_idx
  ON okf.snapshots (status, published_at DESC);

CREATE TABLE IF NOT EXISTS okf.documents (
  snapshot_id varchar(120) NOT NULL REFERENCES okf.snapshots(id) ON DELETE CASCADE,
  path text NOT NULL,
  content_hash text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (snapshot_id, path)
);

CREATE INDEX IF NOT EXISTS documents_path_idx ON okf.documents (path);
CREATE INDEX IF NOT EXISTS documents_content_hash_idx ON okf.documents (content_hash);

CREATE TABLE IF NOT EXISTS okf.receipts (
  session_id varchar(200) NOT NULL REFERENCES runtime.sessions(id) ON DELETE CASCADE,
  snapshot_id varchar(120) NOT NULL,
  path text NOT NULL,
  content_hash text NOT NULL,
  read_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, path)
);

CREATE INDEX IF NOT EXISTS receipts_snapshot_path_idx
  ON okf.receipts (snapshot_id, path);
CREATE INDEX IF NOT EXISTS receipts_read_at_idx ON okf.receipts (read_at DESC);
