import json
import logging
from urllib import request

from aid.config import OPENAI_API_KEY, OPENAI_MODEL, WINDOW_SECONDS

log = logging.getLogger("aid.summary")

_DEVELOPER = (
    "You summarize one production incident for an on-call engineer. "
    "Write two sentences: what crossed the threshold, and one likely cause. "
    "Use only the JSON packet and the previous incidents included in it. "
    "If a previous incident has the same service and signal, say that it matches and reuse that cause. "
    "If the packet is not enough, say what is missing. "
    "This summary is not approval to restart, roll back, or change incident status."
)


def summarize(anomaly: dict, prior: list[dict] | None = None) -> tuple[str, str]:
    if not OPENAI_API_KEY:
        return _template(anomaly), "template"
    try:
        return _openai(anomaly, prior or []), "openai"
    except Exception:
        log.exception("openai summary failed; storing the template sentence")
        return _template(anomaly), "template"


def build_prompt(anomaly: dict, prior: list[dict]) -> str:
    samples = []
    for sample in anomaly["samples"]:
        payload = sample["payload"]
        samples.append(
            {
                "kind": sample["kind"],
                "at": sample["observed_at"],
                "body": payload.get("body"),
                "value": payload.get("value"),
                "attributes": payload.get("attributes"),
            }
        )
    history = [
        {
            "title": item.get("title"),
            "summary": item.get("summary"),
            "status": item.get("status"),
            "value": item.get("value"),
            "created_at": item.get("created_at"),
        }
        for item in prior
    ]
    return json.dumps(
        {
            "service": anomaly["service"],
            "source": anomaly["source"],
            "signal": anomaly["signal"],
            "value": anomaly["value"],
            "window_start": anomaly["window_start"],
            "window_end": anomaly["window_end"],
            "samples": samples,
            "previous_incidents": history,
        }
    )


def _template(anomaly: dict) -> str:
    return f"Measured {anomaly['value']} over the last {WINDOW_SECONDS} seconds."


def _openai(anomaly: dict, prior: list[dict]) -> str:
    payload = {
        "model": OPENAI_MODEL,
        "max_completion_tokens": 300,
        "reasoning_effort": "none" if OPENAI_MODEL.startswith("gpt-6") else "minimal",
        "messages": [
            {"role": "developer", "content": _DEVELOPER},
            {"role": "user", "content": build_prompt(anomaly, prior)},
        ],
    }
    body = json.dumps(payload).encode()
    req = request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "authorization": f"Bearer {OPENAI_API_KEY}",
            "content-type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode())
    text = _message_text(payload["choices"][0]["message"]["content"])
    if not text:
        raise RuntimeError("model returned an empty summary")
    return text


def _message_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    parts = []
    for part in content or []:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("text"):
            parts.append(part["text"])
    return "".join(parts).strip()
