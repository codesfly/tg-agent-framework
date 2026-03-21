"""
可持久化的 LangGraph Checkpointer - 使用 JSON 序列化（安全）
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Sequence

from langgraph.checkpoint.memory import InMemorySaver

from tg_agent_framework.memory.runtime_backend import RuntimeStateBackend

logger = logging.getLogger(__name__)

CHECKPOINTER_KEY = "graph_checkpointer_v2"
CHECKPOINTER_FORMAT_VERSION = 1
CHECKPOINTER_CORRUPT_PREFIX = f"{CHECKPOINTER_KEY}_corrupt_"


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
    """在 InMemorySaver 基础上，定期把状态快照写入本地 sqlite（使用 JSON 序列化）。

    写入采用防抖策略：多次快速 put() 只触发一次磁盘写入（延迟 2 秒合并）。
    """

    DEBOUNCE_SECONDS = 2.0

    def __init__(self, state_store: RuntimeStateBackend):
        super().__init__()
        self._state_store = state_store
        self._persist_lock = threading.Lock()
        self._dirty = False
        self._debounce_timer: threading.Timer | None = None
        self._restore()

    def put(self, config, checkpoint, metadata, new_versions):
        result = super().put(config, checkpoint, metadata, new_versions)
        self._schedule_persist()
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        super().put_writes(config, writes, task_id, task_path)
        self._schedule_persist()

    def delete_thread(self, thread_id: str) -> None:
        super().delete_thread(thread_id)
        self._schedule_persist()

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
        self._schedule_persist()

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
        self._schedule_persist()

    def _schedule_persist(self):
        """防抖写入：标记脏数据后延迟 2 秒合并写入。"""
        with self._persist_lock:
            self._dirty = True
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                self.DEBOUNCE_SECONDS, self._do_persist
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def flush(self):
        """立即将脏数据写入磁盘（用于优雅关闭）。"""
        with self._persist_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._dirty:
            self._do_persist()

    def _do_persist(self):
        """实际执行序列化 + 磁盘写入。"""
        if not self._dirty:
            return
        self._dirty = False
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
            payload_json = json.dumps(payload, cls=_CheckpointEncoder, sort_keys=True)
            envelope = {
                "format_version": CHECKPOINTER_FORMAT_VERSION,
                "checksum": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                "payload": payload,
            }
            serialized = json.dumps(envelope, cls=_CheckpointEncoder).encode("utf-8")
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
            restored = self._decode_persisted_payload(raw)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Checkpointer 反序列化失败，已隔离损坏快照并从空状态启动: %s", exc)
            self._quarantine_corrupt_payload(raw)
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

    def _decode_persisted_payload(self, raw: bytes) -> dict[str, Any]:
        restored = json.loads(raw.decode("utf-8"), object_hook=_decode_hook)
        if not isinstance(restored, dict):
            raise ValueError("checkpoint payload 必须是对象")
        if {"format_version", "checksum", "payload"} <= restored.keys():
            if restored["format_version"] != CHECKPOINTER_FORMAT_VERSION:
                raise ValueError(f"不支持的 checkpoint 版本: {restored['format_version']}")
            payload = restored["payload"]
            payload_json = json.dumps(payload, cls=_CheckpointEncoder, sort_keys=True)
            checksum = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            if checksum != restored["checksum"]:
                raise ValueError("checkpoint checksum 校验失败")
            if not isinstance(payload, dict):
                raise ValueError("checkpoint payload 必须是对象")
            return payload
        return restored

    def _quarantine_corrupt_payload(self, raw: bytes) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        key = f"{CHECKPOINTER_CORRUPT_PREFIX}{timestamp}"
        suffix = 0
        while self._state_store.load_blob(key) is not None:
            suffix += 1
            key = f"{CHECKPOINTER_CORRUPT_PREFIX}{timestamp}_{suffix}"
        self._state_store.save_blob(key, raw)
        self._state_store.delete_blob(CHECKPOINTER_KEY)
