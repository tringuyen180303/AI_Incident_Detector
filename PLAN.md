# Learning plan: AI Incident Detector and Supabase Compute

This repo is a title and this diagram. The plan is a study path: learn the product, then learn the system you drew, then know which box belongs on which runtime.

Read it in order. Each phase ends with a check you can do without building the whole detector.

## What you are building

An incident detector for three kinds of producers:

- Applications (logs, metrics, traces)
- AI agents (tool calls, LLM calls, retries, evaluations)
- Infrastructure (CPU, memory, Kubernetes, the database)

Those signals are collected with OpenTelemetry, split into a raw store and a live processor, and turned into incidents. The incident engine asks Claude for an explanation and writes the incident to Supabase. Supabase Realtime pushes that state to a Vercel dashboard.

Supabase here is the system of record and the live update channel. It is not the telemetry bus, and it is not the place that stores every raw log.

## Two different things named "compute"

Search results mix these. They are not the same product.

| Name | What it is | When you care |
| --- | --- | --- |
| [Supabase Compute](https://supabase.com/compute) | A private-alpha runtime next to your Postgres database. Short-lived sandboxes and always-on HTTP services, in any language, with no wall-clock limit. | The incident engine, a long Claude job, or an agent sandbox. |
| [Compute and Disk](https://supabase.com/docs/guides/platform/compute-and-disk) | The size of the Postgres machine (Nano, Micro, Small, and up). | How much CPU and memory the database itself has. |

This plan uses **Supabase Compute** for the new runtime. Database size shows up only in Phase 2, as the machine that holds incident rows.

Compute is in private alpha behind a waitlist ([announcement](https://supabase.com/blog/supabase-select-2026-recap)). Edge Functions keep working. Deno functions can move onto Compute later because Compute runs the Deno runtime as well as Node and a Dockerfile. Until you have access, study the model here and practice the same shape on an Edge Function.

## Where each box lives

```text
Applications / AI agents / Infrastructure
        logs, metrics, traces, tool calls, CPU, ...
                          |
                          v
                 OpenTelemetry Collector          outside Supabase
                          |
                          v
                  Streaming pipeline              a bus, not Postgres
                     /            \
                    v              v
            Raw telemetry     Stream processor    processor may be a Compute service
                                  |
                                  v
                           Detect anomalies       rules first, models later
                                  |
                                  v
                           Incident engine        Compute always-on service
                              /            \
                             v              v
                          Claude         Supabase Postgres
                        explanation       incident state
                             \              /
                              v            v
                          Supabase Realtime
                                  |
                                  v
                                Vercel             the dashboard only
```

Compute is a good home for the incident engine: a long-running HTTP service in the same region as Postgres, so writing an incident is a local query, and a Claude call can run as long as the model takes.

Compute is a poor home for the OpenTelemetry Collector, the stream bus, and the dashboard. Those stay specialized.

## Phase 0 — Words you will use the whole way

One sitting. No code.

| Word | Meaning in this project |
| --- | --- |
| Signal | One observation: a log line, a metric point, a span, a tool call, a retry. |
| Telemetry | Signals exported in a common shape, here OpenTelemetry. |
| Trace | Spans that share a trace id, so you can see one request or one agent run. |
| Anomaly | A signal that broke a rule you wrote. Not yet an incident. |
| Incident | A durable record that something needs a human: title, severity, evidence, status. |
| Incident state | The row in Postgres that the dashboard reads. Open, acknowledged, resolved. |
| Raw telemetry | The original signals, kept so you can re-check a detection. Not the incident row. |

**Check.** Write one sentence for a fake incident: "The billing agent retried the same tool 40 times in two minutes, error rate on `charge_card` went from 0.2% to 18%, and Postgres CPU crossed 80%." Label which clause is an agent signal, which is an application metric, and which is infrastructure.

## Phase 1 — Walk one incident through the diagram

Goal: be able to point at every arrow and say what crosses it.

### The story

1. **Sources.** A deploy goes out. The app emits HTTP latency. The billing agent emits tool-call spans and retry counts. Kubernetes emits CPU. All three already speak, or can be wrapped to speak, OpenTelemetry.
2. **Collector.** One process receives OTLP (the OpenTelemetry protocol). It batches, adds `service.name`, and forwards. It does not decide that something is an incident.
3. **Streaming pipeline.** A durable stream (for a first version, a small queue is enough; Kafka-class systems come later). Two consumers read the same stream.
4. **Raw telemetry.** One consumer writes the original signals somewhere cheap to scan later. That store is for evidence, not for the live UI.
5. **Stream processor.** The other consumer keeps short windows: error rate over 2 minutes, retry count per agent, CPU per pod.
6. **Detect anomalies.** Compare the window to a threshold. Example: tool retries above 20 in 2 minutes, or HTTP 5xx above 5%. Emit an anomaly event. Do not call Claude here.
7. **Incident engine.** Receives the anomaly. Dedupes it against open incidents. Builds a short evidence packet. Asks Claude for a summary and a likely cause. Writes one incident row.
8. **Supabase.** Stores that row. Realtime publishes the insert and later updates.
9. **Vercel.** The dashboard is subscribed. A new card appears without a refresh.

### What Claude is allowed to see

Send a bounded packet: service name, time window, the metric that fired, a few example spans or log lines, and open incidents that look related. Do not send the raw stream.

### What "done" means for an incident

Status moves `open` → `acknowledged` → `resolved`. Claude writes the summary once at creation. A human changes status. A later phase can let Claude suggest the status; the first version should not.

**Check.** On paper, list the payload at each arrow for the billing-agent story: collector output, anomaly event, Claude request, incident row, realtime event. If a field appears in the incident row and you cannot say which arrow produced it, the diagram is still fuzzy.

## Phase 2 — Supabase as incident state

Goal: know the database, Realtime, and Auth pieces this project uses. This phase is Postgres, not Supabase Compute.

Read:

- [Database overview](https://supabase.com/docs/guides/database/overview)
- [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Realtime Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes)
- [Compute and Disk](https://supabase.com/docs/guides/platform/compute-and-disk) — only the size table, so you can tell it apart from the runtime in Phase 3

### Tables to be able to draw

`incidents`

- `id`, `title`, `summary`
- `severity` (`low`, `medium`, `high`)
- `status` (`open`, `acknowledged`, `resolved`)
- `source` (`application`, `agent`, `infrastructure`)
- `service`, `started_at`, `resolved_at`
- `claude_model`, `created_at`, `updated_at`

`incident_evidence`

- `incident_id`, `kind` (`metric`, `log`, `span`, `tool_call`)
- `observed_at`, `payload` (jsonb, small)

`incident_events`

- `incident_id`, `kind` (`created`, `status_changed`, `note`)
- `actor`, `created_at`, `detail`

Keep raw telemetry out of these tables. Evidence is a handful of samples that justify the incident.

### Realtime

The dashboard listens for inserts and updates on `incidents`. Postgres Changes require the table to be in the Realtime publication, and they respect Row Level Security for a signed-in user. A policy of "any anon key can read every incident" is a bug, not a shortcut.

### Database size

A learning project fits on the smallest paid size once you leave the free Nano instance. You scale this only when incident queries get slow. You do not scale it to absorb the telemetry stream.

**Check.** In the [SQL editor](https://supabase.com/dashboard) of a scratch project, create `incidents` with the columns above, enable Realtime for that table, insert one row, and watch it arrive in a tiny local page using `supabase.channel(...).on('postgres_changes', ...)`. Screenshot or note the payload. That page is the seed of the Vercel app.

## Phase 3 — Supabase Compute, the runtime

Goal: explain the product without looking it up, and know what you cannot know yet because it is alpha.

Primary source: [supabase.com/compute](https://supabase.com/compute). Secondary: the Compute section of the [Select 2026 recap](https://supabase.com/blog/supabase-select-2026-recap).

### The idea

Compute runs your code in the same region and network as the project's Postgres. Queries to that database are local. Each workload gets a full Linux environment and the same default environment variables Edge Functions already get.

Two shapes share that runtime:

| Shape | Lifetime | Use it for |
| --- | --- | --- |
| Ephemeral sandbox | Short-lived, isolated, for untrusted code | An agent or a tool that runs code you do not fully trust |
| Always-on HTTP service | Stays up, suspends when idle, resumes in under a second | The incident engine's API |

Idle sandboxes and services scale to zero. Jobs are not cut off by a short wall-clock limit, which is the usual reason a long Claude call or a backfill dies on a serverless function.

### Trust boundary

Access to Postgres and Storage goes through Supabase Auth and short-lived credentials. The workload can do what its key is allowed to do, which still means Row Level Security applies. A service that writes incidents should use a role that can insert incidents and nothing else.

Also on the product page, and worth remembering before you put an API key in a worker:

- Per-workload firewalls restrict which outbound hosts and ports that workload may call. The incident engine needs Anthropic's API and nothing like a wide-open egress.
- Secrets can be scoped per workload, and Supabase can inject them only on requests to approved services.
- Kernel patches are applied for you. The dashboard shows execution logs, traces, audit logs, and usage.

### How a deploy is supposed to work

Advertised surfaces:

- CLI: `supabase compute deploy`
- An MCP server, so an agent can provision sandboxes and services
- Management API
- GitHub Actions
- A Compute skill for coding agents

The public Management API is alpha and currently shows two resource names with the same spec shape: [compute instances](https://supabase.com/docs/reference/api/v2-get-a-compute-instance) and [workers](https://supabase.com/docs/reference/api/v2-deploy-a-worker). Treat the docs as the source of truth; the example JSON on those pages is placeholder schema (`lorem`, huge integers), not a real deploy response.

The flow the API describes:

1. Mint an upload slot. `POST /v2/projects/{ref}/compute/{name}/uploads` or `POST /v2/projects/{ref}/workers/{name}/uploads`.
2. `PUT` a `.tar.gz` of the build context to the returned URL before it expires. The bytes do not go through the management API.
3. Deploy. `POST /v2/projects/{ref}/workers/{name}/deploy` with that upload id. The response is `202`. The build finishes later.
4. Poll `GET /v2/projects/{ref}/workers/{name}` until `build_state` is `active` or `failed`.

A worker spec, from the API examples, has:

- `runtime` — the sample uses `node`. The product also lists Deno and any Dockerfile.
- `size` — the sample uses `2gb-1vcpu`.
- `exposure` — the sample uses `public`.
- `instances` — how many copies.

Tokens need `workers_read` or `workers_write`. The OAuth scope on these alpha routes is `edge_functions:read` or `edge_functions:write`.

### Compute versus Edge Functions versus Vercel

| | Edge Functions | Supabase Compute | Vercel |
| --- | --- | --- | --- |
| Runs | Deno, short HTTP handlers | Node, Deno, or a container; sandboxes and services | The Next.js dashboard |
| Next to Postgres | Yes, at the edge of the project | Yes, same region and network | No, it calls Supabase over the client |
| Long jobs | Wall-clock limits | No wall-clock limit advertised | Serverless limits; use a queue if you outgrow them |
| Untrusted code | No | Sandboxes are the stated use | No |
| Status | Generally available | Private alpha, waitlist | Generally available |

**Check.** Close the docs and write five sentences: what a sandbox is, what an always-on service is, why the incident engine wants to sit next to Postgres, which secret it needs (the model API key) and which it must not log, and which API call you would poll after a deploy. If you cannot name `build_state`, reread the worker page.

Join the waitlist when you want to run Phase 6 on the real runtime. Do not block Phases 4 and 5 on access.

## Phase 4 — Put Compute on the diagram

Goal: decide the workload shape for each box, and refuse the boxes that do not belong.

| Box | Runtime | Why |
| --- | --- | --- |
| OpenTelemetry Collector | A small VM, container, or hosted collector | It is a daemon that receives OTLP. It is not request/response, and it should keep running if Supabase is down. |
| Streaming pipeline | A queue or log | Compute can run a consumer. It should not be the durable log of every span. |
| Raw telemetry store | Object storage or a columnar store | Volume will dwarf incident rows. |
| Stream processor | Compute always-on service, later | Fine once the stream is small. Start with a script on your laptop so you can see windows before you host them. |
| Anomaly rules | Same process as the stream processor | Detection is a pure function over a window. |
| Incident engine | Compute always-on HTTP service | This is the fit: HTTP in, Claude call, Postgres write, no short timeout. |
| Claude | Called by the incident engine | The model is an API. A sandbox is only useful if you later let an agent run tools. |
| Incident state | Postgres | Rows, constraints, RLS. |
| Live UI updates | Realtime | Already in Phase 2. |
| Dashboard | Vercel | Reads incidents, never ingests telemetry. |

### The first Compute service, when you have access

Name it `incident-engine`. One route:

`POST /anomalies`

Body: `{ service, source, signal, value, window_start, window_end, samples[] }`.

Behavior:

1. Reject a body that has no service or no signal.
2. If an `open` incident already exists for that service and signal, append evidence and return the existing id.
3. Call Claude with the bounded packet from Phase 1.
4. Insert `incidents`, `incident_evidence`, and an `incident_events` row of kind `created`.
5. Return the incident id. Realtime, not this HTTP response, updates the dashboard.

Firewall: allow the model API host only. Secret: the model API key, scoped to this workload. Database role: insert and update on the three incident tables only.

Until the waitlist clears, implement that same route as a Supabase Edge Function. The move later is a redeploy, not a redesign, because the contract is the HTTP body and the three tables.

**Check.** Draw the diagram again from memory and mark each box `Compute`, `Postgres`, `Realtime`, `Vercel`, or `other`. You should mark only the incident engine as Compute for the first version.

## Phase 5 — Telemetry, only as far as the first anomaly

Goal: produce one anomaly event the incident engine can accept. Stay at the edge of OpenTelemetry; do not build a platform.

Read the concepts, not the whole spec:

- [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/)
- [OpenTelemetry metrics](https://opentelemetry.io/docs/concepts/signals/metrics/)
- [Collector](https://opentelemetry.io/docs/collector/)

### Minimum signals

Pick one source so the first pipeline is real.

- **Agent path (closest to this project's name).** Log each tool call as a span: tool name, latency, error, retry count. Anomaly: more than N retries for the same tool inside 2 minutes.
- **App path.** A counter for HTTP 5xx. Anomaly: ratio above a fixed threshold.
- **Infra path.** A gauge for CPU. Anomaly: above 80% for 5 minutes.

Ship those with the OpenTelemetry SDK to a local collector config that prints to stdout. When a window breaches, POST the anomaly body from Phase 4 to your function.

Rules before models. A threshold you can explain is the right first detector. A model that scores "weirdness" can wait until you have a week of raw windows and a list of false alarms.

**Check.** Trigger the threshold on purpose (a loop that records failed tool calls). Confirm one anomaly POST, one incident row, and one dashboard update. Confirm a second burst for the same service and signal does not create a second open incident.

## Phase 6 — The Vercel dashboard

Goal: a person can see and acknowledge an incident. The page does not detect anything.

Read [Next.js on Vercel](https://vercel.com/docs/frameworks/nextjs) only if the app framework is new. The Supabase piece is the client you already used in Phase 2, deployed.

Pages:

- `/` — open incidents, newest first, subscribed to Realtime
- `/incidents/[id]` — summary, evidence samples, status timeline

Actions: acknowledge and resolve. Those update `status` and append `incident_events`. Claude's summary is shown as text. It is not a command.

**Check.** From a second browser, insert or resolve an incident and watch the first browser update. Sign out and confirm the anon user cannot read the table.

## Phase 7 — Study order, then build order

Study in this order even if you only have evenings:

1. Phase 0 and 1 in one sitting. You should be able to tell the billing-agent story without the diagram in front of you.
2. Phase 2 hands-on. A scratch Supabase project and one live row.
3. Phase 3 on paper, plus the waitlist. Write the five sentences.
4. Phase 4 as an Edge Function with a hand-written anomaly JSON body. No collector yet.
5. Phase 6 so you can see the row. Deploy the page to Vercel.
6. Phase 5 last. Wire one real signal to that same JSON body.

Build the vertical slice in the same order: **fake anomaly → incident row → Claude summary → Realtime → Vercel**. Add the collector only after that loop is boring.

When Compute access arrives, redeploy the incident engine with `supabase compute deploy` (or the worker upload flow) and point the anomaly POST at the new URL. Leave the tables and the dashboard alone.

## What to ignore until the slice works

- A second detector, or any ML anomaly model
- Storing every span in Postgres
- Multi-region, Multigres, read replicas
- Letting Claude change incident status or call tools
- Replacing the queue with Supabase
- Kubernetes as a source, until one agent signal already creates incidents

## Open choices, after the slice

These are real forks. Decide them with a running dashboard, not before.

- Whether the stream processor moves onto Compute or stays next to the collector
- Whether a future "suggest a fix" action runs inside a Compute sandbox
- How long raw telemetry is kept, and where
- Who may acknowledge an incident (one shared on-call role, or per-service owners)

## Reading list

- [Supabase Compute](https://supabase.com/compute)
- [Supabase Select 2026 recap](https://supabase.com/blog/supabase-select-2026-recap) — Compute, and the note that local Supabase can run without Docker
- [Deploy a worker (alpha)](https://supabase.com/docs/reference/api/v2-deploy-a-worker)
- [Get a worker (alpha)](https://supabase.com/docs/reference/api/v2-get-a-worker)
- [Get a compute instance (alpha)](https://supabase.com/docs/reference/api/v2-get-a-compute-instance)
- [Compute and Disk](https://supabase.com/docs/guides/platform/compute-and-disk) — database size, a different product
- [Realtime Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes)
- [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Edge Functions](https://supabase.com/docs/guides/functions) — the stand-in until Compute access
- [OpenTelemetry concepts](https://opentelemetry.io/docs/concepts/signals/)
