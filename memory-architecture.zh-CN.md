# free-code 项目 Memory 机制全景说明

本文基于当前仓库代码梳理项目内与 memory 相关的全部主线能力，覆盖：机制、入口、使用命令、实现方法、生命周期、存储位置，以及各模块之间的关系。

---

## 1. 总览：这个项目里的 memory 不是单一功能，而是一组分层机制

项目里的“memory”实际上分成 6 类：

1. **CLAUDE.md 指令记忆**
   - 主要是 `CLAUDE.md`、`CLAUDE.local.md`、`.claude/rules/*.md`
   - 作用是给模型提供长期/静态/规则型指令
   - 由 `src/utils/claudemd.ts` 负责发现、读取、缓存、注入上下文

2. **Auto Memory（自动持久记忆 / memdir）**
   - 存在于项目级 memory 目录中，入口文件是 `MEMORY.md`
   - 存储“跨会话可复用”的用户、反馈、项目、外部参考信息
   - 由 `src/memdir/*` + `src/services/extractMemories/*` 驱动

3. **Team Memory（团队共享记忆）**
   - 是 auto memory 的子目录 `team/`
   - 用于团队共享、跨用户同步的项目记忆
   - 由 `src/memdir/teamMemPaths.ts`、`src/memdir/teamMemPrompts.ts` 等控制

4. **Relevant Memories（按需召回记忆）**
   - 在用户发起新请求后，系统会根据 query 动态筛选最相关的 memory 文件并注入
   - 由 `src/memdir/findRelevantMemories.ts` 和 `src/utils/attachments.ts` 完成

5. **Agent Memory（Agent 专属持久记忆）**
   - 每个 agent 可以拥有独立 memory 目录
   - 支持 `user / project / local` 三种 scope
   - 由 `src/tools/AgentTool/agentMemory.ts` 管理

6. **Session Memory（会话记忆）**
   - 当前会话的摘要文件，不是长期记忆，而是“压缩/续聊/恢复上下文”的工作记忆
   - 由 `src/services/SessionMemory/*` 负责后台提炼、更新和压缩集成

除此之外，还有一个背景整理机制：

7. **Auto Dream（自动整理/归档记忆）**
   - 周期性扫描过去 session，把 memory 目录做 consolidatation / distillation
   - 由 `src/services/autoDream/*` 负责

---

## 2. 核心机制：Memory 在系统中如何工作

### 2.1 System Prompt 级加载

项目启动后，memory 的第一层接入发生在 system prompt 构建阶段：

- `src/constants/prompts.ts`
  - `getSystemPrompt()` 会通过 `systemPromptSection('memory', () => loadMemoryPrompt())` 把 memory prompt 拼进系统提示词
- `src/memdir/memdir.ts`
  - `loadMemoryPrompt()` 负责生成 auto memory / team memory 的行为说明
  - 它并不直接把所有 topic 文件内容塞进 prompt，而是主要提供：
    - memory 目录位置
    - memory 类型规范
    - 如何保存 memory
    - 何时访问 memory
    - 如何搜索 past context

这层的目标不是把所有记忆都塞进 prompt，而是**告诉模型 memory 系统的规则和入口**。

### 2.2 用户上下文中的 CLAUDE.md 注入

另一条更传统的“memory”链路是 CLAUDE.md 体系：

- `src/context.ts`
  - `getUserContext()` 中会调用 `getClaudeMds(filterInjectedMemoryFiles(await getMemoryFiles()))`
- `src/utils/claudemd.ts`
  - `getMemoryFiles()` 会收集：
    - Managed CLAUDE.md
    - User CLAUDE.md
    - Project CLAUDE.md
    - Local CLAUDE.local.md
    - `.claude/rules/*.md`
    - auto memory 入口 `MEMORY.md`
    - team memory 入口 `team/MEMORY.md`

也就是说：

- **CLAUDE.md 系统**负责把“显式指令文件”直接注入上下文
- **memdir / auto memory 系统**负责让模型知道如何读写持久记忆，并在需要时动态召回 topic memory

### 2.3 运行时动态召回 Relevant Memories

项目已经不是只依赖 `MEMORY.md` 索引了，还实现了“按 query 动态筛选 memory”的机制：

- `src/utils/attachments.ts`
  - `startRelevantMemoryPrefetch()`：在用户 turn 开始时异步预取 relevant memories
  - `getRelevantMemoryAttachments()`：实际执行检索
  - `readMemoriesForSurfacing()`：读取被选中的 memory 文件内容并做截断
- `src/memdir/findRelevantMemories.ts`
  - `scanMemoryFiles()` 先扫描 memory 目录中所有 `.md` 文件的 frontmatter
  - `selectRelevantMemories()` 再用 sideQuery/selector model 从候选中选出最相关的最多 5 个

这意味着当前 memory 机制不是“把整棵记忆树全量塞进 prompt”，而是：

- `MEMORY.md` / `team/MEMORY.md` 作为索引与规则入口
- 具体 memory topic 文件按需召回
- 已经 surfacing 过的 memory 会去重，避免重复注入
- 每个 memory 文件还会附带新鲜度提示，提醒可能已过时

### 2.4 背景提炼 durable memory

系统在一次完整 query loop 结束后，会把“本轮对话里值得长期保留的信息”自动提取到 auto memory：

- `src/services/extractMemories/extractMemories.ts`
  - `executeExtractMemories()`：停止钩子里触发
  - `runExtraction()`：启动 forked agent
  - `createAutoMemCanUseTool()`：限制该 agent 只能读、搜、改 memory 目录
- `src/services/extractMemories/prompts.ts`
  - 构造 extraction prompt，要求只基于最近消息提炼 durable memories

这个背景 agent 的职责是：

- 看最近几轮会话
- 判断有哪些内容值得长期记忆
- 更新对应 topic file
- 更新 `MEMORY.md` 索引
- 如果主 agent 已经自己写过 memory，则跳过

### 2.5 Session Memory：为压缩与续聊服务

Session memory 不属于长期知识库，而是当前会话的结构化摘要：

- `src/services/SessionMemory/sessionMemory.ts`
  - `initSessionMemory()`：注册 post-sampling hook
  - `shouldExtractMemory()`：根据 token 增长 / tool call 数量决定是否提炼
  - `setupSessionMemoryFile()`：确保 session memory 文件存在
  - `manuallyExtractSessionMemory()`：手动触发提炼
- `src/services/SessionMemory/prompts.ts`
  - 定义 session summary 模板与更新 prompt
- `src/services/SessionMemory/sessionMemoryUtils.ts`
  - 管理阈值、状态、last summarized message id

Session memory 的主要用途：

- 自动维护当前会话摘要
- 在 `/compact` 时优先用 session memory 做 compaction
- 避免传统 compaction 每次都重新总结整个会话

### 2.6 Auto Dream：周期性整理 memory

Auto Dream 是 memory 的后台 consolidation 机制：

- `src/services/autoDream/autoDream.ts`
  - 定时/阈值满足时触发 forked agent
- `src/services/autoDream/consolidationLock.ts`
  - 用 lock 文件和 mtime 实现“上次 consolidation 时间 + 并发互斥”
- `src/services/autoDream/config.ts`
  - 判断 auto dream 是否启用

它的作用更像 nightly/background maintenance：

- 按过去 session 数量和距离上次整理的时间判断是否触发
- 读取项目 transcript
- 整理并改进 memory 目录内容
- 保持 memory 体系不会只增不减、越积越乱

---

## 3. 入口：Memory 从哪里进入系统

### 3.1 CLI / 环境开关入口

- `src/entrypoints/cli.tsx`
  - 顶层处理 `CLAUDE_CODE_DISABLE_AUTO_MEMORY`
  - 在某些 baseline/ablation 场景下会直接把 auto memory 关闭

### 3.2 命令入口

#### 已确认的用户命令

1. `/memory`
   - 注册位置：`src/commands/memory/index.ts`
   - 具体实现：`src/commands/memory/memory.tsx`
   - 作用：打开 memory 文件选择器并编辑 memory 文件

2. `/compact`
   - 实现：`src/commands/compact/compact.ts`
   - 作用：与 session memory 集成；优先尝试 `trySessionMemoryCompaction()`
   - 这是 memory 生命周期中的重要消费入口

#### 代码里明确提到、但本次未在 `src/commands` 中找到独立命令入口的能力

- `/dream`
  - 在 prompt / 注释中多次出现
  - 更像 skill 或后台 consolidatation 机制的一部分
  - 当前仓库扫描中未找到 `src/commands/dream/*`
- `/remember`
  - 在注释中被提及，但未定位到单独命令实现

因此可以明确说：

- **可直接确认的 memory 用户命令：`/memory`**
- **与 memory 深度耦合的系统命令：`/compact`**
- **`/dream` / `/remember` 在当前仓库中更像概念或其他入口，不宜直接断言其为独立 slash command**

### 3.3 UI / 交互入口

- `src/components/memory/MemoryFileSelector.tsx`
  - `/memory` 命令打开的选择器
  - 可选择：
    - User memory
    - Project memory
    - auto-memory folder
    - team memory folder
    - agent memory folder
  - 还能切换：
    - auto memory 开关
    - auto dream 开关

### 3.4 Prompt / Context 入口

- `src/constants/prompts.ts` -> `loadMemoryPrompt()`
- `src/context.ts` -> `getMemoryFiles()` / `getClaudeMds()`
- `src/QueryEngine.ts`
  - 若使用 custom system prompt 且显式配置了 memory override，也会补注入 memory mechanics prompt

### 3.5 Attachment 入口

- `src/utils/attachments.ts`
  - `nested_memory`：针对文件路径动态加载嵌套 CLAUDE.md / rules
  - `relevant_memories`：针对 query 召回最相关 memory 文件

这是 memory 在“单次用户请求”里的最关键运行时入口。

---

## 4. 使用命令与用户可见行为

### 4.1 `/memory`

用途：打开 memory 管理/编辑界面。

实现点：

- `src/commands/memory/memory.tsx`
  - 打开 Dialog
  - 选择目标 memory 文件
  - 若不存在则先创建文件
  - 调起编辑器 `editFileInEditor()`
- `src/components/memory/MemoryFileSelector.tsx`
  - 构建可编辑 memory 列表与 folder 入口

用户可见行为：

- 编辑 `CLAUDE.md`
- 编辑项目 `CLAUDE.md`
- 打开 auto memory folder
- 打开 team memory folder
- 打开某个 agent 的 memory folder
- 开关 auto memory / auto dream

### 4.2 `/compact`

用途：压缩上下文，但会优先利用 session memory。

实现点：

- `src/commands/compact/compact.ts`
  - 无自定义 compact 指令时，先调用 `trySessionMemoryCompaction()`
- `src/services/compact/sessionMemoryCompact.ts`
  - 如果 session memory 存在且不只是空模板，则直接用它生成 compact 结果

这说明 session memory 是 memory 生命周期里的重要“消费层”。

### 4.3 自动行为（无显式命令）

1. **自动加载 memory 规则**
   - 启动 system prompt / user context 时完成

2. **自动召回 relevant memories**
   - 用户发起 query 时预取并注入

3. **自动抽取 durable memories**
   - 一轮会话结束后触发背景 extraction agent

4. **自动维护 session memory**
   - 在 token / tool thresholds 满足时后台更新

5. **自动 dream/consolidation**
   - 定期触发，对 memory 进行归并和整理

---

## 5. 实现方法：各类 memory 是怎么实现的

## 5.1 CLAUDE.md / rules 体系

实现核心：`src/utils/claudemd.ts`

能力包括：

- 递归发现 `CLAUDE.md`、`CLAUDE.local.md`、`.claude/rules/*.md`
- 支持 include / nested rules / conditional rules
- 支持 managed / user / project / local 分类
- 支持缓存与缓存失效
- 支持过滤哪些 memory 文件真正注入当前上下文

这是“指令型 memory”的主实现。

## 5.2 Auto Memory / Team Memory 体系

实现核心：

- `src/memdir/paths.ts`
  - 决定 auto memory 根目录路径
  - 提供开关 `isAutoMemoryEnabled()`
  - 处理 env override / settings override / remote memory dir
- `src/memdir/memdir.ts`
  - 生成 memory prompt
  - 确保 memory 目录存在
  - 规范 `MEMORY.md` 的索引写法
- `src/memdir/memoryTypes.ts`
  - 定义四种 memory taxonomy：
    - `user`
    - `feedback`
    - `project`
    - `reference`
- `src/memdir/teamMemPaths.ts`
  - 提供 team memory 开关与路径
- `src/memdir/teamMemPrompts.ts`
  - 当 team memory 打开时，生成 combined prompt

这个实现明确把 memory 设计成“文件系统 + frontmatter + index file”的持久层，而不是数据库。

## 5.3 Relevant Memory 检索

实现核心：

- `src/memdir/memoryScan.ts`
  - 扫描 memory 文件 frontmatter 与元信息
- `src/memdir/findRelevantMemories.ts`
  - 用 sideQuery 从 memory manifest 中挑选最相关的候选
- `src/utils/attachments.ts`
  - 读取选中的 memory 文件
  - 注入为 `relevant_memories` attachment
  - 控制大小、条数、去重和 session 总预算
- `src/memdir/memoryAge.ts`
  - 给旧 memory 加入 freshness / stale 提醒

这里的核心思想是：

- 全量 memory 存磁盘
- 运行时按 query 检索局部注入
- 避免 prompt 被 memory 全量内容撑爆

## 5.4 Session Memory 实现

实现核心：

- `src/services/SessionMemory/sessionMemory.ts`
  - 注册 post-sampling hook
  - 判断是否达到提取阈值
  - 用 forked agent 更新 `summary.md`
- `src/services/SessionMemory/sessionMemoryUtils.ts`
  - 管理配置、阈值、状态
- `src/services/SessionMemory/prompts.ts`
  - 维护 session memory 模板

Session memory 的实现特点：

- 单独的 markdown 文件
- 固定 section 模板
- 只能编辑该 memory 文件，不允许随意调用其他工具
- 用于 compact，而不是长期知识积累

## 5.5 背景 durable memory 提取

实现核心：`src/services/extractMemories/extractMemories.ts`

机制：

- 在主线程 query loop 完成后触发
- 启动 forked agent
- 只允许：
  - Read / Grep / Glob
  - 只读 Bash
  - Edit / Write 到 memory 目录内
- 如果主 agent 本轮已经写过 memory，则跳过
- 成功写入后会发出 memory saved 通知

## 5.6 Auto Dream 实现

实现核心：

- `src/services/autoDream/autoDream.ts`
- `src/services/autoDream/consolidationLock.ts`
- `src/services/autoDream/config.ts`

机制：

- 先看是否启用 auto dream
- 再看距离上次 consolidation 是否超过最小小时数
- 再看是否积累了足够多 session
- 最后拿 lock，避免多个进程并发整理
- 成功后更新 lock mtime，作为“上次整理时间”

---

## 6. 生命周期：一次 memory 从产生到被消费的完整链路

可以按下面的顺序理解：

### 阶段 1：启动/构建上下文

- `getSystemPrompt()` 调 `loadMemoryPrompt()`
- `getUserContext()` 调 `getMemoryFiles()` + `getClaudeMds()`
- 模型拿到：
  - memory 规则
  - 已发现的 CLAUDE.md/rules
  - auto/team memory 的入口信息

### 阶段 2：用户发起请求

- `attachments.ts` 启动 `startRelevantMemoryPrefetch()`
- 如果用户 query 足够明确，就从 memory 目录筛出最相关的 topic 文件
- 同时如果用户读某个文件路径，还可能触发 `nested_memory` 附件

### 阶段 3：主 agent 响应 / 工具调用

- 模型可以：
  - 直接读 memory 文件
  - 更新 `MEMORY.md`
  - 新增 topic memory 文件
- collapse / badge 系统会把 memory 读写操作识别成 memory 类操作单独统计

### 阶段 4：回合结束后自动提炼 durable memory

- `extractMemories` 背景 agent 运行
- 把最近对话里可长期复用的信息写入 auto memory / team memory
- 更新 topic 文件和索引文件

### 阶段 5：会话持续期间维护 session memory

- 达到 token 增长阈值或 tool call 阈值后
- `sessionMemory` 背景 agent 更新 `summary.md`

### 阶段 6：上下文压缩时消费 session memory

- 用户执行 `/compact` 或系统自动 compact
- 优先尝试 `trySessionMemoryCompaction()`
- 若 session memory 可用，则直接把它作为 compact summary 使用

### 阶段 7：更长期后台整理

- auto dream 根据时间和 session 数量阈值触发
- 整理 auto memory 目录内容
- 避免 memory 长期堆积后变乱、变重、失去索引质量

---

## 7. 存储：各种 memory 存在哪里

## 7.1 CLAUDE.md 体系

可能位置包括：

- `~/.claude/CLAUDE.md`（User）
- `<project>/CLAUDE.md`（Project）
- `<project>/CLAUDE.local.md`（Local）
- `<project>/.claude/CLAUDE.md`
- `<project>/.claude/rules/*.md`
- managed rules / managed CLAUDE 路径（由 settings / policy 决定）

## 7.2 Auto Memory

由 `src/memdir/paths.ts` 决定，解析顺序是：

1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`
2. settings 中的 `autoMemoryDirectory`
3. 默认：
   - `<memoryBase>/projects/<sanitized-git-root>/memory/`

其中：

- `memoryBase` 默认是 `~/.claude`
- 也可能被 `CLAUDE_CODE_REMOTE_MEMORY_DIR` 重定向

典型文件：

- `MEMORY.md`
- 各个 topic memory 文件 `*.md`
- `logs/YYYY/MM/YYYY-MM-DD.md`（KAIROS daily log 模式）

## 7.3 Team Memory

位置：

- `<autoMemPath>/team/`
- 入口：`<autoMemPath>/team/MEMORY.md`

也就是 team memory 是 auto memory 的子目录，不是完全独立的根。

## 7.4 Agent Memory

由 `src/tools/AgentTool/agentMemory.ts` 管理，按 scope 分三类：

- user scope：`<memoryBase>/agent-memory/<agentType>/`
- project scope：`<cwd>/.claude/agent-memory/<agentType>/`
- local scope：
  - 本地模式：`<cwd>/.claude/agent-memory-local/<agentType>/`
  - remote memory 模式下：`<remoteMemoryDir>/projects/<sanitized-project>/agent-memory-local/<agentType>/`

入口文件都是：

- `MEMORY.md`

## 7.5 Session Memory

由 `src/utils/permissions/filesystem.ts` 决定：

- 目录：`{projectDir}/{sessionId}/session-memory/`
- 文件：`{projectDir}/{sessionId}/session-memory/summary.md`

其中 `projectDir` 形态通常在 `~/.claude/projects/<sanitized-cwd>/...`

## 7.6 Auto Dream 锁文件

位置：

- `<autoMemPath>/.consolidate-lock`

作用：

- 文件 mtime = 上次 consolidation 时间
- 文件内容 = 持有锁的 PID

---

## 8. Memory 类型模型

## 8.1 Durable memory 的四种类型

定义在 `src/memdir/memoryTypes.ts`：

1. `user`
   - 记录用户身份、角色、目标、偏好、知识背景

2. `feedback`
   - 记录用户对协作方式的反馈与约束

3. `project`
   - 记录项目上下文、目标、约束、进度、决策原因

4. `reference`
   - 记录外部系统、仪表盘、文档、Linear/Slack/Grafana 等入口

## 8.2 不应该写进 memory 的内容

项目里明确规定下列内容不应进入 durable memory：

- 代码结构、文件路径、架构模式
- git 历史、变更记录
- 临时调试方案
- 已经存在于 CLAUDE.md 的说明
- 当前会话的临时任务状态

这说明 memory 的设计目标很明确：

- **记“未来会话还值得知道”的信息**
- **不记“当前仓库状态本就可以重新推导”的信息**

---

## 9. 权限与安全设计

项目对 memory 的读写权限控制非常明确。

## 9.1 内部路径白名单

`src/utils/permissions/filesystem.ts` 允许这些 memory 路径绕过普通权限阻塞：

- session memory 路径：可读
- project transcript/project dir：可读
- agent memory 路径：可读/可写
- auto memory 路径：可读；在非 override 模式下可写

## 9.2 Team Memory 路径安全

`src/memdir/teamMemPaths.ts` 做了额外防护：

- 拒绝 null byte
- 拒绝 URL 编码 traversal
- 拒绝 unicode normalization traversal
- 拒绝绝对路径/反斜杠注入
- 用 `realpath` 检查 deepest existing ancestor
- 防止 symlink escape

这是整个 memory 系统里安全防护最重的一块，说明 team memory 被视为更高风险的数据平面。

## 9.3 Memory 文件识别

`src/utils/memoryFileDetection.ts` 会统一识别：

- auto memory
- team memory
- agent memory
- session memory
- session transcript

用途包括：

- collapse 统计
- badge 显示
- shell 命令是否在访问 memory 的判定
- 区分 auto-managed memory 与用户管理的 `CLAUDE.md`

---

## 10. 性能与上下文控制

Memory 不是无限注入的，代码里有很多预算控制：

### 10.1 `MEMORY.md` 截断

`src/memdir/memdir.ts`：

- `MAX_ENTRYPOINT_LINES = 200`
- `MAX_ENTRYPOINT_BYTES = 25000`

意味着：

- `MEMORY.md` 被当作索引，而不是正文容器
- 如果太长，只会部分加载，并附带 warning

### 10.2 relevant memory 单文件截断

`src/utils/attachments.ts`：

- `MAX_MEMORY_LINES = 200`
- `MAX_MEMORY_BYTES = 4096`
- 单个 turn 的 session 总 relevant memory byte 预算也有限

### 10.3 Memory 膨胀诊断

- `src/utils/contextSuggestions.ts`
  - 如果 memory 占上下文比例过高，会给出建议：使用 `/memory` 修剪 stale entries
- `src/utils/status.tsx`
  - 会给出 memory diagnostics
- `src/utils/doctorContextWarnings.ts`
  - 会检测过大的 memory 文件

这说明项目已经把 memory 当作“上下文预算的一部分”来精细管理。

---

## 11. 各模块之间的关系

可以把整个 memory 子系统理解成下面的分层：

### A. 发现与加载层

- `src/utils/claudemd.ts`
- `src/memdir/memdir.ts`
- `src/memdir/paths.ts`
- `src/memdir/teamMemPaths.ts`

职责：

- 决定 memory 在哪
- 找到哪些 memory 文件
- 生成 prompt 与上下文注入内容

### B. 检索与召回层

- `src/memdir/memoryScan.ts`
- `src/memdir/findRelevantMemories.ts`
- `src/utils/attachments.ts`
- `src/memdir/memoryAge.ts`

职责：

- 扫描 memory topic files
- 按 query 选择最相关 memory
- 做新鲜度提示和注入

### C. 写入与提炼层

- `src/services/extractMemories/extractMemories.ts`
- `src/services/extractMemories/prompts.ts`
- `src/tools/AgentTool/agentMemory.ts`
- `src/services/SessionMemory/sessionMemory.ts`

职责：

- 把对话内容落成 durable memory 或 session memory
- 为 agent 提供独立记忆空间

### D. 后台整理与压缩消费层

- `src/services/autoDream/autoDream.ts`
- `src/services/compact/sessionMemoryCompact.ts`
- `src/commands/compact/compact.ts`

职责：

- 周期整理 memory
- 在 compact 时消费 session memory

### E. 权限与可观测性层

- `src/utils/permissions/filesystem.ts`
- `src/utils/memoryFileDetection.ts`
- `src/utils/collapseReadSearch.ts`
- `src/utils/teamMemoryOps.ts`

职责：

- 安全控制
- 记忆读写行为识别
- UI 汇总与 telemetry

---

## 12. 最终结论

这个项目的 memory 体系已经不是简单的 `CLAUDE.md` 文件加载，而是一个完整的多层持久化系统：

1. **CLAUDE.md / rules** 负责静态指令与规则
2. **Auto Memory / Team Memory** 负责 durable、跨会话、可演化的记忆库
3. **Relevant Memories** 负责运行时按 query 检索召回
4. **Agent Memory** 负责每个 agent 的独立长期记忆
5. **Session Memory** 负责当前会话摘要和 compact 支撑
6. **Auto Dream** 负责长期整理与归并

整体设计目标非常清晰：

- 用文件系统做持久化
- 用 `MEMORY.md` 做轻量索引
- 用 topic files 保存正文
- 用 runtime selector 避免全量注入
- 用 session memory 优化 compaction
- 用 auto dream 解决 memory 腐化与膨胀问题

如果只用一句话概括：

> 这个仓库里的 memory 是“文件化持久层 + 运行时召回层 + 背景提炼层 + 压缩消费层”的组合系统，而不是单一 prompt 附件功能。

---

## 13. 关键源码索引

### 命令/UI
- `src/commands/memory/index.ts`
- `src/commands/memory/memory.tsx`
- `src/components/memory/MemoryFileSelector.tsx`
- `src/components/memory/MemoryUpdateNotification.tsx`

### Prompt / Context / Engine
- `src/constants/prompts.ts`
- `src/context.ts`
- `src/QueryEngine.ts`
- `src/entrypoints/cli.tsx`

### CLAUDE.md / rules
- `src/utils/claudemd.ts`

### memdir / auto memory / team memory
- `src/memdir/paths.ts`
- `src/memdir/memdir.ts`
- `src/memdir/memoryTypes.ts`
- `src/memdir/memoryScan.ts`
- `src/memdir/findRelevantMemories.ts`
- `src/memdir/memoryAge.ts`
- `src/memdir/teamMemPaths.ts`
- `src/memdir/teamMemPrompts.ts`

### session memory
- `src/services/SessionMemory/sessionMemory.ts`
- `src/services/SessionMemory/sessionMemoryUtils.ts`
- `src/services/SessionMemory/prompts.ts`
- `src/services/compact/sessionMemoryCompact.ts`

### extraction / dream
- `src/services/extractMemories/extractMemories.ts`
- `src/services/extractMemories/prompts.ts`
- `src/services/autoDream/autoDream.ts`
- `src/services/autoDream/config.ts`
- `src/services/autoDream/consolidationLock.ts`

### 检测 / 权限 / 汇总
- `src/utils/attachments.ts`
- `src/utils/memoryFileDetection.ts`
- `src/utils/permissions/filesystem.ts`
- `src/utils/collapseReadSearch.ts`
- `src/utils/teamMemoryOps.ts`
- `src/utils/contextSuggestions.ts`
- `src/utils/status.tsx`
