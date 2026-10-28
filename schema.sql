-- ตารางตาม docs/designs/07-dbdiagram/db.puml (happy path S1–S8)

-- PostGIS — ถามเชิงพื้นที่จากพิกัดของรายงาน · เครื่องที่รันต้องลง PostGIS ไว้ก่อน
CREATE EXTENSION postgis;

CREATE TABLE users (
    user_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id     text NOT NULL UNIQUE,
    -- แถวเกิดตอนกดยอมรับเท่านั้น ก่อนกดไม่เก็บแม้แต่ line_user_id (LC1)
    pdpa_accepted_at timestamptz NOT NULL,
    -- เวลาที่ผู้แจ้งบล็อกบอท (LINE unfollow) · null = ยังติดตามอยู่ · กลับมาติดตาม (follow) → null
    blocked_at       timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- พยากรณ์อากาศที่อ่านวันละครั้งตอนตี 1 และการทักผู้แจ้งไปก่อนที่ตามมา · หนึ่งวันหนึ่งแถว
-- แถวของวันนี้มีแล้ว = อ่านพยากรณ์แล้ว · หลาย process หรือแอปเปิดใหม่ก็ไม่อ่านซ้ำและไม่ทักซ้ำ
CREATE TABLE broadcasts (
    broadcast_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- วันตามเวลาไทยที่พยากรณ์พูดถึง
    forecast_date date NOT NULL UNIQUE,
    -- เหตุที่ทัก ส่งให้ตัวคุยใช้แต่งข้อความ เช่น ฝนอาจตกแถวบ้าน · null = วันนี้ไม่มีเหตุให้ทัก
    reason        text,
    -- ข้อความทักที่ตัวคุยแต่งครั้งเดียวของวันนั้น {"texts": [...], "buttons": [...]} ทุกคนได้ข้อความนี้ · null = ยังไม่ได้แต่ง
    greeting      jsonb,
    -- skipped = ไม่มีเหตุให้ทัก · scheduled = รอทัก หรือทักยังไม่ครบทุกคน · sent = ทักครบแล้ว
    -- expired = เลยเวลาที่ทักได้ของวันนั้นแล้ว เช่น แอปดับไปทั้งวัน
    status        text NOT NULL CHECK (status IN ('skipped', 'scheduled', 'sent', 'expired')),
    sent_at       timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    session_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    status          text NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'closed', 'analysed', 'analyse_failed')),
    -- ใบที่บอททักไปก่อน · null = ผู้แจ้งทักมาเอง
    broadcast_id    uuid REFERENCES broadcasts (broadcast_id),
    started_at      timestamptz NOT NULL DEFAULT now(),
    last_message_at timestamptz NOT NULL DEFAULT now(),
    closed_at       timestamptz
);

-- หนึ่งผู้แจ้งมีใบเปิดได้ใบเดียว — ข้อความสองอันมาพร้อมกันต้องได้ใบเดียว
CREATE UNIQUE INDEX sessions_one_open_per_user ON sessions (user_id) WHERE status = 'open';

-- การทักแต่ละวันได้ใบเดียวต่อผู้แจ้ง · แอปดับกลางการทักแล้วทักต่อ คนที่ได้ไปแล้วไม่ถูกทักซ้ำ
-- แม้เขาตอบจบจนใบถูกปิดไปแล้ว หรือมีหลาย process ทักพร้อมกัน
CREATE UNIQUE INDEX sessions_one_per_broadcast ON sessions (user_id, broadcast_id) WHERE broadcast_id IS NOT NULL;

CREATE TABLE messages (
    message_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    line_event_id   text UNIQUE,
    line_message_id text,
    role            text NOT NULL CHECK (role IN ('user', 'assistant')),
    type            text NOT NULL CHECK (type IN ('text', 'image', 'location', 'sticker')),
    content         text,
    lat             double precision,
    lng             double precision,
    -- skipped = ส่งรัวจนใบถูกพัก · ไม่ส่งให้ AI และตัววิเคราะห์ข้าม แต่แดชบอร์ดยังเห็น (#239)
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'answered', 'skipped')),
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
    is_active          boolean NOT NULL DEFAULT false,
    -- เพดาน token (input + output) ที่ผู้แจ้งหนึ่งคนใช้ได้ต่อวันตามเวลาไทย · นับเฉพาะตัวคุย (#239)
    user_daily_token_limit bigint NOT NULL DEFAULT 500000,
    -- เพดานข้อความที่บอทยังไม่ได้ตอบใน buffer ของใบหนึ่ง · ข้อความที่เกินพักใบ 24 ชั่วโมง (#239)
    session_buffer_limit integer NOT NULL DEFAULT 30,
    -- เพดาน token (input + output) ที่ผู้แจ้งทุกคนรวมกันใช้ได้ต่อวันตามเวลาไทย · นับเฉพาะตัวคุย (#239)
    system_daily_token_limit bigint NOT NULL DEFAULT 5000000,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- ตัวคุยและตัววิเคราะห์ใช้แถวที่ is_active = true ได้แถวเดียว (#242)
-- แอดมินสลับแถว: ปลดแถวเดิมก่อน แล้วตั้งแถวใหม่ ในสองคำสั่งของ transaction เดียว
--   คำสั่งเดียว SET is_active = (ai_config_id = ...) ชน index นี้ได้ ขึ้นกับลำดับแถว
CREATE UNIQUE INDEX ai_configs_one_active ON ai_configs (is_active) WHERE is_active;

CREATE TABLE reports (
    report_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      uuid NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    ai_config_id    uuid NOT NULL REFERENCES ai_configs (ai_config_id),
    tags            text[],
    lat             double precision,
    lng             double precision,
    "desc"          text NOT NULL,
    -- ความรุนแรงที่ตัววิเคราะห์ประเมินจากเรื่องที่ผู้แจ้งเล่า · ทีมใช้เลือกว่าเรื่องไหนควรทำก่อน
    severity        text NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    -- ใครได้รับผลกระทบ · ค่าที่ใส่ได้อยู่ที่ AffectedGroup ใน app/models/report.py
    affected_groups text[] NOT NULL DEFAULT '{}',
    -- ช่วงเวลาที่คนใช้ที่ตรงนั้นและเจอปัญหาจริง · ค่าที่ใส่ได้อยู่ที่ TimePeriod ใน app/models/report.py
    time_periods    text[] NOT NULL DEFAULT '{}',
    -- ตำแหน่งตามคำของผู้แจ้ง เช่น หน้าวัด ปากซอย 5 · ใช้ได้แม้ไม่ได้ปักหมุด
    place           text,
    started_at      timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
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
    status        text NOT NULL CHECK (status IN ('ok', 'warning', 'error', 'stream_cut')),
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
