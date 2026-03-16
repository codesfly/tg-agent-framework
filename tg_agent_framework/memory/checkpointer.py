"""
可持久化的 LangGraph Checkpointer - 使用 JSON 序列化（安全）
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from typing import Any, Sequence

from langgraph.checkpoint.memory import InMemorySaver

from tg_agent_framework.memory.runtime_store import RuntimeStateStore

logger = logging.getLogger(__name__)

CHECKPOINTER_KEY = "graph_checkpointer_v2"


class _CheckpointEncoder(json.JSONEncoder):
    """处理 LangGraph checkpoint 中的非标准 JSON 类型。"""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, bytes):
            return {"__bytes__": True, "data": obj.hex()}
        if isinstance(obj, tuple):
            return {"__tuple__": True, "data": list(obj)}
        if hasattr(obj, "isoformat"):
            return {"__datetime__": True, "data": obj.isoformat()}
        try:
            return super().default(obj)
        except TypeError:
            logger.debug("跳过不可序列化的对象: %s (类型: %s)", repr(obj)[:100], type(obj).__name__)
            return {"__unserializable__": True, "type": type(obj).__name__}


def _decode_hook(obj: dict) -> Any:
    if obj.get("__bytes__"):
        return bytes.fromhex(obj["data"])
    if obj.get("__tuple__"):
        return tuple(obj["data"])
    if obj.get("__datetime__"):
        from datetime import datetime
        try:
            return datetime.fromisoformat(obj["data"])
        except (ValueError, TypeError):
            return obj["data"]
    return obj


class PersistentMemorySaver(InMemorySaver):
    """在 InMemorySaver 基础上，定期把状态快照写入本地 sqlite（使用 JSON 序列化）。"""

    def __init__(self, state_store: RuntimeStateStore):
        super().__init__()
        self._state_store = state_store
        self._persist_lock = threading.Lock()
        self._restore()

    def put(self, config, checkpoint, metadata, new_versions):
        result = super().put(config, checkpoint, metadata, new_versions)
        self._persist()
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        super().put_writes(config, writes, task_id, task_path)
        self._persist()

    def delete_thread(self, thread_id: str) -> None:
        super().delete_thread(thread_id)
        self._persist()

    def delete_for_runs(self, run_ids: Sequence[str]) -> None:
        targets = set(run_ids)
        if not targets:
            return
        for thread_id, namespaces in list(self.storage.items()):
            for checkpoint_ns, checkpoints in list(namespaces.items()):
                for checkpoint_id in list(checkpoints.keys()):
                    if checkpoint_id in targets:
                        del checkpoints[checkpoint_id]
                        self.writes.pop((thread_id, checkpoint_ns, checkpoint_id), None)
                if not checkpoints:
                    del namespaces[checkpoint_ns]
            if not namespaces:
                del self.storage[thread_id]
        self._persist()

    def prune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        if strategy not in {"keep_latest", "delete"}:
            raise ValueError(f"不支持的剪枝策略: {strategy}")
        for thread_id in thread_ids:
            namespaces = self.storage.get(thread_id)
            if not namespaces:
                continue
            if strategy == "delete":
                self.delete_thread(thread_id)
                continue
            for checkpoint_ns, checkpoints in list(namespaces.items()):
                if len(checkpoints) <= 1:
                    continue
                keep_id = max(checkpoints.keys())
                for checkpoint_id in list(checkpoints.keys()):
                    if checkpoint_id == keep_id:
                        continue
                    del checkpoints[checkpoint_id]
                    self.writes.pop((thread_id, checkpoint_ns, checkpoint_id), None)
        self._persist()

    def _persist(self):
        try:
            payload = {
                "storage": {
                    thread_id: {
                        checkpoint_ns: dict(checkpoints)
                        for checkpoint_ns, checkpoints in namespaces.items()
                    }
                    for thread_id, namespaces in self.storage.items()
                },
                "writes": {
                    json.dumps(key, cls=_CheckpointEncoder): dict(value)
                    for key, value in self.writes.items()
                },
                "blobs": dict(self.blobs),
            }
            serialized = json.dumps(payload, cls=_CheckpointEncoder).encode("utf-8")
        except (TypeError, ValueError) as exc:
            logger.warning("Checkpointer 序列化失败，跳过持久化: %s", exc)
            return
        with self._persist_lock:
            self._state_store.save_blob(CHECKPOINTER_KEY, serialized)

    def _restore(self):
        raw = self._state_store.load_blob(CHECKPOINTER_KEY)
        if not raw:
            return
        try:
            restored = json.loads(raw.decode("utf-8"), object_hook=_decode_hook)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Checkpointer 反序列化失败，将从空状态启动: %s", exc)
            return
        storage = defaultdict(lambda: defaultdict(dict))
        for thread_id, namespaces in restored.get("storage", {}).items():
            ns_map = defaultdict(dict)
            for checkpoint_ns, checkpoints in namespaces.items():
                ns_map[checkpoint_ns] = dict(checkpoints)
            storage[thread_id] = ns_map
        writes = defaultdict(dict)
        for key_str, value in restored.get("writes", {}).items():
            try:
                key = tuple(json.loads(key_str))
            except (json.JSONDecodeError, TypeError):
                continue
            writes[key] = dict(value)
        self.storage = storage
        self.writes = writes
        self.blobs = restored.get("blobs", {})
