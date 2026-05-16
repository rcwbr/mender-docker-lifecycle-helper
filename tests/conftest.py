import pytest
import sys
from pathlib import Path

# Add fixtures directory to path so pytest can discover fixtures
fixtures_path = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(fixtures_path))

from custom_docker_daemon import custom_docker_daemon
from mender_server import mender_server, mender_server_resources
from mender_client import mender_client


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store test results on the item to check for failures in fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{call.when}", rep)
