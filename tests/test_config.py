import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_load_base_config_uses_config_module_directory(tmp_path, monkeypatch):
    project_dir = tmp_path / "sample-agent"
    project_dir.mkdir()
    (project_dir / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=module-token\nLLM_API_KEY=module-key\n",
        encoding="utf-8",
    )
    (project_dir / "app_config.py").write_text(
        "\n".join(
            [
                "from dataclasses import dataclass",
                "from tg_agent_framework.config import BaseConfig, load_base_config",
                "",
                "@dataclass",
                "class AppConfig(BaseConfig):",
                "    pass",
                "",
                "def load():",
                "    return load_base_config(AppConfig)",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(project_dir))
    monkeypatch.chdir(tmp_path)

    module = importlib.import_module("app_config")
    config = module.load()

    assert config.telegram_bot_token == "module-token"
    assert config.env_path == project_dir / ".env"
    assert config.state_namespace == "sample-agent"


def test_load_base_config_uses_caller_file_for_base_config(tmp_path, monkeypatch):
    project_dir = tmp_path / "caller-agent"
    project_dir.mkdir()
    (project_dir / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=caller-token\nLLM_API_KEY=caller-key\n",
        encoding="utf-8",
    )
    (project_dir / "entrypoint.py").write_text(
        "\n".join(
            [
                "from tg_agent_framework.config import BaseConfig, load_base_config",
                "",
                "def load():",
                "    return load_base_config(BaseConfig)",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(project_dir))
    monkeypatch.chdir(tmp_path)

    module = importlib.import_module("entrypoint")
    config = module.load()

    assert config.telegram_bot_token == "caller-token"
    assert config.env_path == project_dir / ".env"
    assert config.state_namespace == "caller-agent"
