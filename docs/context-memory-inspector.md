# Context Memory Inspector 演示指南

Context Memory Inspector 用时间线展示 Code Agent 上下文中与记忆相关的变化：

```text
CLAUDE.md / rules 注入
        ↓
Agent Memory 加载
        ↓
Auto Memory 预取与召回
        ↓
Session Memory 更新
        ↓
最终 API System / Messages / Tools
```

它是完全 opt-in 的本地调试能力。默认运行不写快照，也不会触发断点。

## 最快启动方式：PowerShell 一键启动

在仓库根目录执行：

```powershell
bun run scripts/context-inspector/start.ts
```

脚本会自动完成四件事：启动本地网页、打开浏览器、设置 Inspector 与 Session Memory 演示变量、在当前终端运行主 CLI。退出 CLI 后，后台网页进程会自动清理。

常用选项：

```powershell
# 不自动打开浏览器
bun run scripts/context-inspector/start.ts --no-browser

# 不用低阈值强制触发 Session Memory
bun run scripts/context-inspector/start.ts --no-forced-session-memory

# 先等待调试器连接，再运行 CLI
bun run scripts/context-inspector/start.ts --wait-for-debugger

# 把 --cli-args 后面的参数直接传给 CLI（适合检查启动链路）
bun run scripts/context-inspector/start.ts --no-browser --cli-args --help
```

普通命令行启动可以完整记录快照并驱动网页，但 `debugger` 语句只有在调试器已连接时才会真正暂停。只看上下文变化不需要调试器；要在源码局部变量处停住，再使用 `-WaitForDebugger` 或下面的 VS Code 配置。

## VS Code 启动

1. 用 VS Code 打开仓库。
2. 接受工作区推荐并安装官方 `Bun for Visual Studio Code` 扩展。
3. 打开“运行和调试”。
4. 选择 `Memory Inspector: dashboard + CLI`。
5. 打开 <http://127.0.0.1:4317>。
6. 在 CLI 中执行演示对话。

组合配置会同时启动本地网页和主程序，并启用以下断点：

- `instructions_loaded`：`CLAUDE.md`、`CLAUDE.local.md`、rules 发现和拼接完成；
- `agent_memory_loaded`：自定义 Agent 的 memory prompt 构造完成；
- `memory_recall_resolved`：Auto Memory selector 完成并得到召回附件；
- `session_memory_updated`：Session `summary.md` 更新完成；
- `api_request_ready`：最终 API request 的 system/messages/tools 已组装完成。

断点写在调用位置而不是统一的 snapshot helper 中，因此暂停时可以直接检查局部变量，如 `injectedMemoryFiles`、`memoryAttachments`、`updatedSessionMemory` 和 `params`。

## 手动使用两个终端启动

先启动网页：

```powershell
bun run scripts/context-inspector/server.ts
```

再开另一个 PowerShell：

```powershell
$env:CLAUDE_CODE_CONTEXT_INSPECTOR='1'
$env:CLAUDE_CODE_CONTEXT_INSPECTOR_RESET='1'
$env:CLAUDE_CODE_CONTEXT_INSPECTOR_BREAKPOINTS='instructions_loaded,memory_recall_resolved,session_memory_updated,api_request_ready'
bun run src/entrypoints/cli.tsx
```

如果需要在短演示中强制生成 Session Memory：

```powershell
$env:CLAUDE_CODE_CONTEXT_INSPECTOR_FORCE_SESSION_MEMORY='1'
$env:CLAUDE_CODE_CONTEXT_INSPECTOR_SM_INIT_TOKENS='1'
$env:CLAUDE_CODE_CONTEXT_INSPECTOR_SM_UPDATE_TOKENS='1'
$env:CLAUDE_CODE_CONTEXT_INSPECTOR_SM_TOOL_CALLS='1'
```

这些覆盖值仅在 Context Inspector 已开启时生效，不改变普通运行行为。

## 网页怎么看

顶部六个节点显示当前 run 中各阶段触发次数：

1. `CLAUDE / Rules`
2. `Agent Memory`
3. `Recall Prefetch`
4. `Memory Recalled`
5. `Session Memory`
6. `Final API Context`

左侧时间线按发生顺序展示快照。选择事件后，右侧显示：

- 实际发现与注入的 instruction 文件；
- path-scoped rule 的 glob；
- 拼接后的 user context；
- Agent Memory prompt 与目录；
- `relevant_memories` 召回内容；
- Session `summary.md`；
- 最终发送给模型的 system、messages 和 tools。

网页每 800ms 读取一次本地 `events.jsonl`。主程序停在断点时，最近一次快照已经同步写盘，所以网页可以同时展示暂停点的整体状态。

## 建议演示脚本

### 1. CLAUDE.md 与 rules 注入

准备一条 project instruction 和一条带 `paths` 的 rule，然后启动 CLI。第一个断点查看：

- `discoveredMemoryFiles`
- `injectedMemoryFiles`
- `claudeMd`

如果 rule 是路径条件规则，让 Agent 读取一个匹配文件，再观察后续上下文出现新指令。

### 2. Auto Memory 召回

准备 description 清晰的 topic memory，例如“认证测试必须使用真实数据库”，然后询问匹配问题。

在 `memory_recall_resolved` 断点查看：

- `pendingMemoryPrefetch`
- `memoryAttachments`
- `toolUseContext.readFileState`

网页会显示 selector 最终选中了哪些文件以及注入正文。

### 3. Agent Memory

创建带 `memory: project` 的自定义 Agent 并调用它。`agent_memory_loaded` 断点可查看：

- `agentType`
- `scope`
- `memoryDir`
- `memoryPrompt`

### 4. Session Memory

使用 VS Code 演示配置中的低阈值覆盖，让主程序完成一轮自然交互。`session_memory_updated` 断点可查看：

- `memoryPath`
- `updatedSessionMemory`
- `messages`
- `config`

### 5. 最终上下文

在 `api_request_ready` 查看 `params`，网页同时展开：

- `params.system`
- `params.messages`
- `params.tools`

这一步把前面所有局部机制落到同一个事实：模型最终究竟看到了什么。

## 环境变量

| 变量 | 作用 |
|---|---|
| `CLAUDE_CODE_CONTEXT_INSPECTOR` | `1/true` 时启用快照 |
| `CLAUDE_CODE_CONTEXT_INSPECTOR_DIR` | 修改快照目录 |
| `CLAUDE_CODE_CONTEXT_INSPECTOR_RESET` | 启动首次写入时清空旧快照 |
| `CLAUDE_CODE_CONTEXT_INSPECTOR_BREAKPOINTS` | 逗号分隔的断点阶段，或 `all` |
| `CLAUDE_CODE_CONTEXT_INSPECTOR_MAX_CHARS` | 单个字符串的快照上限，默认 200,000 |
| `CONTEXT_INSPECTOR_PORT` | 网页端口，默认 4317 |

## 安全边界

快照可能包含完整 system prompt、用户消息、工具 schema、文件内容和 Memory。请注意：

- 只在可信的本地开发环境启用；
- 网页服务器只监听 `127.0.0.1`；
- `.claude/context-inspector/` 已加入 `.gitignore`；
- 演示后删除快照目录；
- 不要把 `events.jsonl` 上传到 issue、聊天或代码仓库。
