# tg-agent-framework

> Telegram + LangGraph Agent 快速开发框架
>
> **3 步创建你的 AI Agent** — 定义配置、编写工具、写 Prompt

## ⚡ 30 秒上手

```bash
# 1. 安装框架
pip install -e .

# 2. 生成新项目
tg-agent init my-agent --name "我的Agent"

# 3. 配置并启动
cd my-agent
cp .env.example .env  # 填写 Telegram Token + LLM API Key
pip install -e .
python main.py
```

## 🧩 框架能力

| 能力 | 说明 |
|:--|:--|
| 🤖 LangGraph 编排 | 自动路由 LLM → 工具调用，支持安全/危险工具分离 |
| 📱 Telegram Bot | 消息处理、进度追踪、Markdown→HTML、权限校验 |
| ⚠️ 操作确认 | 危险工具自动暂停，等用户 Telegram 确认后执行 |
| 💾 状态持久化 | SQLite 存储会话与前台操作状态，重启不丢失 |
| 🧠 长期记忆 | 可选 SQLite 长期记忆，支持 user/thread/global scope |
| 🔧 声明式注册 | `@tool_registry.register()` 一行注册工具 |
| 📡 事件总线 | `EventBus` 发布/订阅，解耦框架与业务 |
| ⏰ 定时调度 | `BaseScheduler` 注册式健康检查 |
| 🔒 安全校验 | Shell 命令白名单 + 参数黑名单 |

## 🏗️ 开发新 Agent

### 最小示例

```python
# main.py
import asyncio
from dataclasses import dataclass
from langchain_core.tools import tool
from tg_agent_framework import *

# 1️⃣ 配置
@dataclass
class MyConfig(BaseConfig):
    api_url: str = "http://localhost:3000"

# 2️⃣ 工具
@tool_registry.register(category=ToolCategory.SAFE)
@tool
async def get_status() -> str:
    """查询系统状态"""
    return "✅ 一切正常"

@tool_registry.register(category=ToolCategory.DANGEROUS)
@tool
async def restart_service(name: str) -> str:
    """重启服务（需确认）"""
    return f"已重启 {name}"

# 3️⃣ Bot
class MyBot(AgentBot):
    def get_start_message(self):
        return "🤖 **我的 Agent** 已就绪！"

    def get_quick_actions(self):
        return [QuickAction("📊 状态", "quick:status")]

# 启动
async def main():
    config = load_base_config(MyConfig)
    store = RuntimeStateStore.from_config(config)
    store.init_schema()
    memory = SqliteLongTermMemory.from_config(config)
    await memory.init_schema()

    def graph_factory(current_config: MyConfig, current_state_store: RuntimeStateStore):
        return build_graph(
            config=current_config,
            state_store=current_state_store,
            system_prompt="你是一个智能助手...",
        )

    graph, _ = graph_factory(config, store)
    bot = MyBot(
        config=config,
        graph=graph,
        state_store=store,
        memory=memory,
        graph_factory=graph_factory,
    )
    await bot.run()

asyncio.run(main())
```

### 自定义扩展点

| 方法 | 用途 |
|:--|:--|
| `get_start_message()` | /start 欢迎文案 |
| `get_quick_actions()` | 快捷操作按钮面板 |
| `get_bot_commands()` | Bot 命令菜单 |
| `on_quick_action()` | 处理快捷按钮回调 |

## 💡 Vibe Coding

脚手架自动生成 `.agent-rules.md`，主流 AI 编码工具（Cursor、Copilot、Gemini Code Assist）会自动读取。

**试试这些 prompt：**

```
"帮我添加一个查询 BTC 价格的工具"
"添加一个需要确认才能执行的删除订单工具"
"把欢迎文案改成英文"
"添加一个每 5 分钟检查 API 健康状态的定时任务"
```

AI 会根据 `.agent-rules.md` 中的规范自动在正确位置生成代码。

## 📁 项目结构

```
tg_agent_framework/
├── config.py           # BaseConfig + SSHConfigMixin
├── state.py            # AgentState
├── graph.py            # build_graph() 通用编排
├── registry.py         # ToolRegistry 声明式注册
├── events.py           # EventBus 事件总线
├── scheduler.py        # BaseScheduler 定时调度
├── bot/
│   ├── agent_bot.py    # ★ AgentBot 核心基类
│   ├── auth.py         # 权限校验
│   ├── keyboards.py    # 键盘构建
│   ├── markdown.py     # Markdown→Telegram HTML
│   └── types.py        # QuickAction 等类型
├── memory/
│   ├── base.py         # BaseMemory ABC
│   ├── null.py         # NullMemory 空实现
│   ├── sqlite_memory.py # SqliteLongTermMemory
│   ├── types.py        # MemoryScope / MemoryRecord
│   ├── runtime_backend.py # RuntimeStateBackend
│   ├── checkpointer.py # PersistentMemorySaver
│   └── runtime_store.py # RuntimeStateStore (SQLite)
├── tools/
│   └── security.py     # Shell 安全校验
└── cli/
    └── init.py         # tg-agent init 脚手架
```

## 📄 License

MIT
