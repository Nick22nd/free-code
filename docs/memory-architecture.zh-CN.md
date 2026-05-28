# Memory 架构说明

这份文档从二次开发视角说明本仓库里的 memory 系统，包括机制、存储目录、生命周期、交互方式，以及相关代码位置。

## 总览

这个项目里有多套“memory”相关机制。它们目标相近，但不是同一个子系统：

- `CLAUDE.md` 指令记忆：显式的 instruction 文件，会被加载进上下文。
- Auto-memory / memdir：按项目作用域持久化的文件式记忆系统。
- Team memory：位于 auto-memory 目录下的共享记忆，可通过服务端 API 同步。
- Agent memory：按自定义 agent 类型隔离的持久化记忆。
- Session memory：当前会话摘要，主要服务于压缩和会话内连续性。

如果你要做长期记忆能力的二次开发，最核心的入口通常是 `src/memdir`。

## 存储位置

配置根目录由 `src/utils/envUtils.ts` 中的 `getClaudeConfigHomeDir()` 解析。

默认值：

```text
~/.claude
```

可通过环境变量覆盖：

```text
CLAUDE_CONFIG_DIR
```

### Auto-Memory

auto-memory 的路径在 `src/memdir/paths.ts` 中计算。

默认结构：

```text
<configHome>/projects/<sanitized canonical git root>/memory/
```

入口文件：

```text
<autoMemoryDir>/MEMORY.md
```

`MEMORY.md` 是索引，不是完整记忆正文。详细记忆通常保存在同目录下的 topic `.md` 文件中。

示例 memory 文件：

```markdown
---
name: testing preference
description: User prefers integration tests over mocked database tests
type: feedback
---

Use real database-backed integration tests for migration-related behavior.

Why: mocked tests previously missed production migration issues.
How to apply: avoid replacing database behavior with mocks when validating migrations.
```

支持的 `type` 值定义在 `src/memdir/memoryTypes.ts`：

```text
user
feedback
project
reference
```

### Team Memory

team memory 是 auto-memory 的子目录：

```text
<autoMemoryDir>/team/
<autoMemoryDir>/team/MEMORY.md
```

路径工具函数在：

```text
src/memdir/teamMemPaths.ts
```

team memory 受 `TEAMMEM` feature gate 控制，并且要求 auto-memory 已开启。

### Agent Memory

agent memory 由 `src/tools/AgentTool/agentMemory.ts` 处理。

作用域：

```text
user:    <memoryBase>/agent-memory/<agentType>/
project: <cwd>/.claude/agent-memory/<agentType>/
local:   <cwd>/.claude/agent-memory-local/<agentType>/
```

在 remote 模式下，local agent memory 可能被重定向到：

```text
CLAUDE_CODE_REMOTE_MEMORY_DIR/projects/<project>/agent-memory-local/<agentType>/
```

### Session Memory

session memory 是当前会话状态，不是跨会话长期知识。

路径：

```text
<configHome>/projects/<sanitized cwd>/<sessionId>/session-memory/summary.md
```

路径工具函数位于 `src/utils/permissions/filesystem.ts`：

- `getSessionMemoryDir()`
- `getSessionMemoryPath()`

具体实现位于：

```text
src/services/SessionMemory/sessionMemory.ts
```

### CLAUDE.md Memory

传统 instruction memory 由 `src/utils/claudemd.ts` 发现和加载。

常见位置：

```text
User:    <configHome>/CLAUDE.md
Project: <cwd>/CLAUDE.md
Project: <cwd>/.claude/CLAUDE.md
Project: <cwd>/.claude/rules/*.md
Local:   <cwd>/CLAUDE.local.md
Managed: managed settings path / CLAUDE.md
```

不同 memory 类型的路径选择在：

```text
src/utils/config.ts
```

## 开关机制

auto-memory 默认开启。

开启/关闭优先级实现在 `src/memdir/paths.ts` 的 `isAutoMemoryEnabled()`：

1. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=true` 关闭 auto-memory。
2. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=false` 强制开启。
3. `CLAUDE_CODE_SIMPLE` / `--bare` 关闭 auto-memory。
4. remote 模式下如果没有 `CLAUDE_CODE_REMOTE_MEMORY_DIR`，关闭 auto-memory。
5. settings 中的 `autoMemoryEnabled` 控制开关。
6. 否则默认开启。

auto-memory 目录覆盖方式：

- `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`：完整路径覆盖，主要用于 SDK/Cowork。
- settings 中的 `autoMemoryDirectory`：只允许 policy、flag、local、user settings 这些可信来源。

项目内 checked-in 的 project settings 不允许设置 `autoMemoryDirectory`。这是安全设计，避免恶意仓库把 memory 写入重定向到敏感目录。

## 启动与上下文注入

系统 prompt 会通过以下代码注入 memory 行为说明：

```text
src/constants/prompts.ts
src/memdir/memdir.ts
```

核心函数：

```ts
loadMemoryPrompt()
```

`loadMemoryPrompt()` 会：

- 判断 auto-memory 是否开启。
- 必要时创建 memory 目录。
- 构造 auto-only prompt 或 auto + team memory combined prompt。
- 注入何时保存、如何保存 memory 的规则。
- 在 KAIROS 模式下切换为 append-only daily log 行为。

传统 instruction 文件和 memory 索引通过 user context 加载：

```text
src/context.ts
src/utils/claudemd.ts
```

重要函数：

```ts
getMemoryFiles()
getClaudeMds()
filterInjectedMemoryFiles()
```

`getMemoryFiles()` 会发现和处理：

- `CLAUDE.md`
- `.claude/rules/*.md`
- `CLAUDE.local.md`
- auto-memory 的 `MEMORY.md`
- team-memory 的 `MEMORY.md`

它还处理：

- `@include` 指令。
- frontmatter 剥离。
- HTML 注释剥离。
- `MEMORY.md` 截断。
- 缓存失效。

## 召回 / 读取路径

auto-memory 的 topic 文件不会全部直接注入 prompt，而是按每轮用户输入做相关性召回。

流程：

1. `src/query.ts` 调用 `startRelevantMemoryPrefetch()` 启动 memory 预取。
2. `src/utils/attachments.ts` 找到最近一条真实用户消息。
3. `src/memdir/memoryScan.ts` 扫描 memory topic 文件，并读取 frontmatter。
4. `src/memdir/findRelevantMemories.ts` 用 side query 选择最多 5 个相关 memory。
5. 选中的文件会被读取，并作为 `relevant_memories` attachment 注入。

重要函数：

```ts
startRelevantMemoryPrefetch()
findRelevantMemories()
scanMemoryFiles()
readMemoriesForSurfacing()
collectSurfacedMemories()
```

扫描时会排除 `MEMORY.md`。`MEMORY.md` 被视为总是加载的索引；详细 topic 文件只在相关时召回。

被召回的 memory 会带上 `src/memdir/memoryAge.ts` 生成的 freshness 信息。也就是说，陈旧 memory 会以“历史上下文”的方式出现，而不是被当作当前事实。

## 写入路径

memory 写入有两条路径。

### 主 Agent 直接写入

主 agent 可以直接写 memory 文件，因为 `loadMemoryPrompt()` 已经告诉模型该怎么写。

prompt 中的规则包括：

- 如果用户明确要求 remember，立即保存。
- 如果用户要求 forget，找到并移除相关条目。
- 每个 topic 单独保存成一个文件。
- `MEMORY.md` 保持为简洁索引。
- 避免重复。
- 更新错误或过期的 memory。

相关 prompt 构造位于：

```text
src/memdir/memdir.ts
src/memdir/teamMemPrompts.ts
src/memdir/memoryTypes.ts
```

### 后台 Extract Memories

如果主 agent 没有写 memory，回合结束时可能 fork 一个后台 agent，从最近消息里抽取值得长期保存的内容。

核心文件：

```text
src/services/extractMemories/extractMemories.ts
src/services/extractMemories/prompts.ts
src/query/stopHooks.ts
src/utils/backgroundHousekeeping.ts
```

生命周期：

1. `startBackgroundHousekeeping()` 调用 `initExtractMemories()`。
2. 回合结束时，`handleStopHooks()` 调用 `executeExtractMemories()`。
3. `executeExtractMemories()` fork 一个 cache-safe 后台 agent。
4. fork 出来的 agent 收到 memory extraction prompt。
5. 这个 agent 可以读/搜 memory，并且只能写 memory 目录内部。
6. 如果写入了文件，会产生一个 `memory_saved` system message。

关键保护：

- 不在 subagent 中运行。
- auto-memory 关闭时不运行。
- remote 模式下不运行。
- 如果主会话已经写了 memory，本轮跳过，避免重复。
- 只允许读/搜工具，以及 memory 目录内写入。
- 重叠运行会被合并，必要时补跑一次 trailing extraction。

## Team Memory 同步

team memory 由 `src/services/teamMemorySync` 同步。

关键文件：

```text
src/services/teamMemorySync/index.ts
src/services/teamMemorySync/watcher.ts
src/services/teamMemorySync/types.ts
src/services/teamMemorySync/secretScanner.ts
src/services/teamMemorySync/teamMemSecretGuard.ts
```

启动入口：

```ts
startTeamMemoryWatcher()
```

同步行为：

- 启动时先从服务端 pull。
- 然后 watch 本地 team memory 目录。
- 本地写入会调度 push。
- pull 会把服务端 entries 写到本地磁盘。
- push 只上传 content hash 有变化的 entries。
- 用 ETag / `If-Match` 处理冲突。
- 本地删除不会删除远端数据；下一次 pull 会恢复。
- pull 时 server wins。
- push 冲突重试时尽量保留本地变更。
- secret scanner 会跳过包含敏感信息的文件。

感知 team memory 写入的 hook 位于：

```text
src/utils/sessionFileAccessHooks.ts
```

## Agent Memory

agent memory 给自定义 agents 提供独立的持久化 memory 目录。

核心文件：

```text
src/tools/AgentTool/agentMemory.ts
```

重要函数：

```ts
getAgentMemoryDir()
getAgentMemoryEntrypoint()
isAgentMemoryPath()
loadAgentMemoryPrompt()
```

`loadAgentMemoryPrompt()` 复用 auto-memory 的 `buildMemoryPrompt()`，但会增加 scope-specific guidance：

- user scope：记忆应更通用，适用于跨项目。
- project scope：记忆应贴合当前项目，并可能通过版本控制共享。
- local scope：记忆应贴合当前项目和当前机器。

agent 创建 UI 中的 memory 步骤在：

```text
src/components/agents/new-agent-creation/wizard-steps/MemoryStep.tsx
```

## Session Memory

session memory 会把当前对话总结到一个 session-local markdown 文件中。

核心文件：

```text
src/services/SessionMemory/sessionMemory.ts
```

初始化入口：

```ts
initSessionMemory()
```

它会注册 post-sampling hook，并在达到阈值后更新 `summary.md`。

这个功能和 auto-compact 相关。它不是长期用户/项目记忆。

手动抽取入口：

```ts
manuallyExtractSessionMemory()
```

summary 相关流程会用到它。

## UI 与命令

`/memory` 命令：

```text
src/commands/memory/index.ts
src/commands/memory/memory.tsx
```

memory 选择器 UI：

```text
src/components/memory/MemoryFileSelector.tsx
```

它可以展示：

- User memory。
- Project memory。
- Local memory。
- Auto-memory folder。
- Team memory folder。
- Active agent memory folders。
- Auto-memory 开关。
- Auto-dream 开关。

选择 memory 文件后，会通过配置的编辑器打开：

```text
$VISUAL
$EDITOR
默认编辑器 fallback
```

memory 更新通知位于：

```text
src/components/memory/MemoryUpdateNotification.tsx
src/components/messages/SystemTextMessage.tsx
```

## 权限与安全

memory 路径经常位于 `.claude` 下，而 `.claude` 被视为危险目录。因此项目为托管 memory 文件加了专门的内部读写权限。

核心文件：

```text
src/utils/permissions/filesystem.ts
```

重要检查：

```ts
isAutoMemPath()
isAgentMemoryPath()
isSessionMemoryPath()
checkReadableInternalPath()
```

auto-memory 默认有特殊写入 carve-out。例外是 `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`：这个 override 可以指向任意目录，因此不会自动获得静默写权限，除非 SDK 调用方显式授权。

team memory 的路径安全校验更严格：

```text
src/memdir/teamMemPaths.ts
```

它防护：

- null byte。
- 绝对路径 key。
- 反斜杠 traversal。
- URL 编码 traversal。
- Unicode normalization traversal。
- symlink escape。
- dangling symlink 写入。

用于折叠 UI / telemetry 的 memory 文件检测逻辑在：

```text
src/utils/memoryFileDetection.ts
```

## 重要代码地图

路径与开关：

```text
src/memdir/paths.ts
src/memdir/teamMemPaths.ts
src/tools/AgentTool/agentMemory.ts
src/utils/envUtils.ts
src/utils/config.ts
```

Prompt 构造：

```text
src/memdir/memdir.ts
src/memdir/teamMemPrompts.ts
src/memdir/memoryTypes.ts
src/constants/prompts.ts
src/QueryEngine.ts
```

Instruction 与索引加载：

```text
src/utils/claudemd.ts
src/context.ts
```

相关 memory 召回：

```text
src/query.ts
src/utils/attachments.ts
src/memdir/memoryScan.ts
src/memdir/findRelevantMemories.ts
src/memdir/memoryAge.ts
```

后台抽取：

```text
src/utils/backgroundHousekeeping.ts
src/query/stopHooks.ts
src/services/extractMemories/extractMemories.ts
src/services/extractMemories/prompts.ts
```

Team sync：

```text
src/services/teamMemorySync/index.ts
src/services/teamMemorySync/watcher.ts
src/services/teamMemorySync/secretScanner.ts
src/utils/sessionFileAccessHooks.ts
```

Session memory：

```text
src/services/SessionMemory/sessionMemory.ts
src/services/SessionMemory/sessionMemoryUtils.ts
src/services/SessionMemory/prompts.ts
src/services/compact/sessionMemoryCompact.ts
```

UI：

```text
src/commands/memory/index.ts
src/commands/memory/memory.tsx
src/components/memory/MemoryFileSelector.tsx
src/components/memory/MemoryUpdateNotification.tsx
src/components/messages/SystemTextMessage.tsx
```

权限与检测：

```text
src/utils/permissions/filesystem.ts
src/utils/memoryFileDetection.ts
src/utils/teamMemoryOps.ts
```

## 二次开发入口建议

如果要改“memory 存在哪里”：

- 从 `src/memdir/paths.ts` 开始。
- team memory 还要看 `src/memdir/teamMemPaths.ts`。
- agent memory 看 `src/tools/AgentTool/agentMemory.ts`。
- 同时检查 `src/utils/permissions/filesystem.ts` 中的权限 carve-out。

如果要改“什么内容应该被保存”：

- 改 `src/memdir/memoryTypes.ts` 中的 prompt sections。
- 改 `src/memdir/memdir.ts` 中 auto-only prompt 构造。
- 改 `src/memdir/teamMemPrompts.ts` 中 team combined prompt。
- 改 `src/services/extractMemories/prompts.ts` 中后台抽取 prompt。

如果要改“自动抽取时机/行为”：

- 从 `src/services/extractMemories/extractMemories.ts` 开始。
- 检查 `src/query/stopHooks.ts` 中的回合结束触发。
- 检查 `src/utils/backgroundHousekeeping.ts` 中的初始化。

如果要改“召回排序/选择”：

- 从 `src/memdir/findRelevantMemories.ts` 开始。
- 检查 `src/memdir/memoryScan.ts` 中的 manifest 扫描。
- 检查 `src/utils/attachments.ts` 中的 attachment 注入。

如果要改 `/memory` UI：

- 从 `src/components/memory/MemoryFileSelector.tsx` 开始。
- 检查 `src/commands/memory/memory.tsx` 中的命令包装。

如果要改 team sync：

- 从 `src/services/teamMemorySync/index.ts` 开始。
- 检查 `src/services/teamMemorySync/watcher.ts` 的 watcher 行为。
- 检查 `src/utils/sessionFileAccessHooks.ts` 中的写入通知。

