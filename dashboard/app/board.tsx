"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Incident, Notice, Stats } from "@/lib/incidents";

type Filter = "open" | "acknowledged" | "resolved";

const FILTERS: Filter[] = ["open", "acknowledged", "resolved"];

export function Board() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "offline">("loading");
  const [filter, setFilter] = useState<Filter | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [now, setNow] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    const [incidentResponse, statsResponse, noticeResponse] = await Promise.all([
      fetch("/api/incidents", { cache: "no-store" }),
      fetch("/api/stats", { cache: "no-store" }),
      fetch("/api/notifications", { cache: "no-store" }),
    ]);
    const incidentPayload = await incidentResponse.json();
    const statsPayload = await statsResponse.json();
    const noticePayload = await noticeResponse.json();
    if (!incidentResponse.ok) {
      setPhase("offline");
      setError(incidentPayload.error || "The incident store is not ready.");
      setIncidents([]);
      setNotices([]);
      setStats(null);
      return;
    }
    setPhase("ready");
    setError(null);
    setIncidents(incidentPayload);
    setNotices(noticeResponse.ok && Array.isArray(noticePayload) ? noticePayload : []);
    setStats(statsResponse.ok ? statsPayload : null);
  }, []);

  useEffect(() => {
    refresh();
    const poll = window.setInterval(refresh, 2000);
    return () => window.clearInterval(poll);
  }, [refresh]);

  useEffect(() => {
    setNow(Date.now());
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  const counts = useMemo(() => {
    return {
      open: incidents.filter((item) => item.status === "open").length,
      acknowledged: incidents.filter((item) => item.status === "acknowledged").length,
      resolved: incidents.filter((item) => item.status === "resolved").length,
    };
  }, [incidents]);

  const visible = useMemo(() => {
    if (filter === "all") return incidents;
    return incidents.filter((item) => item.status === filter);
  }, [filter, incidents]);

  useEffect(() => {
    if (!visible.length) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !visible.some((item) => item.id === selectedId)) {
      setSelectedId(visible[0].id);
    }
  }, [visible, selectedId]);

  const selected = visible.find((item) => item.id === selectedId) ?? null;

  async function changeStatus(id: string, status: "acknowledged" | "resolved") {
    setPending(`${id}:${status}`);
    setActionError(null);
    const response = await fetch(`/api/incidents/${id}/status`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json();
    setPending(null);
    if (!response.ok) {
      setActionError(payload.error || "Could not update the incident.");
      return;
    }
    await refresh();
  }

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <p className="eyebrow">AI Incident Detector</p>
          <h1>Incidents</h1>
          <p className="live">
            <span className={phase === "ready" ? "dot on" : "dot"} />
            {phase === "loading"
              ? "Reading the incident store"
              : phase === "offline"
                ? "Waiting for the engine"
                : `${stats?.store || "store"} · ${stats?.incidents ?? incidents.length} rows · ${stats?.log_samples ?? 0} log lines copied in`}
          </p>
        </div>
        <ul className="counts">
          {FILTERS.map((status) => (
            <li key={status}>
              <button
                type="button"
                aria-pressed={filter === status}
                onClick={() => setFilter((current) => (current === status ? "all" : status))}
              >
                <strong>{counts[status]}</strong>
                <span>{status}</span>
              </button>
            </li>
          ))}
        </ul>
      </header>

      {phase === "loading" ? (
        <section className="empty">
          <p className="eyebrow">Connecting</p>
          <h2>Reading the incident store.</h2>
        </section>
      ) : error ? (
        <Offline message={error} />
      ) : incidents.length === 0 ? (
        <Waiting />
      ) : (
        <div className="workspace">
          <Alerts
            notices={notices}
            now={now}
            onOpen={(id) => {
              setFilter("all");
              setSelectedId(id);
            }}
          />
          <div className="list" role="listbox" aria-label="Incidents">
            {visible.length === 0 ? (
              <p className="hint" style={{ padding: "12px" }}>
                No {filter} incidents. Click the count again to show every row.
              </p>
            ) : (
              visible.map((incident) => (
                <button
                  key={incident.id}
                  type="button"
                  role="option"
                  aria-selected={incident.id === selectedId}
                  aria-current={incident.id === selectedId ? "true" : undefined}
                  className="row"
                  onClick={() => setSelectedId(incident.id)}
                >
                  <span className={`tick ${incident.severity}`} />
                  <span className="row-copy">
                    <span className="service">{incident.service}</span>
                    <span className="row-title">{incident.title}</span>
                  </span>
                  <span className="when">{now ? ago(incident.created_at, now) : ""}</span>
                </button>
              ))
            )}
          </div>
          <article className="detail">
            {selected ? (
              <Detail
                incident={selected}
                now={now}
                pending={pending}
                actionError={actionError}
                onStatus={changeStatus}
              />
            ) : (
              <p className="hint">Select an incident.</p>
            )}
          </article>
        </div>
      )}
    </div>
  );
}

function Detail({
  incident,
  now,
  pending,
  actionError,
  onStatus,
}: {
  incident: Incident;
  now: number | null;
  pending: string | null;
  actionError: string | null;
  onStatus: (id: string, status: "acknowledged" | "resolved") => void;
}) {
  return (
    <>
      <p className="detail-kicker">
        {incident.service} · {incident.source} · {incident.signal}
      </p>
      <h2>{incident.title}</h2>
      <div className="pills">
        <span className={`pill ${incident.severity}`}>{incident.severity}</span>
        <span className={`pill ${incident.status}`}>{incident.status}</span>
        <span className="pill">summary {incident.summary_source}</span>
      </div>
      <p className="summary">{cleanSummary(incident.summary)}</p>
      <ul className="facts">
        <li>
          <strong>{formatValue(incident.signal, Number(incident.value))}</strong>
          measured value
        </li>
        <li>
          <strong>{now ? ago(incident.started_at, now) : "—"}</strong>
          window opened
        </li>
        <li>
          <strong>{incident.evidence.length}</strong>
          samples stored
        </li>
      </ul>
      <ul className="evidence">
        {incident.evidence.length === 0 ? (
          <li>
            <span className="kind">none</span>
            <span>No sample lines were stored with this row.</span>
          </li>
        ) : (
          incident.evidence.map((sample, index) => (
            <li key={`${sample.observed_at}-${index}`}>
              <span className="kind">{sample.kind.replace("_", " ")}</span>
              <span>{sampleText(sample.payload)}</span>
            </li>
          ))
        )}
      </ul>
      <div className="actions">
        <button
          type="button"
          disabled={incident.status !== "open" || pending !== null}
          onClick={() => onStatus(incident.id, "acknowledged")}
        >
          {pending === `${incident.id}:acknowledged` ? "Saving…" : "Acknowledge"}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={incident.status === "resolved" || pending !== null}
          onClick={() => onStatus(incident.id, "resolved")}
        >
          {pending === `${incident.id}:resolved` ? "Saving…" : "Resolve"}
        </button>
      </div>
      {actionError ? <p className="error-line">{actionError}</p> : null}
      <p className="hint">
        Resolving closes this row. The next breach of the same service and signal opens a new one.
      </p>
    </>
  );
}

function Alerts({
  notices,
  now,
  onOpen,
}: {
  notices: Notice[];
  now: number | null;
  onOpen: (id: string) => void;
}) {
  return (
    <section className="alerts" aria-label="Alerts">
      <p className="eyebrow">Alerts</p>
      {notices.length === 0 ? (
        <p className="hint">Notify workers deliver an alert when an incident opens or changes status.</p>
      ) : (
        <div className="alert-row">
          {notices.map((notice) => (
            <button key={notice.id} type="button" className="alert" onClick={() => onOpen(notice.incident_id)}>
              <span className={`kind ${notice.severity}`}>{noticeLabel(notice)}</span>
              <span className="alert-title">{notice.title}</span>
              <span className="when">{now ? ago(notice.created_at, now) : ""}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function noticeLabel(notice: Notice): string {
  if (notice.kind === "opened") return "Opened";
  return notice.status;
}

function Waiting() {
  return (
    <section className="empty">
      <p className="eyebrow">Connected</p>
      <h2>Watching for the first breach.</h2>
      <p>
        The producer holds a quiet minute, then spikes <code>checkout</code>, <code>billing-agent</code>, and{" "}
        <code>web-node</code> for about 16 seconds. The three rules need that spike inside a 30 second window.
      </p>
      <About />
    </section>
  );
}

function Offline({ message }: { message: string }) {
  return (
    <section className="offline">
      <p className="eyebrow">Not connected</p>
      <h2>Start the pipeline, then this board fills itself.</h2>
      <p>{message}</p>
      <ol className="steps">
        <li>
          <span>
            From the repo root, run <code>docker compose up --build</code>. That starts Kafka, the detector, the
            incident API, and the notify workers.
          </span>
        </li>
        <li>
          <span>
            In another terminal, run <code>cd dashboard && npm install && npm run dev</code>.
          </span>
        </li>
        <li>
          <span>Leave both running. The first incidents land about 15 seconds after Kafka is ready.</span>
        </li>
      </ol>
      <About />
    </section>
  );
}

function About() {
  return (
    <details className="about">
      <summary>Where the rows come from</summary>
      <p>
        Every log stays on the Kafka topic <code>telemetry</code> for 24 hours. This board reads incident rows and
        the alerts the notify workers deliver. One open row per service and signal, plus at most five error lines.
        Deployed, the same tables live in Supabase.
      </p>
    </details>
  );
}

function cleanSummary(text: string): string {
  return text
    .replace(/^\s*[-•]\s*/, "")
    .replace(/\s+[-•]\s+(?=[A-Z])/g, " ")
    .trim();
}

function sampleText(payload: EvidencePayload): string {
  if (payload.body) return String(payload.body);
  if (payload.signal !== undefined) return `${payload.signal} = ${payload.value ?? ""}`;
  return JSON.stringify(payload);
}

type EvidencePayload = {
  body?: string;
  signal?: string;
  value?: number | string;
};

function formatValue(signal: string, value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (signal.includes("ratio") || signal.includes("utilization")) {
    return `${Math.round(value * 1000) / 10}%`;
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function ago(iso: string, now: number): string {
  const delta = Math.max(0, now - new Date(iso).getTime());
  const seconds = Math.round(delta / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return new Date(iso).toLocaleDateString();
}
