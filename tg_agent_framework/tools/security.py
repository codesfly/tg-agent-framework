"""
Shell 命令安全校验 — 白名单 + 参数黑名单

提供通用的命令验证机制，防止 LLM 通过 Agent 执行任意 shell 命令。
"""

from __future__ import annotations

import logging
import os
import shlex
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 允许的命令白名单（子类可扩展）
ALLOWED_SHELL_COMMANDS: set[str] = {
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "wc",
    "df",
    "du",
    "free",
    "uptime",
    "top",
    "ps",
    "netstat",
    "ss",
    "curl",
    "ping",
    "dig",
    "nslookup",
    "git",
    "find",
    "date",
    "whoami",
    "hostname",
    "uname",
    "which",
    "file",
    "stat",
    "lsof",
    "journalctl",
    "systemctl",
    "pm2",
}

READ_ONLY_SUBCOMMANDS: dict[str, set[str]] = {
    "git": {
        "describe",
        "diff",
        "grep",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
    },
    "pm2": {
        "describe",
        "jlist",
        "list",
        "prettylist",
        "show",
        "status",
    },
    "systemctl": {
        "cat",
        "is-active",
        "is-enabled",
        "list-unit-files",
        "list-units",
        "show",
        "status",
    },
}

FIND_DANGEROUS_ARGS: set[str] = {
    "-delete",
    "-exec",
    "-execdir",
    "-fprint",
    "-fprintf",
    "-fprint0",
    "-ok",
    "-okdir",
}

GIT_GLOBAL_OPTIONS_WITH_VALUES: set[str] = {
    "-C",
    "-c",
    "--git-dir",
    "--namespace",
    "--work-tree",
}

# 全局阻止的 shell 元字符和危险 pattern
BLOCKED_SHELL_PATTERNS: set[str] = {
    "&&",
    "||",
    ">>",
    ">",
    "|",
    ";",
    "$(",
    "`",
    "\n",
    "\\n",
    "rm ",
    "rm\t",
    "mkfs",
    "dd ",
    "chmod",
    "chown",
    "useradd",
    "userdel",
    "passwd",
    "sudo ",
    "su ",
    "/etc/shadow",
    "/etc/passwd",
}

# git 危险参数
GIT_DANGEROUS_ARGS: set[str] = {
    "--output",
    "-o",
    "--upload-pack",
    "--receive-pack",
    "--exec",
    "--exec-path",
}

# curl 危险参数
CURL_DANGEROUS_ARGS: set[str] = {
    "-X",
    "--request",
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "-F",
    "--form",
    "-T",
    "--upload-file",
    "-o",
    "--output",
    "-O",
    "--remote-name",
}

CURL_OPTIONS_WITH_VALUES: set[str] = {
    "-A",
    "--connect-timeout",
    "-e",
    "--header",
    "-H",
    "--interface",
    "--max-time",
    "-m",
    "--proxy",
    "--retry",
    "--retry-delay",
    "--url",
    "-u",
    "--user",
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
        urls = _extract_curl_urls(parts[1:])
        if not urls:
            return "curl 缺少目标地址"
        for url in urls:
            if not _is_local_url(url):
                return "curl 仅允许访问 localhost/127.0.0.1"

    if base_cmd == "find":
        for arg in parts[1:]:
            if arg in FIND_DANGEROUS_ARGS:
                return f"find 参数 '{arg}' 被禁止"

    if base_cmd in READ_ONLY_SUBCOMMANDS:
        subcommand = _extract_subcommand(base_cmd, parts)
        if not subcommand:
            return f"命令 '{base_cmd}' 缺少子命令"
        if subcommand not in READ_ONLY_SUBCOMMANDS[base_cmd]:
            return f"{base_cmd} 子命令 '{subcommand}' 不在只读白名单中"

    return None


def _extract_subcommand(base_cmd: str, parts: list[str]) -> str | None:
    skip_next = False
    for arg in parts[1:]:
        if skip_next:
            skip_next = False
            continue
        if base_cmd == "git" and arg in GIT_GLOBAL_OPTIONS_WITH_VALUES:
            skip_next = True
            continue
        if arg.startswith("--") and "=" in arg:
            continue
        if arg.startswith("-"):
            continue
        return arg
    return None


def _is_local_url(value: str) -> bool:
    candidate = value if "://" in value else f"http://{value}"
    parsed = urlparse(candidate)
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _extract_curl_urls(args: list[str]) -> list[str]:
    urls: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in CURL_OPTIONS_WITH_VALUES:
            skip_next = True
            continue
        if arg.startswith("--") and "=" in arg:
            option_name, value = arg.split("=", 1)
            if option_name in CURL_OPTIONS_WITH_VALUES:
                if option_name == "--url":
                    urls.append(value)
                continue
        if arg.startswith("-"):
            continue
        urls.append(arg)
    return urls
