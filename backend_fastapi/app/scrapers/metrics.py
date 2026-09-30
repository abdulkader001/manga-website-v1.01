import structlog
from typing import Dict, Any

logger = structlog.get_logger(__name__)

# Basic in-memory metrics for demonstration.
# In production, use Prometheus client (`prometheus_client`) or StatsD.


class ScraperMetrics:
    _metrics: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def _init_domain(cls, domain: str):
        if domain not in cls._metrics:
            cls._metrics[domain] = {
                "success_count": 0,
                "failure_count": 0,
                "total_retries": 0,
                "total_latency_ms": 0,
                "request_count": 0,
            }

    @classmethod
    def record_success(cls, domain: str, latency_ms: int):
        cls._init_domain(domain)
        cls._metrics[domain]["success_count"] += 1
        cls._metrics[domain]["total_latency_ms"] += latency_ms
        cls._metrics[domain]["request_count"] += 1
        logger.info(f"METRIC: Success for {domain} (latency: {latency_ms}ms)")

    @classmethod
    def record_failure(cls, domain: str):
        cls._init_domain(domain)
        cls._metrics[domain]["failure_count"] += 1
        cls._metrics[domain]["request_count"] += 1
        logger.error(f"METRIC: Failure for {domain}")

    @classmethod
    def record_retry(cls, domain: str):
        cls._init_domain(domain)
        cls._metrics[domain]["total_retries"] += 1
        logger.warning(f"METRIC: Retry for {domain}")

    @classmethod
    def get_metrics(cls, domain: str = None) -> Dict[str, Any]:
        if domain:
            return cls._metrics.get(domain, {})
        return cls._metrics
