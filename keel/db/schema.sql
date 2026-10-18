CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS project (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS person (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES project(id),
    display_name text NOT NULL,
    token_hash   text NOT NULL,
    UNIQUE (project_id, display_name),
    UNIQUE (token_hash)
);

CREATE TABLE IF NOT EXISTS participant (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES project(id),
    principal_type    text NOT NULL DEFAULT 'person_session',
    person_id         uuid REFERENCES person(id),
    agent_name        text,
    sponsor_person_id uuid REFERENCES person(id),
    role              text,
    harness           text NOT NULL,
    tier              text NOT NULL CHECK (tier IN ('deep','light')),
    session_id        text NOT NULL,
    allowed_scopes    text[] NOT NULL DEFAULT '{}',
    allowed_categories text[] NOT NULL DEFAULT '{}',
    status            text NOT NULL DEFAULT 'active',
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, person_id, session_id)
);

CREATE TABLE IF NOT EXISTS goal (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid NOT NULL REFERENCES project(id),
    statement      text NOT NULL,
    owner_person_id uuid REFERENCES person(id),
    scope_tags     text[] NOT NULL DEFAULT '{}',
    status         text NOT NULL DEFAULT 'active',
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES project(id),
    kind                text NOT NULL DEFAULT 'decision' CHECK (kind IN ('decision','lesson')),
    category            text,
    goal_id             uuid REFERENCES goal(id),
    statement           text NOT NULL,
    rationale           text,
    scope_tags          text[] NOT NULL,
    owner_person_id     uuid REFERENCES person(id),
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('proposed','active','superseded','rejected')),
    source_participant_id uuid REFERENCES participant(id),
    supersedes_id       uuid REFERENCES decision(id),
    evidence_refs       text[] NOT NULL DEFAULT '{}',
    expires_at          timestamptz,
    embedding           vector(1536),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS decision_scope_idx ON decision USING gin (scope_tags);
CREATE INDEX IF NOT EXISTS decision_status_idx ON decision (project_id, status);
ALTER TABLE decision ADD COLUMN IF NOT EXISTS ts tsvector
    GENERATED ALWAYS AS (to_tsvector('english',
        coalesce(statement,'') || ' ' || coalesce(rationale,''))) STORED;
CREATE INDEX IF NOT EXISTS decision_ts_idx ON decision USING gin (ts);

CREATE TABLE IF NOT EXISTS dependency (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id    uuid NOT NULL REFERENCES decision(id),
    dependent_type text NOT NULL CHECK (dependent_type IN ('participant','artifact')),
    dependent_ref  text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dependency_decision_idx ON dependency (decision_id);
CREATE INDEX IF NOT EXISTS dependency_dependent_ref_idx ON dependency (dependent_type, dependent_ref);

CREATE TABLE IF NOT EXISTS claim (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid NOT NULL REFERENCES project(id),
    participant_id uuid NOT NULL REFERENCES participant(id),
    scope_tags     text[] NOT NULL,
    expires_at     timestamptz
);
CREATE INDEX IF NOT EXISTS claim_participant_idx ON claim (participant_id);

CREATE TABLE IF NOT EXISTS conflict (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES project(id),
    decision_a_id uuid NOT NULL REFERENCES decision(id),
    subject_type text NOT NULL CHECK (subject_type IN ('decision','planned_action')),
    subject_ref  text NOT NULL,
    relation     text NOT NULL CHECK (relation IN ('contradicts','duplicates','supersedes','unclear')),
    severity     text NOT NULL CHECK (severity IN ('high','medium','low')),
    explanation  text NOT NULL,
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    resolution   text,
    resolved_by  uuid REFERENCES person(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id           uuid NOT NULL REFERENCES project(id),
    target_participant_id uuid REFERENCES participant(id),
    target_person_id     uuid REFERENCES person(id),
    kind                 text NOT NULL CHECK (kind IN ('conflict','change')),
    ref_id               uuid NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    delivered_at         timestamptz,
    acknowledged_at      timestamptz
);
ALTER TABLE alert ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS alert_target_ack_idx ON alert (target_participant_id, acknowledged_at);
-- Dedupe pre-existing duplicate unacked change-alerts BEFORE the unique index, so
-- ensure_schema can't fail on a deployment that accumulated them before the dedupe fix.
DELETE FROM alert a USING alert b
 WHERE a.kind = 'change' AND a.acknowledged_at IS NULL
   AND b.kind = 'change' AND b.acknowledged_at IS NULL
   AND a.target_participant_id = b.target_participant_id
   AND a.ref_id = b.ref_id
   AND a.ctid > b.ctid;
CREATE UNIQUE INDEX IF NOT EXISTS alert_unacked_change_idx ON alert (target_participant_id, ref_id)
    WHERE kind = 'change' AND acknowledged_at IS NULL;

CREATE TABLE IF NOT EXISTS event (
    id          bigserial PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES project(id),
    actor       text NOT NULL,
    action      text NOT NULL,
    payload_json jsonb NOT NULL,
    prev_hash   text,
    hash        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS event_project_idx ON event (project_id, id);

CREATE TABLE IF NOT EXISTS handoff (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES project(id),
    from_participant_id uuid REFERENCES participant(id),
    to_person_id      uuid REFERENCES person(id),
    to_participant_id uuid REFERENCES participant(id),
    scope_tags        text[] NOT NULL DEFAULT '{}',
    decision_ids      uuid[] NOT NULL DEFAULT '{}',
    conflict_ids      uuid[] NOT NULL DEFAULT '{}',
    note              text,
    status            text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','declined')),
    created_at        timestamptz NOT NULL DEFAULT now(),
    accepted_at       timestamptz
);
CREATE INDEX IF NOT EXISTS handoff_to_person_status_idx ON handoff (project_id, to_person_id, status);

CREATE TABLE IF NOT EXISTS outcome (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id  uuid NOT NULL REFERENCES decision(id),
    result       text NOT NULL CHECK (result IN ('held','reversed','caused_rework')),
    evidence_ref text,
    source       text NOT NULL CHECK (source IN ('manual','inferred')),
    confirmed_by uuid REFERENCES person(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_feedback (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id  uuid NOT NULL REFERENCES alert(id),
    verdict   text NOT NULL CHECK (verdict IN ('useful','noise')),
    note      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS drift_signal (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES project(id),
    participant_id uuid REFERENCES participant(id),
    source        text NOT NULL CHECK (source IN ('edit','turn','commit','pr','gateway','slack')),
    scope_tags    text[] NOT NULL DEFAULT '{}',
    summary       text,
    file_paths    text[] NOT NULL DEFAULT '{}',
    ref           text,
    confidence    double precision,
    result        text CHECK (result IN ('none','possible','conflict')),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_request (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id             uuid NOT NULL REFERENCES project(id),
    requester_participant_id uuid REFERENCES participant(id),
    owner_person_id        uuid REFERENCES person(id),
    question               text NOT NULL,
    options                text[] NOT NULL DEFAULT '{}',
    scope_tags             text[] NOT NULL DEFAULT '{}',
    status                 text NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','expired')),
    answer_decision_id     uuid REFERENCES decision(id),
    created_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS judgment_cache (
    key        text PRIMARY KEY,
    model      text NOT NULL,
    judgment   jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- I2/I3: Google identity on person + agent tokens + device-code grants (additive)
ALTER TABLE person ADD COLUMN IF NOT EXISTS email text;
ALTER TABLE person ADD COLUMN IF NOT EXISTS firebase_uid text;
CREATE UNIQUE INDEX IF NOT EXISTS person_email_idx ON person (email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS person_firebase_uid_idx ON person (firebase_uid) WHERE firebase_uid IS NOT NULL;

CREATE TABLE IF NOT EXISTS token (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES project(id),
    person_id   uuid NOT NULL REFERENCES person(id),
    token_hash  text NOT NULL UNIQUE,
    kind        text NOT NULL CHECK (kind IN ('person','agent')),
    label       text,
    scope       text NOT NULL DEFAULT 'full' CHECK (scope IN ('full','read_only')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz
);
CREATE INDEX IF NOT EXISTS token_person_idx ON token (person_id);

CREATE TABLE IF NOT EXISTS device_grant (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_code_hash text NOT NULL UNIQUE,
    user_code        text NOT NULL UNIQUE,
    harness          text NOT NULL,
    label            text,
    status           text NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','approved','denied','expired','claimed')),
    scope            text,
    person_id        uuid REFERENCES person(id),
    token_id         uuid REFERENCES token(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    approved_at      timestamptz,
    expires_at       timestamptz NOT NULL,
    last_polled_at   timestamptz
);
