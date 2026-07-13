"""Static smoke checks for auto-pause container integration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_image_installs_packet_detector_with_raw_capability():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "knockd" in dockerfile
    assert "setcap cap_net_raw=ep" in dockerfile
    assert "scripts/palworld_control.py /usr/local/bin/palworld-control" in dockerfile


def test_compose_grants_net_raw_and_exposes_interface_setting():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "NET_RAW" in compose
    assert "IDLE_PAUSE_INTERFACE" in compose

    example = (
        ROOT / "docker-compose.idle-pause.example.yml"
    ).read_text(encoding="utf-8")
    assert "IDLE_RESTART_MODE=pause" in example
    assert "NET_RAW" in example


def test_helm_pause_mode_adds_net_raw_and_runtime_interface():
    deployment = (
        ROOT / "charts/palworld-server/templates/deployment.yaml"
    ).read_text(encoding="utf-8")
    values = (
        ROOT / "charts/palworld-server/values.yaml"
    ).read_text(encoding="utf-8")
    assert 'eq .Values.monitoring.idleRestart.mode "pause"' in deployment
    assert "NET_RAW" in deployment
    assert "IDLE_PAUSE_INTERFACE" in deployment
    assert 'interface: "eth0"' in values

