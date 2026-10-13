CREATE TABLE IF NOT EXISTS schema_version(version integer PRIMARY KEY);
INSERT INTO schema_version VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS accounts(
 id uuid PRIMARY KEY, tenant text NOT NULL, branch text NOT NULL, username text UNIQUE NOT NULL,
 salt bytea NOT NULL, verifier bytea NOT NULL, role text NOT NULL CHECK(role IN ('owner','cashier','reader','radius')),
 enabled boolean NOT NULL DEFAULT true, failures integer NOT NULL DEFAULT 0, locked_until timestamptz);
CREATE TABLE IF NOT EXISTS sessions(
 digest bytea PRIMARY KEY, account uuid NOT NULL REFERENCES accounts(id), expires timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 seq bigserial PRIMARY KEY, tenant text NOT NULL, branch text NOT NULL, event_id text NOT NULL, device text NOT NULL,
 kind text NOT NULL, digest text NOT NULL, body jsonb NOT NULL, actor uuid NOT NULL REFERENCES accounts(id),
 created timestamptz NOT NULL DEFAULT now(), state text NOT NULL DEFAULT 'QUEUED' CHECK(state IN ('QUEUED','APPLIED','QUARANTINED')),
 reason text, UNIQUE(tenant,branch,event_id));
CREATE INDEX IF NOT EXISTS events_queue ON events(seq) WHERE state='QUEUED';
CREATE TABLE IF NOT EXISTS conflicts(
 seq bigserial PRIMARY KEY, tenant text NOT NULL, branch text NOT NULL,event_id text NOT NULL,
 digest text NOT NULL, actor uuid NOT NULL REFERENCES accounts(id),created timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant,branch,event_id,digest));
CREATE TABLE IF NOT EXISTS ledger(
 tenant text NOT NULL,branch text NOT NULL,id text NOT NULL,subscriber text NOT NULL,currency text NOT NULL,
 amount bigint NOT NULL CHECK(amount<>0 AND abs(amount)<=999999999999),reversal_of text,note text NOT NULL,
 PRIMARY KEY(tenant,branch,id),UNIQUE(tenant,branch,reversal_of),
 FOREIGN KEY(tenant,branch,reversal_of) REFERENCES ledger(tenant,branch,id));
CREATE TABLE IF NOT EXISTS radius_sessions(
 tenant text NOT NULL,branch text NOT NULL,nas text NOT NULL,session text NOT NULL,username text NOT NULL,
 seconds bigint NOT NULL,input_octets bigint NOT NULL,output_octets bigint NOT NULL,stopped boolean NOT NULL,
 PRIMARY KEY(tenant,branch,nas,session));
CREATE OR REPLACE FUNCTION forbid_ledger_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_LEDGER'; END; $$;
DROP TRIGGER IF EXISTS ledger_immutable ON ledger;
CREATE TRIGGER ledger_immutable BEFORE UPDATE OR DELETE ON ledger FOR EACH ROW EXECUTE FUNCTION forbid_ledger_change();
CREATE TABLE IF NOT EXISTS nas_clients(
 digest bytea PRIMARY KEY, tenant text NOT NULL, branch text NOT NULL, nas text NOT NULL, enabled boolean NOT NULL DEFAULT true,actor uuid NOT NULL REFERENCES accounts(id));
CREATE TABLE IF NOT EXISTS radius_users(
 tenant text NOT NULL,branch text NOT NULL,username text NOT NULL,salt bytea NOT NULL,verifier bytea NOT NULL,
 expires timestamptz NOT NULL,enabled boolean NOT NULL DEFAULT true,
 failures integer NOT NULL DEFAULT 0,locked_until timestamptz,
 PRIMARY KEY(tenant,branch,username));
-- Business synchronization keeps immutable record versions, not mutable financial snapshots.
CREATE TABLE IF NOT EXISTS business_sync_heads(
 tenant text NOT NULL,branch text NOT NULL,revision bigint NOT NULL,digest text NOT NULL,PRIMARY KEY(tenant,branch));
CREATE TABLE IF NOT EXISTS business_sync_records(
 tenant text NOT NULL,branch text NOT NULL,kind text NOT NULL,id text NOT NULL,revision bigint NOT NULL,
 body jsonb NOT NULL,actor uuid NOT NULL REFERENCES accounts(id),device text NOT NULL,created timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant,branch,kind,id,revision));
CREATE INDEX IF NOT EXISTS business_sync_latest ON business_sync_records(tenant,branch,kind,id,revision DESC);
DROP TRIGGER IF EXISTS business_sync_immutable ON business_sync_records;
CREATE TRIGGER business_sync_immutable BEFORE UPDATE OR DELETE ON business_sync_records FOR EACH ROW EXECUTE FUNCTION forbid_ledger_change();
