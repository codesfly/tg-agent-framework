import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.memory.checkpointer import (
    CHECKPOINTER_CORRUPT_PREFIX,
    CHECKPOINTER_KEY,
    PersistentMemorySaver,
)
from tg_agent_framework.memory.runtime_store import SCHEMA_VERSION, RuntimeStateStore


def test_runtime_store_bootstraps_schema_version_and_integrity(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")

    store.init_schema()

    assert store.get_schema_version() == SCHEMA_VERSION
    assert store.validate_integrity() is True


def test_corrupt_checkpoint_is_quarantined_on_restore(tmp_path):
    store = RuntimeStateStore(tmp_path / "state")
    store.init_schema()
    store.save_blob(CHECKPOINTER_KEY, b"{not-json")

    PersistentMemorySaver(store)

    assert store.load_blob(CHECKPOINTER_KEY) is None
    quarantined_keys = store.list_blob_keys(CHECKPOINTER_CORRUPT_PREFIX)
    assert len(quarantined_keys) == 1
    assert store.load_blob(quarantined_keys[0]) == b"{not-json"
