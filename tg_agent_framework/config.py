"""
Agent 框架基础配置 — 分层设计

BaseConfig: 最小必需配置（Telegram + LLM + 状态存储）
SSHConfigMixin: 可选 SSH 远程执行能力
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv, set_key


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

    # --- 状态存储 ---
    state_dir: str = field(
        default_factory=lambda: str(Path.home() / ".local" / "state" / "tg_agent")
    )
    env_path: Path = field(default_factory=lambda: Path(".env"))

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
    resolved_env_path = Path(env_path).expanduser() if env_path else Path.cwd() / ".env"
    if env_path:
        load_dotenv(resolved_env_path)
    else:
        load_dotenv()

    allowed_users_raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    allowed_users = [
        int(uid.strip())
        for uid in allowed_users_raw.split(",")
        if uid.strip().isdigit()
    ]

    # BaseConfig 字段从环境变量加载
    base_kwargs = {
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_allowed_users": allowed_users,
        "llm_api_key": os.getenv("LLM_API_KEY", ""),
        "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        "llm_model": os.getenv("LLM_MODEL", "gpt-4o"),
        "llm_reasoning_effort": os.getenv("LLM_REASONING_EFFORT", ""),
        "llm_request_timeout_seconds": float(
            os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30")
        ),
        "foreground_operation_timeout_seconds": float(
            os.getenv("FOREGROUND_OPERATION_TIMEOUT_SECONDS", "45")
        ),
        "env_path": resolved_env_path,
    }

    state_dir = os.getenv("STATE_DIR")
    if state_dir:
        base_kwargs["state_dir"] = state_dir

    # SSHConfigMixin 字段
    if issubclass(config_class, SSHConfigMixin):
        base_kwargs.update({
            "exec_mode": os.getenv("EXEC_MODE", "local"),
            "ssh_host": os.getenv("SSH_HOST", ""),
            "ssh_port": int(os.getenv("SSH_PORT", "22")),
            "ssh_user": os.getenv("SSH_USER", "root"),
            "ssh_key_path": os.getenv("SSH_KEY_PATH", ""),
        })

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
