"""Systems Telemetry Daemon - Linux/OS resource monitor and performance profiler."""

from __future__ import annotations
import os
import re
import json
import time
import argparse
import sys
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque, DefaultDict, Dict, List, Optional, Tuple

import psutil


SystemMetrics = Dict[str, float]


class SystemMonitor:
    """Collects and monitors system resource metrics."""

    def __init__(self, sampling_interval: float = 1.0):
        self.sampling_interval = sampling_interval
        self.metrics_history: Deque[SystemMetrics] = deque(maxlen=3600)
        self.cpu_history: Deque[float] = deque(maxlen=3600)
        self.memory_history: Deque[float] = deque(maxlen=3600)
        self.net_io_history: Deque[Tuple[int, int]] = deque(maxlen=3600)
        self.disk_io_history: Deque[Tuple[int, int]] = deque(maxlen=3600)
        self._prev_net: Optional[psutil.NetIOCounters] = None
        self._prev_disk: Optional[psutil.DiskIOCounters] = None

    def collect(self) -> SystemMetrics:
        """Collect current system metrics."""
        now = datetime.now()

        # CPU percent (non-blocking, instantaneous)
        cpu_percent = psutil.cpu_percent(interval=self.sampling_interval)

        # Memory
        mem = psutil.virtual_memory()
        memory_used_mb = mem.used / (1024 * 1024)
        memory_total_mb = mem.total / (1024 * 1024)

        # Disk I/O rates
        disk_io = psutil.disk_io_counters()
        disk_read_rate, disk_write_rate = self._compute_io_rate(
            disk_io, self._prev_disk
        )
        self._prev_disk = disk_io

        # Network I/O rates
        net_io = psutil.net_io_counters()
        net_sent_rate, net_recv_rate = self._compute_io_rate(net_io, self._prev_net)
        self._prev_net = net_io

        metrics: SystemMetrics = {
            "timestamp": now.isoformat(),
            "cpu_percent": cpu_percent,
            "memory_percent": mem.percent,
            "memory_used_mb": round(memory_used_mb, 2),
            "memory_total_mb": round(memory_total_mb, 2),
            "disk_read_mb_s": round(disk_read_rate, 2),
            "disk_write_mb_s": round(disk_write_rate, 2),
            "net_sent_mb_s": round(net_sent_rate, 2),
            "net_recv_mb_s": round(net_recv_rate, 2),
        }

        self.metrics_history.append(metrics)
        self.cpu_history.append(cpu_percent)
        self.memory_history.append(memory_used_mb)
        self.net_io_history.append((net_sent_rate, net_recv_rate))
        self.disk_io_history.append((disk_read_rate, disk_write_rate))

        return metrics

    @staticmethod
    def _compute_io_rate(
        current: psutil.IOCounters, previous: Optional[psutil.IOCounters]
    ) -> Tuple[float, float]:
        """Compute MB/s rates from IO counters, handling first-call case."""
        if previous is None:
            return 0.0, 0.0

        # psutil.IOCounters has: read_count, write_count, read_bytes, write_bytes
        # We use bytes for rate calculation
        read_bytes = current.read_bytes - previous.read_bytes
        write_bytes = current.write_bytes - previous.write_bytes

        # Convert to MB/s (assume 1-second interval)
        read_mb_s = read_bytes / (1024 * 1024)
        write_mb_s = write_bytes / (1024 * 1024)
        return max(0.0, read_mb_s), max(0.0, write_mb_s)

    def get_current(self) -> SystemMetrics:
        """Return the most recent metrics snapshot."""
        if not self.metrics_history:
            return self._empty_metrics()
        return self.metrics_history[-1]

    @staticmethod
    def _empty_metrics() -> SystemMetrics:
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "memory_used_mb": 0.0,
            "memory_total_mb": 0.0,
            "disk_read_mb_s": 0.0,
            "disk_write_mb_s": 0.0,
            "net_sent_mb_s": 0.0,
            "net_recv_mb_s": 0.0,
        }

    def get_average(self, window: Optional[int] = None) -> SystemMetrics:
        """Return average metrics over the specified window (or all history)."""
        history = list(self.metrics_history)
        if window and window < len(history):
            history = history[-window:]

        if not history:
            return self._empty_metrics()

        n = len(history)
        return {
            "timestamp": history[-1]["timestamp"],
            "cpu_percent": sum(m["cpu_percent"] for m in history) / n,
            "memory_percent": sum(m["memory_percent"] for m in history) / n,
            "memory_used_mb": sum(m["memory_used_mb"] for m in history) / n,
            "memory_total_mb": sum(m["memory_total_mb"] for m in history) / n,
            "disk_read_mb_s": sum(m["disk_read_mb_s"] for m in history) / n,
            "disk_write_mb_s": sum(m["disk_write_mb_s"] for m in history) / n,
            "net_sent_mb_s": sum(m["net_sent_mb_s"] for m in history) / n,
            "net_recv_mb_s": sum(m["net_recv_mb_s"] for m in history) / n,
        }

    def get_peak(self) -> SystemMetrics:
        """Return peak metrics observed."""
        if not self.metrics_history:
            return self._empty_metrics()
        hist = list(self.metrics_history)
        return {
            "timestamp": max(hist, key=lambda m: m["cpu_percent"])["timestamp"],
            "cpu_percent": max(m["cpu_percent"] for m in hist),
            "memory_percent": max(m["memory_percent"] for m in hist),
            "memory_used_mb": max(m["memory_used_mb"] for m in hist),
            "memory_total_mb": max(m["memory_total_mb"] for m in hist),
            "disk_read_mb_s": max(m["disk_read_mb_s"] for m in hist),
            "disk_write_mb_s": max(m["disk_write_mb_s"] for m in hist),
            "net_sent_mb_s": max(m["net_sent_mb_s"] for m in hist),
            "net_recv_mb_s": max(m["net_recv_mb_s"] for m in hist),
        }

    def get_min(self) -> SystemMetrics:
        """Return minimum metrics observed."""
        if not self.metrics_history:
            return self._empty_metrics()
        hist = list(self.metrics_history)
        return {
            "timestamp": min(hist, key=lambda m: m["cpu_percent"])["timestamp"],
            "cpu_percent": min(m["cpu_percent"] for m in hist),
            "memory_percent": min(m["memory_percent"] for m in hist),
            "memory_used_mb": min(m["memory_used_mb"] for m in hist),
            "memory_total_mb": min(m["memory_total_mb"] for m in hist),
            "disk_read_mb_s": min(m["disk_read_mb_s"] for m in hist),
            "disk_write_mb_s": min(m["disk_write_mb_s"] for m in hist),
            "net_sent_mb_s": min(m["net_sent_mb_s"] for m in hist),
            "net_recv_mb_s": min(m["net_recv_mb_s"] for m in hist),
        }


class PerformanceProfiler:
    """Profiles performance patterns and detects anomalies."""

    def __init__(self, monitor: SystemMonitor, window: int = 60):
        self.monitor = monitor
        self.window = window
        self.alerts: List[Dict] = []

    def analyze_window(self) -> Dict:
        """Analyze the current window and return findings."""
        avg = self.monitor.get_average(window=self.window)
        peak = self.monitor.get_peak()
        current = self.monitor.get_current()

        findings: Dict = {
            "window": self.window,
            "average": avg,
            "peak": peak,
            "current": current,
            "anomalies": [],
        }

        # Detect anomalies
        if current["cpu_percent"] > 90:
            findings["anomalies"].append(
                {"type": "high_cpu", "message": f"CPU at {current['cpu_percent']}%"}
            )

        if current["memory_percent"] > 85:
            findings["anomalies"].append(
                {"type": "high_memory", "message": f"Memory at {current['memory_percent']}%"}
            )

        if current["disk_write_mb_s"] > 100 and peak["disk_write_mb_s"] > 100:
            findings["anomalies"].append(
                {"type": "high_disk_io", "message": f"Disk write throughput high: {current['disk_write_mb_s']} MB/s"}
            )

        if current["net_sent_mb_s"] > 500:
            findings["anomalies"].append(
                {"type": "high_network", "message": f"Network send throughput high: {current['net_sent_mb_s']} MB/s"}
            )

        self.alerts.append(findings)
        return findings


def monitor_continuous(interval: int = 5, duration: Optional[int] = None) -> None:
    """Run continuous monitoring for *duration* seconds (or indefinitely)."""
    monitor = SystemMonitor(sampling_interval=1.0)
    profiler = PerformanceProfiler(monitor, window=60)
    end_time = time.time() + duration if duration else None

    print(f"Starting telemetry monitor (sampling every {interval}s, press Ctrl+C to stop)")
    try:
        while True:
            monitor.collect()
            profiler.analyze_window()
            if end_time and time.time() >= end_time:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")

    # Print summary
    print("\n=== Monitoring Summary ===")
    print(f"Samples collected: {len(monitor.metrics_history)}")
    print(f"Average CPU: {monitor.get_average()['cpu_percent']:.1f}%")
    print(f"Average Memory: {monitor.get_average()['memory_percent']:.1f}%")
    print(f"Peak CPU: {monitor.get_peak()['cpu_percent']:.1f}%")
    print(f"Peak Memory: {monitor.get_peak()['memory_percent']:.1f}%")


def generate_report(monitor: SystemMonitor, output: str = "stdout") -> None:
    """Generate a JSON performance report."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "samples": len(monitor.metrics_history),
        " averages": monitor.get_average(),
        "peak": monitor.get_peak(),
        "min": monitor.get_min(),
    }

    if output == "stdout":
        print(json.dumps(report, indent=2))
    else:
        with open(output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {output}")


def parse_args_cli() -> argparse.Namespace:
    """Parse command-line arguments for the telemetry daemon."""
    parser = argparse.ArgumentParser(
        description="Linux/OS resource monitor and performance profiler"
    )
    parser.add_argument(
        "--continuous", "-c", action="store_true", help="Run in continuous monitoring mode"
    )
    parser.add_argument(
        "--interval", type=int, default=5, help="Sampling interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--duration", type=int, default=None, help="Run for N seconds then exit"
    )
    parser.add_argument(
        "--report", "-r", type=str, default=None, help="Generate JSON report to file"
    )
    parser.add_argument(
        "--samples", type=int, default=None, help="Number of samples to collect"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args_cli()

    if args.continuous or args.samples is not None:
        samples = args.samples or None
        interval = args.interval
        monitor = SystemMonitor(sampling_interval=1.0)
        end_time = time.time() + args.duration if args.duration else None

        print(f"Collecting {samples or 'continuous'} samples every {interval}s")
        collected = 0
        try:
            while True:
                monitor.collect()
                collected += 1
                if args.samples and collected >= args.samples:
                    break
                if end_time and time.time() >= end_time:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped by user")

        # Generate and print report
        generate_report(monitor, output=args.report or "stdout")
    else:
        # Single collection mode
        metrics = SystemMonitor().collect()
        print(json.dumps(metrics, indent=2))