"""
tg-agent init — 一键生成新 Agent 项目脚手架

用法:
    python -m tg_agent_framework.cli.init my-trading-agent
    python -m tg_agent_framework.cli.init my-monitor-agent --name "监控Agent"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ═══════════════════════════════════════════
#  项目模板
# ═══════════════════════════════════════════

PYPROJECT_TEMPLATE = """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{slug}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"

dependencies = [
    "tg-agent-framework",
]

[project.optional-dependencies]
dev = [
    "ruff>=0.11",
    "mypy>=1.10",
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.setuptools.packages.find]
include = ["*"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
warn_unused_configs = true
show_error_codes = true
"""

ENV_EXAMPLE_TEMPLATE = """# === Telegram ===
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_ALLOWED_USERS=123456789

# === LLM (OpenAI 协议) ===
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# === 可选: 状态命名空间（同机多 Bot 时建议显式设置） ===
# STATE_NAMESPACE=my-agent

# === 可选: SSH 远程执行 ===
# EXEC_MODE=remote
# SSH_HOST=1.2.3.4
# SSH_PORT=22
# SSH_USER=root
# SSH_KEY_PATH=~/.ssh/id_rsa
"""

CONFIG_TEMPLATE = '''"""
{name} 配置
"""

from dataclasses import dataclass

from tg_agent_framework import BaseConfig, load_base_config


@dataclass
class AgentConfig(BaseConfig):
    """自定义配置 — 在这里添加你的业务字段"""
    # 示例: api_endpoint: str = "http://localhost:3000"
    pass


def load_config() -> AgentConfig:
    return load_base_config(AgentConfig)
'''

TOOLS_INIT_TEMPLATE = '''"""
{name} 工具定义

在这里定义你的 Agent 工具。使用 @tool_registry.register() 装饰器自动注册。

工具分两类:
- SAFE:      只读/无副作用，直接执行
- DANGEROUS: 有副作用（修改数据、重启服务等），需用户在 Telegram 中确认后执行
"""

from langchain_core.tools import tool

from tg_agent_framework import tool_registry, ToolCategory


@tool_registry.register(category=ToolCategory.SAFE)
@tool
async def hello(name: str) -> str:
    """向用户打招呼 — 这是一个示例工具，请替换为你的实际功能"""
    return f"你好 {{name}}! 👋 我是 {name}。"


# @tool_registry.register(category=ToolCategory.DANGEROUS)
# @tool
# async def dangerous_example(target: str) -> str:
#     """示例危险工具 — 执行前会弹出确认按钮"""
#     return f"已对 {{target}} 执行操作"
'''

PROMPTS_TEMPLATE = '''"""
{name} System Prompt

这是 Agent 的"人格"和"能力边界"定义。
LLM 会严格遵循这个 prompt 来决定如何使用工具。
"""

SYSTEM_PROMPT = """你是 {name}，一个专业的 AI 助手。

## 你的能力
- 你可以通过工具执行各种操作
- 你会用清晰、专业的中文回应用户

## 工具使用原则
1. 先理解用户意图，再选择合适的工具
2. 如果不确定，先询问用户
3. 执行完成后，用简洁的语言总结结果

## 注意事项
- 遇到错误时，先尝试诊断原因再汇报
- 不要编造数据，只报告工具返回的真实结果
"""
'''

MAIN_TEMPLATE = '''"""
{name} 入口
"""

import asyncio
import logging
import sys

from aiogram.types import BotCommand

from tg_agent_framework import (
    AgentBot,
    QuickAction,
    RuntimeStateStore,
    build_graph,
    tool_registry,
)

from config import AgentConfig, load_config
from prompts import SYSTEM_PROMPT

# 触发工具注册（导入即可）
import tools  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("{slug}")


class MyBot(AgentBot):
    """{name} Telegram Bot"""

    def get_start_message(self) -> str:
        return (
            "🤖 **{name}** 已就绪！\\n\\n"
            "直接发送自然语言指令开始交互。\\n\\n"
            "**内置命令:**\\n"
            "• `/reset` - 重置对话\\n"
            "• `/stop` - 取消当前操作\\n"
            "• `/model` - 查看/切换 LLM 模型\\n"
        )

    def get_quick_actions(self) -> list[QuickAction]:
        # 在这里添加快捷按钮
        return [
            # QuickAction("📊 状态", "quick:status", row=0),
        ]

    def get_bot_commands(self) -> list[BotCommand]:
        return [
            BotCommand(command="start", description="启动对话"),
            BotCommand(command="reset", description="重置对话上下文"),
            BotCommand(command="stop", description="取消当前执行"),
            BotCommand(command="model", description="查看/切换 LLM 模型"),
        ]


async def main():
    config = load_config()
    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("配置错误: %s", err)
        sys.exit(1)

    state_store = RuntimeStateStore.from_config(config)
    state_store.init_schema()

    def graph_factory(current_config: AgentConfig, current_state_store: RuntimeStateStore):
        return build_graph(
            config=current_config,
            state_store=current_state_store,
            system_prompt=SYSTEM_PROMPT,
        )

    graph, _ = graph_factory(config, state_store)

    bot = MyBot(
        config=config,
        graph=graph,
        state_store=state_store,
        dangerous_tool_names=tool_registry.dangerous_tool_names,
        graph_factory=graph_factory,
    )

    logger.info("🤖 {name} 启动中...")
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
'''

AGENT_RULES_TEMPLATE = """# {name} — AI 编码规则

## 项目结构

```
{slug}/
├── config.py     # 配置（继承 BaseConfig）
├── main.py       # 启动入口（继承 AgentBot）
├── prompts.py    # System Prompt（Agent 人格）
├── tools/        # 工具函数（@tool_registry.register）
│   └── __init__.py
├── .env          # 环境变量（密钥等）
└── .env.example  # 环境变量模板
```

## 核心概念

### 开发新工具
在 `tools/__init__.py` 中添加：

```python
from langchain_core.tools import tool
from tg_agent_framework import tool_registry, ToolCategory

@tool_registry.register(category=ToolCategory.SAFE)
@tool
async def my_tool(param: str) -> str:
    \"\"\"工具描述 — LLM 会根据这个描述决定何时调用\"\"\"
    return "结果"
```

- `SAFE`: 直接执行（只读操作）
- `DANGEROUS`: 需要用户在 Telegram 中确认后执行（有副作用的操作）

### 修改 Agent 行为
- **人格/指令**: 编辑 `prompts.py` 中的 `SYSTEM_PROMPT`
- **欢迎文案**: 编辑 `main.py` 中 `MyBot.get_start_message()`
- **快捷按钮**: 编辑 `main.py` 中 `MyBot.get_quick_actions()`
- **新配置项**: 在 `config.py` 的 `AgentConfig` 类中添加字段

### 框架自动处理
- Telegram 消息收发与格式化（Markdown → HTML）
- LLM 推理 + 工具调用编排（LangGraph）
- 前台操作进度追踪与心跳
- 危险操作确认/拒绝流程
- 超时自动重置对话上下文
- 状态持久化（SQLite）

## 工具函数规范
1. 必须是 `async def`
2. 必须有**清晰的 docstring**（LLM 靠 docstring 理解工具用途）
3. 参数和返回值类型标注完整
4. 返回 `str` 类型（LLM 消费的描述文本）
5. 异常应被 catch 并返回友好的错误信息

## 运行
```bash
cp .env.example .env  # 填写你的密钥
pip install -e .
python main.py
```
"""

GITIGNORE_TEMPLATE = """__pycache__/
*.pyc
.env
*.sqlite3
.venv/
dist/
*.egg-info/
"""

README_TEMPLATE = """# {name}

> 基于 [tg-agent-framework](https://github.com/your-org/tg-agent-framework) 构建

## 快速开始

```bash
cp .env.example .env   # 填写 Telegram Token 和 LLM API Key
pip install -e .
python main.py
```

## 开发工具

在 `tools/__init__.py` 中添加新工具，框架自动注册：

```python
@tool_registry.register(category=ToolCategory.SAFE)
@tool
async def my_tool(param: str) -> str:
    \"\"\"工具描述\"\"\"
    return "结果"
```

## 项目结构

| 文件 | 用途 |
|:--|:--|
| `config.py` | 自定义配置 |
| `main.py` | Bot 启动入口 |
| `prompts.py` | Agent 人格定义 |
| `tools/` | 工具函数 |
"""


# ═══════════════════════════════════════════
#  脚手架逻辑
# ═══════════════════════════════════════════


def create_project(
    project_dir: str,
    name: str | None = None,
    description: str = "",
):
    """生成新 Agent 项目"""
    project_path = Path(project_dir).resolve()
    slug = project_path.name
    display_name = name or slug.replace("-", " ").replace("_", " ").title()
    desc = description or f"{display_name} — 基于 tg-agent-framework"

    if project_path.exists() and any(project_path.iterdir()):
        print(f"❌ 目录 {project_path} 不为空，请指定一个空目录")
        sys.exit(1)

    # 创建目录
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / "tools").mkdir()

    # 写入文件
    files = {
        "pyproject.toml": PYPROJECT_TEMPLATE.format(slug=slug, description=desc),
        ".env.example": ENV_EXAMPLE_TEMPLATE,
        ".gitignore": GITIGNORE_TEMPLATE,
        "README.md": README_TEMPLATE.format(name=display_name, slug=slug),
        "config.py": CONFIG_TEMPLATE.format(name=display_name),
        "main.py": MAIN_TEMPLATE.format(name=display_name, slug=slug),
        "prompts.py": PROMPTS_TEMPLATE.format(name=display_name),
        "tools/__init__.py": TOOLS_INIT_TEMPLATE.format(name=display_name),
        ".agent-rules.md": AGENT_RULES_TEMPLATE.format(name=display_name, slug=slug),
    }

    for filename, content in files.items():
        filepath = project_path / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")

    print(f"""
✅ 项目 {display_name} 已创建！

📁 {project_path}

🚀 快速开始:
   cd {project_path}
   cp .env.example .env   # 填写你的密钥
   pip install -e .
   python main.py

📝 开发指南: 查看 .agent-rules.md

💡 Vibe Coding:
   打开 Cursor/Copilot，它会自动读取 .agent-rules.md
   试试: "帮我添加一个查询 BTC 价格的工具"
""")


def main():
    parser = argparse.ArgumentParser(
        prog="tg-agent",
        description="tg-agent-framework 脚手架 — 一键生成新 Agent 项目",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="创建新 Agent 项目")
    init_parser.add_argument("project_dir", help="项目目录名")
    init_parser.add_argument("--name", help="Agent 显示名称", default=None)
    init_parser.add_argument("--description", help="项目描述", default="")

    args = parser.parse_args()

    if args.command == "init":
        create_project(args.project_dir, args.name, args.description)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
