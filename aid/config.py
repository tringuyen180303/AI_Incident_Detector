import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


BROKERS = _env("KAFKA_BROKERS", "localhost:9092")
DATABASE_URL = _env("DATABASE_URL", "postgresql://aid:aid@localhost:5433/aid")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-5-nano")

WINDOW_SECONDS = int(_env("WINDOW_SECONDS", "30"))
COOLDOWN_SECONDS = int(_env("COOLDOWN_SECONDS", "30"))
RETRY_THRESHOLD = int(_env("RETRY_THRESHOLD", "5"))
MIN_REQUESTS = int(_env("MIN_REQUESTS", "10"))
ERROR_RATIO_THRESHOLD = float(_env("ERROR_RATIO_THRESHOLD", "0.05"))
CPU_THRESHOLD = float(_env("CPU_THRESHOLD", "0.8"))
CPU_MIN_SAMPLES = int(_env("CPU_MIN_SAMPLES", "3"))

TELEMETRY_PARTITIONS = int(_env("TELEMETRY_PARTITIONS", "12"))
ANOMALY_PARTITIONS = int(_env("ANOMALY_PARTITIONS", "3"))
OTLP_PARTITIONS = int(_env("OTLP_PARTITIONS", "6"))
API_PORT = int(_env("API_PORT", "8080"))

TELEMETRY_TOPIC = "telemetry"
ANOMALY_TOPIC = "anomalies"
OTLP_LOGS_TOPIC = "otlp.logs"
OTLP_METRICS_TOPIC = "otlp.metrics"
OTLP_TRACES_TOPIC = "otlp.traces"

# Raw telemetry is kept for a day. Anomalies are kept for a week.
# Neither topic is copied into Supabase.
TELEMETRY_RETENTION_MS = "86400000"
ANOMALY_RETENTION_MS = "604800000"
EVIDENCE_LOG_LIMIT = 5
