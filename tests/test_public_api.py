import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_package_and_cli_entrypoint_import():
    module = importlib.import_module("tg_agent_framework")
    cli_module = importlib.import_module("tg_agent_framework.cli.init")

    assert module.__name__ == "tg_agent_framework"
    assert callable(cli_module.main)
    assert hasattr(module, "MemoryScope")
    assert hasattr(module, "MemoryRecord")
    assert hasattr(module, "RuntimeStateBackend")
    assert hasattr(module, "SqliteLongTermMemory")
