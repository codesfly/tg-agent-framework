"""
Agent 框架基础配置 — 分层设计

BaseConfig: 最小必需配置（Telegram + LLM + 状态存储）
SSHConfigMixin: 可选 SSH 远程执行能力
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, set_key


def _normalize_state_namespace(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    compact = compact.strip("-.")
    return compact or "default"


def _resolve_project_dir(config_class: type | None = None) -> Path:
    if config_class is not None and config_class is not BaseConfig:
        module = sys.modules.get(config_class.__module__)
        module_file = getattr(module, "__file__", None)
        if module_file:
            return Path(module_file).resolve().parent

    current_file = Path(__file__).resolve()
    for frame_info in inspect.stack()[1:]:
        frame_file = frame_info.filename
        if not frame_file:
            continue
        candidate = Path(frame_file).resolve()
        if candidate == current_file:
            continue
        return candidate.parent
    return Path.cwd().resolve()


def _default_state_namespace() -> str:
    return _normalize_state_namespace(_resolve_project_dir().name)


def _default_env_path() -> Path:
    return _resolve_project_dir() / ".env"


@dataclass
class BaseConfig:
    """Agent 框架最小必需配置"""

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_allowed_users: list[int] = field(default_factory=list)

    # --- LLM (OpenAI 协议) ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_reasoning_effort: str = ""
    llm_request_timeout_seconds: float = 30.0
    foreground_operation_timeout_seconds: float = 45.0
    max_history_messages: int = 24

    # --- 状态存储 ---
    state_dir: str = field(
        default_factory=lambda: str(Path.home() / ".local" / "state" / "tg_agent")
    )
    state_namespace: str = field(default_factory=_default_state_namespace)
    env_path: Path = field(default_factory=_default_env_path)

    def validate(self) -> list[str]:
        """校验必填配置，返回错误列表。子类可 super().validate() + 扩展。"""
        errors: list[str] = []
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN 未设置")
        if not self.llm_api_key:
            errors.append("LLM_API_KEY 未设置")
        return errors


@dataclass
class SSHConfigMixin:
    """可选 Mixin: SSH 远程执行能力"""

    exec_mode: str = "local"  # "local" | "remote"
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key_path: str = ""

    @property
    def is_remote(self) -> bool:
        return self.exec_mode == "remote"

    def validate_ssh(self) -> list[str]:
        errors: list[str] = []
        if self.is_remote:
            if not self.ssh_host:
                errors.append("EXEC_MODE=remote 但 SSH_HOST 未设置")
            if not self.ssh_key_path:
                errors.append("EXEC_MODE=remote 但 SSH_KEY_PATH 未设置")
        return errors


def load_base_config(
    config_class: type = BaseConfig,
    env_path: str | Path | None = None,
    **overrides,
):
    """
    从 .env 文件和环境变量加载配置。

    支持传入自定义 Config 类（继承 BaseConfig），
    自动解析 BaseConfig 中已知的环境变量。
    """
    if env_path:
        resolved_env_path = Path(env_path).expanduser().resolve()
        project_dir = resolved_env_path.parent
    else:
        project_dir = _resolve_project_dir(config_class)
        resolved_env_path = project_dir / ".env"

    file_values = (
        {key: value for key, value in dotenv_values(resolved_env_path).items() if value is not None}
        if resolved_env_path.exists()
        else {}
    )

    def get_setting(name: str, default: str = "") -> str:
        value = os.getenv(name)
        if value is not None:
            return value
        return str(file_values.get(name, default))

    allowed_users_raw = get_setting("TELEGRAM_ALLOWED_USERS", "")
    allowed_users = [
        int(uid.strip()) for uid in allowed_users_raw.split(",") if uid.strip().isdigit()
    ]

    # BaseConfig 字段从环境变量加载
    base_kwargs = {
        "telegram_bot_token": get_setting("TELEGRAM_BOT_TOKEN", ""),
        "telegram_allowed_users": allowed_users,
        "llm_api_key": get_setting("LLM_API_KEY", ""),
        "llm_base_url": get_setting("LLM_BASE_URL", "https://api.openai.com/v1"),
        "llm_model": get_setting("LLM_MODEL", "gpt-4o"),
        "llm_reasoning_effort": get_setting("LLM_REASONING_EFFORT", ""),
        "llm_request_timeout_seconds": float(get_setting("LLM_REQUEST_TIMEOUT_SECONDS", "30")),
        "foreground_operation_timeout_seconds": float(
            get_setting("FOREGROUND_OPERATION_TIMEOUT_SECONDS", "45")
        ),
        "max_history_messages": int(get_setting("MAX_HISTORY_MESSAGES", "24")),
        "state_namespace": _normalize_state_namespace(project_dir.name),
        "env_path": resolved_env_path,
    }

    state_dir = get_setting("STATE_DIR", "")
    if state_dir:
        base_kwargs["state_dir"] = state_dir
    state_namespace = get_setting("STATE_NAMESPACE", "")
    if state_namespace:
        base_kwargs["state_namespace"] = _normalize_state_namespace(state_namespace)

    # SSHConfigMixin 字段
    if issubclass(config_class, SSHConfigMixin):
        base_kwargs.update(
            {
                "exec_mode": get_setting("EXEC_MODE", "local"),
                "ssh_host": get_setting("SSH_HOST", ""),
                "ssh_port": int(get_setting("SSH_PORT", "22")),
                "ssh_user": get_setting("SSH_USER", "root"),
                "ssh_key_path": get_setting("SSH_KEY_PATH", ""),
            }
        )

    # 用户覆盖
    base_kwargs.update(overrides)

    return config_class(**base_kwargs)


def persist_llm_settings(config: BaseConfig, model: str, base_url: str):
    """将 LLM 模型配置写回 .env，保证重启后仍然生效。"""
    env_path = config.env_path.expanduser()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.touch()
    set_key(str(env_path), "LLM_MODEL", model, quote_mode="never")
    set_key(str(env_path), "LLM_BASE_URL", base_url, quote_mode="never")
