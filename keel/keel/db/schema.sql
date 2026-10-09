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

CREATE TABLE IF NOT EXISTS claim (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid NOT NULL REFERENCES project(id),
    participant_id uuid NOT NULL REFERENCES participant(id),
    scope_tags     text[] NOT NULL,
    expires_at     timestamptz
);

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
    delivered_at         timestamptz,
    acknowledged_at      timestamptz
);

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
