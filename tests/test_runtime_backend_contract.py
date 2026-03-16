import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.memory.checkpointer import PersistentMemorySaver
from tg_agent_framework.memory.runtime_backend import RuntimeStateBackend
from tg_agent_framework.memory.runtime_store import RuntimeStateStore


class FakeRuntimeBackend:
    def __init__(self):
        self._blobs: dict[str, bytes] = {}

    def load_blob(self, key: str) -> bytes | None:
        return self._blobs.get(key)

    def save_blob(self, key: str, value: bytes) -> None:
        self._blobs[key] = value

    def delete_blob(self, key: str) -> None:
        self._blobs.pop(key, None)

    def list_blob_keys(self, prefix: str = "") -> list[str]:
        return [key for key in sorted(self._blobs) if key.startswith(prefix)]


def test_runtime_state_store_satisfies_runtime_backend_contract(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")

    assert isinstance(store, RuntimeStateBackend)


def test_checkpointer_accepts_runtime_backend_contract():
    saver = PersistentMemorySaver(FakeRuntimeBackend())

    assert saver is not None
