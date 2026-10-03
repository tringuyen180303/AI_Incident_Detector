"""Convert OTLP JSON from the collector into the telemetry topic shape."""

from datetime import datetime, timezone

from aid.events import event


def otlp_to_events(payload: dict) -> list[dict]:
    if "kind" in payload and "service" in payload:
        return [payload]
    found: list[dict] = []
    found.extend(_logs(payload))
    found.extend(_metrics(payload))
    found.extend(_spans(payload))
    return found


def _logs(payload: dict) -> list[dict]:
    events = []
    for resource_logs in payload.get("resourceLogs", []):
        service = _service_name(resource_logs.get("resource", {}))
        for scope in resource_logs.get("scopeLogs", []):
            for record in scope.get("logRecords", []):
                body = _any_value(record.get("body"))
                attributes = _attributes(record.get("attributes"))
                severity = str(record.get("severityText") or attributes.get("severity") or "INFO")
                events.append(
                    event(
                        kind="log",
                        source=_source(service, attributes),
                        service=service,
                        signal="log",
                        ts=_time(record.get("timeUnixNano") or record.get("observedTimeUnixNano")),
                        body=str(body) if body is not None else "",
                        attributes={**attributes, "severity": severity.upper()},
                    )
                )
    return events


def _metrics(payload: dict) -> list[dict]:
    events = []
    for resource_metrics in payload.get("resourceMetrics", []):
        service = _service_name(resource_metrics.get("resource", {}))
        for scope in resource_metrics.get("scopeMetrics", []):
            for metric in scope.get("metrics", []):
                events.extend(_metric(service, metric))
    return events


def _metric(service: str, metric: dict) -> list[dict]:
    name = metric.get("name", "")
    datapoints = _datapoints(metric)
    if name == "system.cpu.utilization":
        busy = _cpu_busy(datapoints)
        if busy is None:
            return []
        return [
            event(
                kind="metric",
                source="infrastructure",
                service=service,
                signal="cpu.utilization",
                ts=_time(datapoints[-1].get("timeUnixNano")),
                value=busy,
                attributes={"states": "non-idle"},
            )
        ]
    if name in {"system.memory.utilization", "process.cpu.utilization"}:
        value = _number(datapoints[-1]) if datapoints else None
        if value is None:
            return []
        return [
            event(
                kind="metric",
                source="infrastructure",
                service=service,
                signal="cpu.utilization" if "cpu" in name else "memory.utilization",
                ts=_time(datapoints[-1].get("timeUnixNano")),
                value=value,
            )
        ]
    return []


def _spans(payload: dict) -> list[dict]:
    events = []
    for resource_spans in payload.get("resourceSpans", []):
        service = _service_name(resource_spans.get("resource", {}))
        for scope in resource_spans.get("scopeSpans", []):
            for span in scope.get("spans", []):
                attributes = _attributes(span.get("attributes"))
                tool = attributes.get("gen_ai.tool.name")
                operation = attributes.get("gen_ai.operation.name")
                if not tool and operation not in {"execute_tool", "tools/call"}:
                    continue
                status = span.get("status") or {}
                failed = status.get("code") in {2, "STATUS_CODE_ERROR"}
                tool_name = str(tool or span.get("name") or "tool")
                events.append(
                    event(
                        kind="tool_call",
                        source="agent",
                        service=service,
                        signal="tool.retry" if failed else "tool.call",
                        ts=_time(span.get("endTimeUnixNano") or span.get("startTimeUnixNano")),
                        body=status.get("message") or tool_name,
                        attributes={
                            "tool": tool_name,
                            "error": failed,
                            "trace_id": span.get("traceId"),
                            "span_id": span.get("spanId"),
                        },
                    )
                )
    return events


def _datapoints(metric: dict) -> list[dict]:
    body = metric.get("gauge") or metric.get("sum") or {}
    return list(body.get("dataPoints") or [])


def _cpu_busy(datapoints: list[dict]) -> float | None:
    if not datapoints:
        return None
    states = []
    idles = []
    for point in datapoints:
        value = _number(point)
        if value is None:
            continue
        state = _attributes(point.get("attributes")).get("state")
        if state is None:
            return value
        if state == "idle":
            idles.append(value)
        else:
            states.append(value)
    if idles:
        return max(0.0, min(1.0, 1 - (sum(idles) / len(idles))))
    if states:
        return max(0.0, min(1.0, sum(states)))
    return None


def _number(point: dict) -> float | None:
    if "asDouble" in point:
        return float(point["asDouble"])
    if "asInt" in point:
        return float(point["asInt"])
    return None


def _service_name(resource: dict) -> str:
    attributes = _attributes(resource.get("attributes"))
    return str(attributes.get("service.name") or attributes.get("host.name") or "unknown")


def _source(service: str, attributes: dict) -> str:
    if "gen_ai.tool.name" in attributes or "agent" in service:
        return "agent"
    return "application"


def _attributes(items) -> dict:
    parsed = {}
    for item in items or []:
        parsed[item.get("key")] = _any_value(item.get("value"))
    return parsed


def _any_value(value):
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            if key == "intValue":
                return int(value[key])
            return value[key]
    return None


def _time(nanos) -> datetime:
    if not nanos:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(nanos) / 1_000_000_000, timezone.utc)
