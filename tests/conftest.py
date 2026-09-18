import os
import tempfile
import atexit

import pytest

# Never use production credentials, mounts or inference from the test suite.
_sandbox = tempfile.TemporaryDirectory(prefix="runtime-tests-")
atexit.register(_sandbox.cleanup)
for _name in ("OKF_DATA_ROOT", "SESSION_ROOT", "SIMULATOR_ROOT", "TOOL_REGISTRY_ROOT"):
    os.environ[_name] = f"{_sandbox.name}/{_name}"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:1/v1"
os.environ["LLM_API_KEY"] = "synthetic-test-only"
os.environ["LLM_MODEL"] = "synthetic"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LLM_PROXY_URL", None)
for _connection in ("LOVABLE", "EXTERNAL"):
    for _field in ("BASE_URL", "API_KEY", "MODEL", "PROXY_URL", "READ_TIMEOUT_SECONDS"):
        os.environ.pop(f"LLM_{_connection}_{_field}", None)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for name in ("OKF_DATA_ROOT", "SESSION_ROOT", "SIMULATOR_ROOT"):
        monkeypatch.setenv(name, str(tmp_path / name))
    from simple_agent.services.okf_store import PersistentOKFStore
    from simple_agent.tools import okf_tools

    store = PersistentOKFStore()
    monkeypatch.setattr(okf_tools, "store", store)
    return store


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
