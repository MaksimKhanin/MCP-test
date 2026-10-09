-- Метаданные датасетов (условный каталог DWH).
CREATE TABLE IF NOT EXISTS datasets (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    owner           TEXT NOT NULL,
    description     TEXT,
    freshness_sla_h INT  NOT NULL,          -- сколько часов данные считаются свежими
    last_loaded_at  TIMESTAMPTZ,            -- когда последний раз грузились
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- Сюда агент пишет решения (очередь задач для оркестратора).
CREATE TABLE IF NOT EXISTS agent_tasks (
    id          SERIAL PRIMARY KEY,
    dataset     TEXT NOT NULL REFERENCES datasets(name),
    action      TEXT NOT NULL,              -- reload / notify_owner
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO datasets (name, owner, description, freshness_sla_h, last_loaded_at, is_active) VALUES
    ('sales_daily',    'team-sales',   'Продажи по дням',            24, now() - interval '2 hours',  TRUE),
    ('customers',      'team-crm',     'Справочник клиентов',        24, now() - interval '50 hours', TRUE),
    ('web_events',     'team-product', 'Сырые события с сайта',       1, now() - interval '3 hours',  TRUE),
    ('finance_ledger', 'team-finance', 'Главная книга',              168, NULL,                       TRUE),
    ('legacy_orders',  'team-sales',   'Старая таблица заказов',      24, now() - interval '400 days', FALSE)
ON CONFLICT (name) DO NOTHING;
