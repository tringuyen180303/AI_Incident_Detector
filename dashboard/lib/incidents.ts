export type Evidence = {
  kind: string;
  observed_at: string;
  payload: {
    body?: string;
    signal?: string;
    value?: number | string;
    [key: string]: unknown;
  };
};

export type Incident = {
  id: string;
  title: string;
  summary: string;
  summary_source: string;
  severity: string;
  status: string;
  source: string;
  service: string;
  signal: string;
  value: number;
  started_at: string;
  resolved_at: string | null;
  created_at: string;
  evidence: Evidence[];
};

export type Stats = {
  store: string;
  incidents: number;
  log_samples: number;
};

export type Notice = {
  id: string;
  incident_id: string;
  kind: string;
  channel: string;
  service: string;
  signal: string;
  title: string;
  summary: string;
  severity: string;
  status: string;
  created_at: string;
};

const STATUSES = new Set(["open", "acknowledged", "resolved"]);

function supabaseEnv(): { url: string; key: string } | null {
  const url = process.env.SUPABASE_URL?.replace(/\/$/, "");
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (url && key) return { url, key };
  return null;
}

function apiBase(): string {
  return (process.env.INCIDENT_API_URL || "http://localhost:8080").replace(/\/$/, "");
}

export function sourceLabel(): string {
  return supabaseEnv() ? "supabase" : "local engine";
}

export async function listIncidents(): Promise<Incident[]> {
  if (supabaseEnv()) return listFromSupabase();
  const payload = await apiJson("/api/incidents");
  if (!Array.isArray(payload)) {
    throw new Error("Incident API returned an unexpected payload");
  }
  return payload as Incident[];
}

export async function listNotifications(): Promise<Notice[]> {
  if (supabaseEnv()) {
    const rows = (await supabaseFetch(
      "/notifications?select=id,incident_id,kind,channel,service,signal,title,summary,severity,status,created_at&channel=eq.board&order=created_at.desc&limit=20",
    )) as Notice[] | null;
    return rows || [];
  }
  const payload = await apiJson("/api/notifications");
  if (!Array.isArray(payload)) {
    throw new Error("Incident API returned an unexpected payload");
  }
  return payload as Notice[];
}

export async function readStats(): Promise<Stats> {
  if (supabaseEnv()) return statsFromSupabase();
  const payload = await apiJson("/api/stats");
  return payload as Stats;
}

export async function setStatus(id: string, status: string): Promise<{ id: string; status: string }> {
  if (!STATUSES.has(status)) {
    throw new Error("status must be open, acknowledged, or resolved");
  }
  if (supabaseEnv()) return setStatusOnSupabase(id, status);
  const payload = await apiJson(`/api/incidents/${encodeURIComponent(id)}/status`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return payload as { id: string; status: string };
}

async function apiJson(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${apiBase()}${path}`, { ...init, cache: "no-store" });
  } catch {
    throw new Error(
      "The incident API is not running. Start it with docker compose up --build, then refresh.",
    );
  }
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const message =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `Incident API returned ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

async function supabaseFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const env = supabaseEnv();
  if (!env) throw new Error("Supabase is not configured");
  const headers = new Headers(init.headers);
  headers.set("apikey", env.key);
  headers.set("authorization", `Bearer ${env.key}`);
  headers.set("content-type", "application/json");
  const response = await fetch(`${env.url}/rest/v1${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Supabase ${response.status}: ${text || response.statusText}`);
  }
  return text ? JSON.parse(text) : null;
}

async function listFromSupabase(): Promise<Incident[]> {
  const rows = (await supabaseFetch(
    "/incidents?select=id,title,summary,summary_source,severity,status,source,service,signal,value,started_at,resolved_at,created_at,incident_evidence(kind,observed_at,payload)&order=created_at.desc&limit=50",
  )) as Array<Incident & { incident_evidence?: Evidence[] }>;
  return (rows || []).map((row) => {
    const evidence = [...(row.incident_evidence || [])].sort((a, b) =>
      String(a.observed_at).localeCompare(String(b.observed_at)),
    );
    const { incident_evidence: _nested, ...incident } = row;
    return { ...incident, evidence };
  });
}

async function statsFromSupabase(): Promise<Stats> {
  const [incidents, logSamples] = await Promise.all([
    supabaseCount("/incidents?select=id"),
    supabaseCount("/incident_evidence?select=id&kind=eq.log"),
  ]);
  return { store: "supabase", incidents, log_samples: logSamples };
}

async function supabaseCount(path: string): Promise<number> {
  const env = supabaseEnv();
  if (!env) return 0;
  const response = await fetch(`${env.url}/rest/v1${path}`, {
    headers: {
      apikey: env.key,
      authorization: `Bearer ${env.key}`,
      Range: "0-0",
      Prefer: "count=exact",
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Supabase ${response.status}: ${await response.text()}`);
  }
  const range = response.headers.get("content-range") || "";
  const total = range.split("/")[1];
  if (!total || total === "*") return 0;
  return Number(total);
}

async function setStatusOnSupabase(id: string, status: string): Promise<{ id: string; status: string }> {
  const now = new Date().toISOString();
  const rows = (await supabaseFetch(`/incidents?id=eq.${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify({
      status,
      updated_at: now,
      resolved_at: status === "resolved" ? now : null,
    }),
  })) as Array<{ id: string }>;
  if (!rows?.length) {
    throw new Error("incident not found");
  }
  await supabaseFetch("/incident_events", {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({
      incident_id: id,
      kind: "status_changed",
      actor: "dashboard",
      detail: { status },
    }),
  });
  return { id, status };
}
