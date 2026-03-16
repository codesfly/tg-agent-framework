import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tg_agent_framework.tools.security import validate_shell_command


def test_rejects_destructive_shell_commands():
    commands = [
        "systemctl restart nginx",
        "pm2 delete all",
        "find /tmp -delete",
        "git clean -fd",
        "git branch -D stale-branch",
        "git remote remove origin",
    ]

    for command in commands:
        assert validate_shell_command(command) is not None


def test_allows_read_only_commands():
    assert validate_shell_command("systemctl status nginx") is None
    assert validate_shell_command("git status --short") is None
    assert validate_shell_command("curl --max-time 5 http://localhost:8080/healthz") is None
