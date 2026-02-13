"""Temporary UI export regression test.

This module is intentionally pytest-friendly (no top-level execution side effects).
It validates that UI JSON endpoints can be queried from a minimal coordinator.
"""

import sys

sys.path.append('.')

from agents.ui_agent import UIAgent


# prevent starting background feed worker in constructor for test
UIAgent._feed_worker = lambda self: None


class DummyCfg:
    pass


class DummyCoordinator:
    def __init__(self):
        self.cfg = DummyCfg()
        # sensible defaults used by UIAgent
        self.cfg.feed_buffer_trades = 500
        self.cfg.feed_buffer_logs = 1000
        self.cfg.allowed_ips = []
        self.agents = {}
        self.data_cache = {}
        self.running = True

    def get_shared_data(self, key):
        return self.data_cache.get(key)

    def share_data(self, key, value):
        self.data_cache[key] = value


def test_ui_json_endpoints_smoke():
    """Ensure core JSON endpoints respond in a minimal environment."""
    dc = DummyCoordinator()
    ui = UIAgent(coordinator=dc)

    c = ui.app.test_client()

    r_metrics = c.get('/metrics.json')
    assert r_metrics.status_code == 200
    assert isinstance(r_metrics.get_json(), dict)

    r_tape = c.get('/tape.json')
    assert r_tape.status_code == 200
    tape_payload = r_tape.get_json()
    assert isinstance(tape_payload, dict)
    assert 'trades' in tape_payload

    r_audit = c.get('/audit.json')
    assert r_audit.status_code == 200
    payload = r_audit.get_json()
    assert isinstance(payload, dict)
    assert 'entries' in payload or 'rows' in payload
