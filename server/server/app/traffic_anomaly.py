from __future__ import annotations

import hashlib
import re
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any

_HTTP_REQ_RE = re.compile(
    r'"?(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+([^\s"?#]+)(?:\?[^\s"]*)?\s*(?:HTTP/[0-9.]+)?"?(?:\s+(\d{3}))?',
    re.IGNORECASE,
)
_STATUS_CODE_RE = re.compile(r'(?:HTTP/[0-9.]+"\s+|status[=:\s]+)(\d{3})\b', re.IGNORECASE)
_LEADING_IP_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\b")
_CLIENT_IP_KEY_RE = re.compile(r"(?:client_ip|ip|remote_addr|src)[=:\s]+(\d{1,3}(?:\.\d{1,3}){3})\b", re.IGNORECASE)
_LATENCY_RE = re.compile(r"(?:latency|request_time|upstream_response_time|duration)[=:\s]+([0-9]+(?:\.[0-9]+)?)\s*(ms|s)?", re.IGNORECASE)

SENSITIVE_PATHS = (
    "/login",
    "/admin",
    "/wp-login.php",
    "/.env",
    "/.git",
    "/xmlrpc.php",
    "/phpmyadmin",
)


class TrafficAnomalyDetector:
    """Real-time sliding-window HTTP/network traffic anomaly detector per website."""

    def __init__(
        self,
        max_events_per_website: int = 5000,
        cooldown_seconds: int = 60,
    ) -> None:
        self.max_events_per_website = max(100, int(max_events_per_website))
        self.cooldown_seconds = max(0, int(cooldown_seconds))
        self._events: dict[str, deque[dict[str, Any]]] = {}
        self._anomalies: dict[str, deque[dict[str, Any]]] = {}
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    def record_event(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        website_id = str(event.get("website_id") or "").strip()
        if not website_id:
            return []

        parsed = self._extract_traffic_record(event)
        bucket = self._events.setdefault(website_id, deque(maxlen=self.max_events_per_website))
        bucket.append(parsed)

        now_dt = parsed["timestamp_dt"]
        if len(bucket) > 1:
            latest_dt = max(item["timestamp_dt"] for item in bucket)
            if latest_dt > now_dt:
                now_dt = latest_dt

        triggered: list[dict[str, Any]] = []
        agent_id = parsed["agent_id"]

        drop = self._evaluate_traffic_drop(website_id, agent_id, bucket, now_dt)
        if drop:
            triggered.append(drop)

        spike = self._evaluate_traffic_spike(website_id, agent_id, bucket, now_dt)
        if spike:
            triggered.append(spike)

        brute = self._evaluate_brute_force(website_id, agent_id, bucket, now_dt)
        if brute:
            triggered.append(brute)

        error_burst = self._evaluate_error_burst(website_id, agent_id, bucket, now_dt)
        if error_burst:
            triggered.append(error_burst)

        if triggered:
            anomaly_bucket = self._anomalies.setdefault(website_id, deque(maxlen=100))
            for item in triggered:
                anomaly_bucket.append(item)

        return triggered

    def check_traffic_drop(
        self,
        website_id: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        bucket = self._events.get(website_id)
        if not bucket:
            return None
        now_dt = _coerce_datetime(now) or datetime.now(timezone.utc)
        last_agent = str(bucket[-1].get("agent_id") or "unknown")
        anomaly = self._evaluate_traffic_drop(website_id, last_agent, bucket, now_dt)
        if anomaly:
            self._anomalies.setdefault(website_id, deque(maxlen=100)).append(anomaly)
        return anomaly

    def get_website_traffic_summary(
        self,
        website_id: str,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        bucket = list(self._events.get(website_id) or [])
        anomalies = list(self._anomalies.get(website_id) or [])
        if not bucket:
            return {
                "website_id": website_id,
                "requests_1m": 0,
                "requests_5m": 0,
                "rpm_baseline": 0.0,
                "status_counts": {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0},
                "error_rate_percent": 0.0,
                "top_ips": [],
                "top_paths": [],
                "recent_anomalies": anomalies[-20:][::-1],
            }

        now_dt = _coerce_datetime(now) or max(item["timestamp_dt"] for item in bucket)
        cutoff_1m = now_dt - timedelta(seconds=60)
        cutoff_5m = now_dt - timedelta(seconds=300)
        cutoff_6m = now_dt - timedelta(seconds=360)

        events_1m = [item for item in bucket if cutoff_1m < item["timestamp_dt"] <= now_dt]
        events_5m = [item for item in bucket if cutoff_5m < item["timestamp_dt"] <= now_dt]
        prev_5m = [item for item in bucket if cutoff_6m < item["timestamp_dt"] <= cutoff_1m]

        active_window = events_5m if events_5m else bucket[-200:]
        status_counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        for item in active_window:
            code = item.get("status_code")
            if isinstance(code, int):
                if 200 <= code < 300:
                    status_counts["2xx"] += 1
                elif 300 <= code < 400:
                    status_counts["3xx"] += 1
                elif 400 <= code < 500:
                    status_counts["4xx"] += 1
                elif 500 <= code < 600:
                    status_counts["5xx"] += 1

        total_window = len(active_window)
        error_rate = round((status_counts["5xx"] / total_window) * 100.0, 2) if total_window > 0 else 0.0
        rpm_baseline = round(len(prev_5m) / 5.0, 2) if prev_5m else round(len(events_5m) / 5.0, 2)

        ip_counter = Counter(
            item["client_ip"] for item in active_window if item.get("client_ip") and item["client_ip"] != "unknown"
        )
        path_counter = Counter(
            item["path"] for item in active_window if item.get("path")
        )

        return {
            "website_id": website_id,
            "requests_1m": len(events_1m),
            "requests_5m": len(events_5m),
            "rpm_baseline": rpm_baseline,
            "status_counts": status_counts,
            "error_rate_percent": error_rate,
            "top_ips": [{"ip": ip, "count": count} for ip, count in ip_counter.most_common(5)],
            "top_paths": [{"path": path, "count": count} for path, count in path_counter.most_common(5)],
            "recent_anomalies": anomalies[-20:][::-1],
        }

    def _extract_traffic_record(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(event.get("metadata") or {})
        message = str(event.get("message") or "")
        timestamp_raw = event.get("timestamp") or event.get("observed_at")
        timestamp_dt = _coerce_datetime(timestamp_raw) or datetime.now(timezone.utc)

        method = str(event.get("method") or metadata.get("method") or "").upper()
        path = str(event.get("path") or metadata.get("path") or "").strip()
        status_code = _coerce_int(event.get("status_code") or metadata.get("status_code"))

        req_match = _HTTP_REQ_RE.search(message)
        if req_match:
            if not method:
                method = req_match.group(1).upper()
            if not path:
                path = req_match.group(2).strip()
            if status_code is None and req_match.group(3):
                status_code = _coerce_int(req_match.group(3))

        if status_code is None:
            status_match = _STATUS_CODE_RE.search(message)
            if status_match:
                status_code = _coerce_int(status_match.group(1))

        client_ip = str(
            event.get("client_ip")
            or metadata.get("client_ip")
            or metadata.get("remote_addr")
            or ""
        ).strip()
        if not client_ip:
            ip_match = _LEADING_IP_RE.search(message) or _CLIENT_IP_KEY_RE.search(message)
            if ip_match:
                client_ip = ip_match.group(1)
        if not client_ip:
            client_ip = str(event.get("source_ip") or "unknown").strip() or "unknown"

        latency_ms = _coerce_float(event.get("latency_ms") or metadata.get("latency_ms"))
        if latency_ms is None:
            lat_match = _LATENCY_RE.search(message)
            if lat_match:
                val = float(lat_match.group(1))
                unit = (lat_match.group(2) or "ms").lower()
                latency_ms = val * 1000.0 if unit == "s" else val

        return {
            "website_id": str(event.get("website_id") or ""),
            "agent_id": str(event.get("agent_id") or "unknown"),
            "timestamp": timestamp_dt.isoformat(),
            "timestamp_dt": timestamp_dt,
            "status_code": status_code,
            "client_ip": client_ip,
            "path": path or "/",
            "method": method or "GET",
            "latency_ms": latency_ms,
            "category": str(event.get("category") or ""),
            "severity": str(event.get("severity") or "normal"),
        }

    def _evaluate_traffic_spike(
        self,
        website_id: str,
        agent_id: str,
        bucket: deque[dict[str, Any]],
        now_dt: datetime,
    ) -> dict[str, Any] | None:
        if not self._can_fire(website_id, "traffic_spike", now_dt):
            return None

        cutoff_1m = now_dt - timedelta(seconds=60)
        cutoff_6m = now_dt - timedelta(seconds=360)
        events_1m = [item for item in bucket if cutoff_1m < item["timestamp_dt"] <= now_dt]
        requests_1m = len(events_1m)
        if requests_1m < 30:
            return None

        prev_5m = [item for item in bucket if cutoff_6m < item["timestamp_dt"] <= cutoff_1m]
        baseline_rpm = (len(prev_5m) / 5.0) if prev_5m else 10.0
        ratio = requests_1m / max(baseline_rpm, 1.0)
        if ratio < 3.0:
            return None

        top_ip, top_ip_count = ("unknown", 0)
        ip_counts = Counter(item["client_ip"] for item in events_1m if item.get("client_ip"))
        if ip_counts:
            top_ip, top_ip_count = ip_counts.most_common(1)[0]

        top_path, top_path_count = ("/", 0)
        path_counts = Counter(item["path"] for item in events_1m if item.get("path"))
        if path_counts:
            top_path, top_path_count = path_counts.most_common(1)[0]

        self._mark_fired(website_id, "traffic_spike", now_dt)
        return self._make_anomaly(
            website_id=website_id,
            agent_id=agent_id,
            anomaly_type="traffic_spike",
            severity="critical" if ratio >= 5.0 or requests_1m >= 100 else "problem",
            title=f"Traffic Spike / DDoS Flood ({requests_1m} req/min, {ratio:.1f}x baseline)",
            description=(
                f"Detected {requests_1m} requests in 60s ({ratio:.1f}x baseline of {baseline_rpm:.1f} rpm). "
                f"Top client IP {top_ip} ({top_ip_count} reqs) targeting {top_path} ({top_path_count} reqs)."
            ),
            metrics={
                "requests_1m": requests_1m,
                "baseline_rpm": round(baseline_rpm, 2),
                "spike_ratio": round(ratio, 2),
                "top_client_ip": top_ip,
                "top_client_ip_count": top_ip_count,
                "target_path": top_path,
                "target_path_count": top_path_count,
            },
            detected_at=now_dt,
        )

    def _evaluate_traffic_drop(
        self,
        website_id: str,
        agent_id: str,
        bucket: deque[dict[str, Any]],
        now_dt: datetime,
    ) -> dict[str, Any] | None:
        if not self._can_fire(website_id, "traffic_drop", now_dt):
            return None

        cutoff_1m = now_dt - timedelta(seconds=60)
        cutoff_6m = now_dt - timedelta(seconds=360)
        prev_5m = [item for item in bucket if cutoff_6m < item["timestamp_dt"] <= cutoff_1m]
        baseline_rpm = len(prev_5m) / 5.0
        if baseline_rpm < 10.0:
            return None

        events_1m = [item for item in bucket if cutoff_1m < item["timestamp_dt"] <= now_dt]
        requests_1m = len(events_1m)
        if requests_1m > 0 and requests_1m >= (0.10 * baseline_rpm):
            return None

        self._mark_fired(website_id, "traffic_drop", now_dt)
        return self._make_anomaly(
            website_id=website_id,
            agent_id=agent_id,
            anomaly_type="traffic_drop",
            severity="critical" if requests_1m == 0 else "problem",
            title=f"Traffic Drop / Silent Outage ({requests_1m} req/min vs {baseline_rpm:.1f} rpm baseline)",
            description=(
                f"Traffic dropped from {baseline_rpm:.1f} req/min baseline to {requests_1m} req/min in the last 60s. "
                "Possible upstream load balancer blackhole, DNS failure, or firewall drop."
            ),
            metrics={
                "requests_1m": requests_1m,
                "baseline_rpm": round(baseline_rpm, 2),
                "previous_5m_requests": len(prev_5m),
            },
            detected_at=now_dt,
        )

    def _evaluate_brute_force(
        self,
        website_id: str,
        agent_id: str,
        bucket: deque[dict[str, Any]],
        now_dt: datetime,
    ) -> dict[str, Any] | None:
        if not self._can_fire(website_id, "brute_force", now_dt):
            return None

        cutoff_1m = now_dt - timedelta(seconds=60)
        events_1m = [item for item in bucket if cutoff_1m < item["timestamp_dt"] <= now_dt]
        suspicious_by_ip: dict[str, list[dict[str, Any]]] = {}
        for item in events_1m:
            code = item.get("status_code")
            path = str(item.get("path") or "").lower()
            is_auth_or_scan_code = code in {401, 403, 404}
            is_sensitive_path = any(
                path == target or path.startswith(target + "/") or target in path
                for target in SENSITIVE_PATHS
            )
            if is_auth_or_scan_code or is_sensitive_path:
                ip = str(item.get("client_ip") or "unknown")
                suspicious_by_ip.setdefault(ip, []).append(item)

        for ip, items in suspicious_by_ip.items():
            if len(items) >= 15:
                top_path = Counter(i["path"] for i in items).most_common(1)[0][0]
                status_breakdown = Counter(str(i.get("status_code") or "unknown") for i in items)
                self._mark_fired(website_id, "brute_force", now_dt)
                return self._make_anomaly(
                    website_id=website_id,
                    agent_id=agent_id,
                    anomaly_type="brute_force",
                    severity="problem" if len(items) < 30 else "critical",
                    title=f"Brute Force / Scanner Detected from {ip} ({len(items)} attempts/60s)",
                    description=(
                        f"Client IP {ip} generated {len(items)} auth/scanner requests in 60s "
                        f"targeting {top_path} (statuses: {dict(status_breakdown)})."
                    ),
                    metrics={
                        "client_ip": ip,
                        "attempt_count_1m": len(items),
                        "target_path": top_path,
                        "status_breakdown": dict(status_breakdown),
                    },
                    detected_at=now_dt,
                )
        return None

    def _evaluate_error_burst(
        self,
        website_id: str,
        agent_id: str,
        bucket: deque[dict[str, Any]],
        now_dt: datetime,
    ) -> dict[str, Any] | None:
        if not self._can_fire(website_id, "error_burst", now_dt):
            return None

        cutoff_1m = now_dt - timedelta(seconds=60)
        events_1m = [item for item in bucket if cutoff_1m < item["timestamp_dt"] <= now_dt]
        total_1m = len(events_1m)
        if total_1m < 10:
            return None

        errors_5xx = [
            item
            for item in events_1m
            if isinstance(item.get("status_code"), int) and 500 <= int(item["status_code"]) <= 599
        ]
        count_5xx = len(errors_5xx)
        ratio_5xx = count_5xx / total_1m
        if ratio_5xx < 0.15:
            return None

        top_status = Counter(int(item["status_code"]) for item in errors_5xx).most_common(1)[0][0]
        top_path = Counter(item["path"] for item in errors_5xx).most_common(1)[0][0]
        self._mark_fired(website_id, "error_burst", now_dt)
        return self._make_anomaly(
            website_id=website_id,
            agent_id=agent_id,
            anomaly_type="error_burst",
            severity="critical" if ratio_5xx >= 0.40 or top_status in {502, 503, 504} else "problem",
            title=f"HTTP 5xx Error Burst ({ ratio_5xx * 100:.1f}% 5xx in 60s, top {top_status})",
            description=(
                f"{count_5xx} of {total_1m} requests ({ratio_5xx * 100:.1f}%) returned HTTP 5xx in the last 60s "
                f"(top status {top_status} on {top_path})."
            ),
            metrics={
                "requests_1m": total_1m,
                "errors_5xx_1m": count_5xx,
                "error_ratio": round(ratio_5xx, 4),
                "error_rate_percent": round(ratio_5xx * 100.0, 2),
                "top_status_code": top_status,
                "top_error_path": top_path,
            },
            detected_at=now_dt,
        )

    def _can_fire(self, website_id: str, anomaly_type: str, now_dt: datetime) -> bool:
        if self.cooldown_seconds <= 0:
            return True
        last_fired = self._cooldowns.get((website_id, anomaly_type))
        if not last_fired:
            return True
        return (now_dt - last_fired).total_seconds() >= self.cooldown_seconds

    def _mark_fired(self, website_id: str, anomaly_type: str, now_dt: datetime) -> None:
        self._cooldowns[(website_id, anomaly_type)] = now_dt

    def _make_anomaly(
        self,
        website_id: str,
        agent_id: str,
        anomaly_type: str,
        severity: str,
        title: str,
        description: str,
        metrics: dict[str, Any],
        detected_at: datetime,
    ) -> dict[str, Any]:
        ts_iso = detected_at.isoformat()
        basis = f"{website_id}|{agent_id}|{anomaly_type}|{ts_iso}"
        anomaly_id = "anom_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
        return {
            "anomaly_id": anomaly_id,
            "website_id": website_id,
            "agent_id": agent_id,
            "anomaly_type": anomaly_type,
            "severity": severity,
            "title": title,
            "description": description,
            "metrics": metrics,
            "detected_at": ts_iso,
        }


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
