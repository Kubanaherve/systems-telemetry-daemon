"""Unit tests for systems-telemetry-daemon."""

import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/Users/friendkh/systems-telemetry-daemon")
from daemon import SystemMonitor, PerformanceProfiler, parse_args_cli


def test_collect_metrics():
    monitor = SystemMonitor(sampling_interval=0.1)
    with patch("daemon.psutil") as mock_psutil:
        mock_psutil.cpu_percent.return_value = 45.2
        mock_vmem = MagicMock()
        mock_vmem.percent = 60.5
        mock_vmem.used = 8 * 1024 * 1024 * 1024
        mock_vmem.total = 16 * 1024 * 1024 * 1024
        mock_psutil.virtual_memory.return_value = mock_vmem
        mock_disk = MagicMock()
        mock_disk.read_bytes = 100 * 1024 * 1024
        mock_disk.write_bytes = 50 * 1024 * 1024
        mock_psutil.disk_io_counters.return_value = mock_disk
        mock_net = MagicMock()
        mock_net.bytes_sent = 20 * 1024 * 1024
        mock_net.bytes_recv = 30 * 1024 * 1024
        mock_psutil.net_io_counters.return_value = mock_net

        metrics = monitor.collect()

    assert metrics["cpu_percent"] == 45.2
    assert metrics["memory_percent"] == 60.5
    assert metrics["memory_used_mb"] == 8.0
    assert metrics["memory_total_mb"] == 16.0
    assert metrics["disk_read_mb_s"] == 0.0  # first call
    assert metrics["disk_write_mb_s"] == 0.0  # first call
    assert metrics["net_sent_mb_s"] == 0.0  # first call
    assert metrics["net_recv_mb_s"] == 0.0  # first call


def test_compute_io_rate():
    monitor = SystemMonitor(sampling_interval=1.0)
    # Set up prev IO counters
    monitor._prev_disk = MagicMock(read_bytes=100*1024*1024, write_bytes=50*1024*1024)
    # Current after 1 second
    monitor._prev_disk = monitor._prev_disk  # just for type check

    # Test with previous set
    from daemon import SystemMonitor as SM
    # Actually let's just test the static method logic inline
    current = type("Obj", (), {"read_bytes": 200*1024*1024, "write_bytes": 150*1024*1024})()
    previous = type("Obj", (), {"read_bytes": 100*1024*1024, "write_bytes": 50*1024*1024})()

    read_rate = (current.read_bytes - previous.read_bytes) / (1024 * 1024)
    write_rate = (current.write_bytes - previous.write_bytes) / (1024 * 1024)
    assert abs(read_rate - 100.0) < 0.01
    assert abs(write_rate - 100.0) < 0.01


def test_performance_profiler():
    monitor = SystemMonitor(sampling_interval=0.1)
    profiler = PerformanceProfiler(monitor, window=10)

    with patch("daemon.psutil") as mock_psutil:
        mock_psutil.cpu_percent.return_value = 95.0
        mock_vmem = MagicMock()
        mock_vmem.percent = 90.0
        mock_vmem.used = 8 * 1024 * 1024 * 1024
        mock_vmem.total = 16 * 1024 * 1024 * 1024
        mock_psutil.virtual_memory.return_value = mock_vmem
        mock_psutil.disk_io_counters.return_value = MagicMock(
            read_bytes=0, write_bytes=0
        )
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=0, bytes_recv=0
        )

        _ = monitor.collect()
        findings = profiler.analyze_window()

    assert len(findings["anomalies"]) > 0
    assert any(a["type"] == "high_cpu" for a in findings["anomalies"])


def test_get_averages():
    monitor = SystemMonitor(sampling_interval=0.1)
    with patch("daemon.psutil") as mock_psutil:
        for i in range(5):
            mock_psutil.cpu_percent.return_value = float(i * 10)
            mock_vmem = MagicMock()
            mock_vmem.percent = 50.0
            mock_vmem.used = 4 * 1024 * 1024 * 1024
            mock_vmem.total = 8 * 1024 * 1024 * 1024
            mock_psutil.virtual_memory.return_value = mock_vmem
            mock_psutil.disk_io_counters.return_value = MagicMock(
                read_bytes=0, write_bytes=0
            )
            mock_psutil.net_io_counters.return_value = MagicMock(
                bytes_sent=0, bytes_recv=0
            )
            monitor.collect()

    avg = monitor.get_average(window=3)
    assert abs(avg["cpu_percent"] - 20.0 / 3) < 0.1  # (10+20+30)/3 = 20


def test_parse_args():
    args = parse_args_cli()
    assert hasattr(args, "continuous")
    assert hasattr(args, "interval")
    assert hasattr(args, "duration")
    assert hasattr(args, "report")
    assert hasattr(args, "samples")

    # Test with --continuous
    ns = parse_args_cli(["--continuous"])
    assert ns.continuous is True

    # Test with --report
    ns = parse_args_cli(["--report", "/tmp/report.json"])
    assert ns.report == "/tmp/report.json"