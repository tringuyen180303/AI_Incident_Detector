create table incidents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  summary text not null,
  summary_source text not null default 'template',
  severity text not null check (severity in ('low', 'medium', 'high')),
  status text not null default 'open' check (status in ('open', 'acknowledged', 'resolved')),
  source text not null check (source in ('application', 'agent', 'infrastructure')),
  service text not null,
  signal text not null,
  value double precision not null,
  started_at timestamptz not null,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- One open incident per service and signal. A second anomaly updates this row.
create unique index incidents_one_open
  on incidents (service, signal)
  where status = 'open';

create table incident_evidence (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents (id) on delete cascade,
  kind text not null check (kind in ('metric', 'log', 'span', 'tool_call')),
  observed_at timestamptz not null,
  payload jsonb not null
);

create table incident_events (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid not null references incidents (id) on delete cascade,
  kind text not null check (kind in ('created', 'status_changed', 'note', 'evidence_appended')),
  actor text not null,
  detail jsonb,
  created_at timestamptz not null default now()
);
