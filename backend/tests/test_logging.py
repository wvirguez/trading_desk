import json

import pytest
import structlog

from app.core.logging import configure_logging


def test_configure_logging_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()

    structlog.get_logger().info("ingesta", symbol="BTC/USDT", fetched=72)

    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "ingesta"
    assert data["symbol"] == "BTC/USDT"
    assert data["fetched"] == 72
    assert data["level"] == "info"
    assert "timestamp" in data
