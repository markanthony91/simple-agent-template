-- Synthetic contract check. The transaction always rolls back its rows.
BEGIN;
INSERT INTO runtime.tenants VALUES ('test-tenant', 'Synthetic', now());
INSERT INTO runtime.portfolios VALUES
  ('test-portfolio', 'test-tenant', 'Synthetic', 'Synthetic', now());
INSERT INTO runtime.customers VALUES
  ('test-customer', 'test-tenant', 'Synthetic', '000', '000', '2000-01-01', now());
INSERT INTO runtime.debts VALUES
  ('test-debt', 'test-tenant', 'test-portfolio', 'test-customer', 'synthetic',
   '100.00', 1, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, now());
INSERT INTO runtime.sessions(id, state) VALUES
  ('test-session', '{}'::jsonb), ('test-session-2', '{}'::jsonb);
INSERT INTO runtime.session_contexts VALUES
  ('test-session', 'test-tenant', 'test-portfolio', 'test-customer', 'test-debt', now());
INSERT INTO runtime.payment_agreements(agreement_id, origin_session_id, data)
VALUES ('test-agreement', 'test-session', '{}'::jsonb);
INSERT INTO runtime.payment_instructions(payment_id, agreement_id, method, installment_number, data)
VALUES ('test-payment', 'test-agreement', 'boleto', 1, '{}'::jsonb);

DO $$
BEGIN
  ASSERT (SELECT count(*) FROM runtime.session_contexts WHERE session_id='test-session') = 1;
  ASSERT (SELECT count(*) FROM runtime.payment_instructions WHERE agreement_id='test-agreement') = 1;
  BEGIN
    INSERT INTO runtime.session_contexts VALUES
      ('test-session-2', 'wrong-tenant', 'test-portfolio', 'test-customer', 'test-debt', now());
    RAISE EXCEPTION 'cross-tenant context allowed';
  EXCEPTION WHEN foreign_key_violation THEN NULL;
  END;
END $$;
ROLLBACK;

DO $$
BEGIN
  ASSERT (SELECT count(*) FROM runtime.sessions) = 0;
  ASSERT (SELECT count(*) FROM runtime.tenants) = 0;
  ASSERT (SELECT count(*) FROM runtime.payment_agreements) = 0;
END $$;
SELECT 'PASS isolated PostgreSQL SQLite-catalog parity';
