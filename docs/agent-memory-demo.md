# Agent Memory 演示：alma-memory-demo

这个示例参考 `alma-subagent` 的人格化 Agent 写法，同时增加 Code Agent 原生的 `memory: project`：

```text
.claude/agents/alma-memory-demo.md
        │ 声明 memory: project
        ▼
.claude/agent-memory/alma-memory-demo/MEMORY.md
        │ 索引 topic
        ├── user_preferences.md
        └── collaboration_style.md
```

## 运行演示

重新启动带 Context Memory Inspector 的 CLI：

```powershell
bun run scripts/context-inspector/start.ts
```

在主 Agent 中输入：

```text
请调用 alma-memory-demo agent 回答：我喜欢什么泳姿？
```

也可以直接让整个 CLI 使用该 Agent：

```powershell
bun run scripts/context-inspector/start.ts --cli-args --agent alma-memory-demo
```

启动器默认显式启用 `user,project,local` 三种 setting sources，避免本机环境只加载内置 Agent。

然后输入：

```text
我喜欢什么泳姿？
```

## 观察点

1. `Agent Memory`：`loadAgentMemoryPrompt()` 根据 `memory: project` 定位 `.claude/agent-memory/alma-memory-demo/`，并把持久记忆说明与 `MEMORY.md` 加入 Agent prompt。
2. `Memory Recalled`：Agent 根据索引读取 `user_preferences.md`；网页标记来源为 `Read 工具`。
3. `Final API Context`：查看 Agent 最终收到的人格 prompt、Agent Memory prompt 和任务消息。

可以修改 `user_preferences.md` 中的泳姿后重新调用 Agent，演示“Agent 定义不变、独立记忆改变答案”。
