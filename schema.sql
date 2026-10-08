-- ตารางตาม docs/designs/07-dbdiagram/db.puml (happy path S1–S8)

CREATE TABLE users (
    user_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id     text NOT NULL UNIQUE,
    -- แถวเกิดตอนกดยอมรับเท่านั้น ก่อนกดไม่เก็บแม้แต่ line_user_id (LC1)
    pdpa_accepted_at timestamptz NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    session_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    status          text NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'closed', 'analysed', 'analyse_failed')),
    started_at      timestamptz NOT NULL DEFAULT now(),
    last_message_at timestamptz NOT NULL DEFAULT now(),
    closed_at       timestamptz
);

CREATE TABLE messages (
    message_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    line_event_id   text UNIQUE,
    line_message_id text,
    role            text NOT NULL CHECK (role IN ('reporter', 'bot')),
    type            text NOT NULL CHECK (type IN ('text', 'image', 'location', 'sticker')),
    content         text,
    lat             double precision,
    lng             double precision,
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'answered')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE prompts (
    prompt_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt     text NOT NULL,
    "desc"     text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE models (
    model_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider   text NOT NULL,
    name       text NOT NULL,
    "desc"     text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_configs (
    ai_config_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_model_id      uuid NOT NULL REFERENCES models (model_id),
    chat_prompt_id     uuid NOT NULL REFERENCES prompts (prompt_id),
    analyzer_model_id  uuid NOT NULL REFERENCES models (model_id),
    analyzer_prompt_id uuid NOT NULL REFERENCES prompts (prompt_id),
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    report_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    ai_config_id uuid NOT NULL REFERENCES ai_configs (ai_config_id),
    tags         text[],
    lat          double precision,
    lng          double precision,
    "desc"       text NOT NULL,
    started_at   timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attachments (
    attachment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id    uuid NOT NULL REFERENCES messages (message_id) ON DELETE CASCADE,
    -- null จนตัววิเคราะห์เลือกรูปนี้เข้ารายงาน
    report_id     uuid REFERENCES reports (report_id) ON DELETE SET NULL,
    type          text NOT NULL CHECK (type IN ('image')),
    file_path     text NOT NULL,
    "desc"        text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_calls (
    ai_call_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    ai_config_id  uuid NOT NULL REFERENCES ai_configs (ai_config_id),
    kind          text NOT NULL CHECK (kind IN ('communicator', 'analyser')),
    request       jsonb NOT NULL,
    response      text,
    input_tokens  int,
    output_tokens int,
    status        text NOT NULL CHECK (status IN ('ok', 'error', 'stream_cut')),
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
