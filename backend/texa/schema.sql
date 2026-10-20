-- Application tables (idempotent; applied at API start).
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.catalog_versions (
  version      serial PRIMARY KEY,
  fingerprint  text NOT NULL,
  catalog      jsonb NOT NULL,
  published_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.conversations (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title      text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- One row per question. state holds the pipeline outputs (candidate, spec, sql, preview, facts, insight...).
CREATE TABLE IF NOT EXISTS app.turns (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id  uuid NOT NULL REFERENCES app.conversations(id) ON DELETE CASCADE,
  question         text NOT NULL,
  status           text NOT NULL DEFAULT 'running',
  model            text,
  contract_version int,
  state            jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS turns_conversation_idx ON app.turns (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS app.run_steps (
  id         bigserial PRIMARY KEY,
  turn_id    uuid NOT NULL REFERENCES app.turns(id) ON DELETE CASCADE,
  step       text NOT NULL,
  status     text NOT NULL,
  ms         int,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.feedback (
  turn_id    uuid PRIMARY KEY REFERENCES app.turns(id) ON DELETE CASCADE,
  rating     text NOT NULL CHECK (rating IN ('up', 'down')),
  comment    text CHECK (length(comment) <= 1000),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.model_connection (
  id                int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  provider          text NOT NULL,
  encrypted_api_key text NOT NULL,
  allowed_models    jsonb NOT NULL DEFAULT '[]'::jsonb,
  default_model     text,
  max_output_tokens int NOT NULL DEFAULT 8192,
  daily_token_limit int NOT NULL DEFAULT 0,
  answer_language   text NOT NULL DEFAULT 'auto',
  updated_at        timestamptz NOT NULL DEFAULT now()
);
-- Optional endpoint override: an organisation gateway / proxy speaking the provider's API.
ALTER TABLE app.model_connection ADD COLUMN IF NOT EXISTS base_url text;

-- Token ledger; never stores prompt or response text.
CREATE TABLE IF NOT EXISTS app.llm_usage (
  id            bigserial PRIMARY KEY,
  turn_id       uuid,
  call_name     text NOT NULL,
  model         text NOT NULL,
  input_tokens  int,
  cached_tokens int,
  output_tokens int,
  ms            int,
  created_at    timestamptz NOT NULL DEFAULT now()
);
