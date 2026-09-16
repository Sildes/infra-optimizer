"""Contrats de données du rapport d'analyse (schéma de sortie de l'énoncé)."""
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


Severity = Literal["low", "medium", "high"]
ServiceName = Literal["database", "api_gateway", "cache"]
ServiceStatus = Literal["online", "degraded", "offline"]
# Le timestamp doit être au format ISO 8601
IsoUtcTimestamp = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]

class Anomaly(BaseModel):
    metric: str
    value: float
    threshold: float
    severity: Severity
    description: str

class Insights(BaseModel):
    """Agrégats de la période analysée."""

    average_latency_ms: float
    max_cpu_usage: float
    max_memory_usage: float
    error_rate: float
    uptime_seconds: float


class Recommendation(BaseModel):
    id: str
    action: str
    target: str
    parameters: dict
    benefit_estimate: str


class ServiceStatusSummary(BaseModel):
    online: list[ServiceName]
    degraded: list[ServiceName]
    offline: list[ServiceName]

class MetricRecord(BaseModel):
    # On force le timestamp à être au format ISO 8601
    timestamp: IsoUtcTimestamp
    cpu_usage: float
    memory_usage: float
    latency_ms: float
    disk_usage: float
    network_in_kbps: float
    network_out_kbps: float
    io_wait: float
    thread_count: int
    active_connections: int
    error_rate: float
    uptime_seconds: int
    temperature_celsius: float
    power_consumption_watts: float
    service_status: dict[ServiceName, ServiceStatus]


class Report(BaseModel):
    # On force le timestamp à être au format ISO 8601
    timestamp: IsoUtcTimestamp
    insights: Insights
    anomalies: list[Anomaly]
    recommendations: list[Recommendation]
    service_status_summary: ServiceStatusSummary
