"""
Shell 命令安全校验 — 白名单 + 参数黑名单

提供通用的命令验证机制，防止 LLM 通过 Agent 执行任意 shell 命令。
"""

from __future__ import annotations

import logging
import os
import shlex

logger = logging.getLogger(__name__)

# 允许的命令白名单（子类可扩展）
ALLOWED_SHELL_COMMANDS: set[str] = {
    "ls", "cat", "head", "tail", "grep", "wc", "df", "du",
    "free", "uptime", "top", "ps", "netstat", "ss", "curl",
    "ping", "dig", "nslookup", "git", "find", "date", "whoami",
    "hostname", "uname", "which", "file", "stat", "lsof",
    "journalctl", "systemctl", "pm2",
}

# 全局阻止的 shell 元字符和危险 pattern
BLOCKED_SHELL_PATTERNS: set[str] = {
    "&&", "||", ">>", ">", "|", ";", "$(",
    "`", "$(", "\n", "\\n",
    "rm ", "rm\t", "mkfs", "dd ",
    "chmod", "chown", "useradd", "userdel",
    "passwd", "sudo ", "su ",
    "/etc/shadow", "/etc/passwd",
}

# git 危险参数
GIT_DANGEROUS_ARGS: set[str] = {
    "--output", "-o",
    "--upload-pack", "--receive-pack",
    "--exec", "--exec-path",
}

# curl 危险参数
CURL_DANGEROUS_ARGS: set[str] = {
    "-X", "--request",
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode",
    "-F", "--form",
    "-T", "--upload-file",
    "-o", "--output",
    "-O", "--remote-name",
}


def validate_shell_command(command: str) -> str | None:
    """
    校验 shell 命令是否安全。

    返回:
        None — 命令安全，允许执行
        str  — 拒绝原因

    用法:
        reason = validate_shell_command(cmd)
        if reason:
            return f"命令被拒绝: {reason}"
    """
    for pattern in BLOCKED_SHELL_PATTERNS:
        if pattern in command:
            return f"包含被禁止的 pattern: {pattern!r}"

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"命令解析失败: {e}"

    if not parts:
        return "空命令"

    base_cmd = os.path.basename(parts[0])

    if base_cmd not in ALLOWED_SHELL_COMMANDS:
        return (
            f"命令 '{base_cmd}' 不在白名单中。"
            f"允许的命令: {', '.join(sorted(ALLOWED_SHELL_COMMANDS))}"
        )

    # git 参数黑名单
    if base_cmd == "git":
        for arg in parts[1:]:
            arg_name = arg.split("=")[0] if "=" in arg else arg
            if arg_name.lower() in GIT_DANGEROUS_ARGS:
                return f"git 参数 '{arg_name}' 被禁止"

    # curl 限制
    if base_cmd == "curl":
        for arg in parts[1:]:
            arg_name = arg.split("=")[0] if "=" in arg else arg
            if arg_name in CURL_DANGEROUS_ARGS:
                return f"curl 仅允许 GET 请求，参数 '{arg_name}' 被禁止"
        # 限制只能访问 localhost
        for arg in parts[1:]:
            if not arg.startswith("-"):
                if "localhost" not in arg and "127.0.0.1" not in arg:
                    return f"curl 仅允许访问 localhost/127.0.0.1"

    return None
