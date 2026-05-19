CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE,
  display_name TEXT,
  plan TEXT DEFAULT 'self_hosted_free',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  encrypted_key TEXT NOT NULL,
  is_default BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_registry (
  id TEXT PRIMARY KEY,
  family TEXT,
  display_name TEXT,
  is_free BOOLEAN DEFAULT true,
  context_window INT,
  capabilities JSONB,
  telemetry JSONB,
  health_score NUMERIC,
  model_class TEXT,
  sycophancy_index NUMERIC DEFAULT 0,
  last_seen TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quorum_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  mode TEXT NOT NULL,
  task_type TEXT,
  primary_language TEXT,
  original_prompt TEXT NOT NULL,
  selected_council JSONB,
  consensus_score NUMERIC,
  final_answer TEXT,
  disagreements JSONB DEFAULT '[]'::jsonb,
  escalation_recommended BOOLEAN DEFAULT false,
  marginal_cost_usd NUMERIC DEFAULT 0.00,
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS quorum_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES quorum_sessions(id) ON DELETE CASCADE,
  phase TEXT NOT NULL,
  model_id TEXT REFERENCES model_registry(id),
  role TEXT,
  label TEXT,
  status TEXT,
  latency_ms INT,
  output_text TEXT,
  parsed_output JSONB,
  confidence_self_reported NUMERIC,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quorum_claims (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES quorum_sessions(id) ON DELETE CASCADE,
  claim TEXT NOT NULL,
  supporters JSONB DEFAULT '[]'::jsonb,
  is_disagreement BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_model_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  provider_model_id TEXT NOT NULL,
  preference TEXT NOT NULL,
  reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saved_presets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  mode TEXT NOT NULL,
  council JSONB,
  hub_model TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  model_id TEXT,
  eval_name TEXT,
  task_type TEXT,
  primary_language TEXT,
  score NUMERIC,
  sample_size INT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_name TEXT,
  suite TEXT,
  baseline TEXT,
  metrics JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL,
  user_id UUID,
  session_id UUID,
  event_type TEXT,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS audit_log_2026_05 PARTITION OF audit_log
FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE INDEX IF NOT EXISTS idx_quorum_sessions_user_created ON quorum_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quorum_runs_session_phase ON quorum_runs(session_id, phase);
CREATE INDEX IF NOT EXISTS idx_model_registry_health ON model_registry(health_score DESC) WHERE is_free = true;

CREATE OR REPLACE VIEW model_eval_scores AS SELECT * FROM eval_scores;
CREATE OR REPLACE VIEW council_presets AS SELECT * FROM saved_presets;
