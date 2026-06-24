# Code Agent 如何记住一件事？

> 一条记忆从创建、索引、召回到压缩后重现的源码旅程  
> 组内技术分享 · Memory 主题 · 约 30 分钟

## 这次分享要解决什么

我们每天都在使用 Code Agent，但“它为什么记得”“为什么有时又忘了”，很容易停留在产品感觉上。

这次分享聚焦 Code Agent 的**持久上下文与 Memory 家族**：

1. `CLAUDE.md`、`.claude/rules/`、auto memory 和 agent memory 各自解决什么问题；
2. 什么信息值得成为自动记忆；
3. 一条记忆怎样被创建和写入；
4. 指令和记忆如何进入模型上下文；
5. 压缩发生后，记忆为什么还能再次出现；
6. 这些机制在我们的源码中分别落在哪里。

上下文窗口、压缩策略、文件恢复和 Skill 重建只讲与 Memory 的交界面，完整机制留到下一次 Context 主题分享。

---

## 1. 从一个真实问题开始

假设用户说：

> 以后这个项目的集成测试不要 mock 数据库。上个季度 mock 测试全部通过，但生产迁移失败了。

几天后的新会话里，用户让 Code Agent 给新模块补测试。

Agent 可以重新读取测试代码，也可以查看 Git 历史，但以下信息很难从仓库里重新推导：

- “不能 mock 数据库”是团队约定；
- 约定来自一次真实事故；
- 遇到速度与真实性冲突时，应优先真实性。

这正是 Memory 应该保存的信息。

### 第一个判断：它能否被重新推导？

源码在 [`src/memdir/memoryTypes.ts`](../src/memdir/memoryTypes.ts) 中给出了非常重要的原则：

> Memory 保存的是无法从当前项目状态重新推导的上下文。

| 信息 | 更合适的来源 | 是否适合 Memory |
|---|---|---:|
| 函数参数和返回值 | 代码 | 否 |
| 某次提交改了什么 | Git | 否 |
| 构建命令 | README / package.json | 通常否 |
| 用户偏好简洁回复 | 用户反馈 | 是 |
| 禁止 mock 数据库及其原因 | 团队约定与事故背景 | 是 |
| 合并冻结从哪天开始、为什么 | 项目状态 | 是 |
| 某类事故去哪个 Linear 项目查 | 外部信息指针 | 是 |

这条边界很关键：Memory 不是另一个代码索引，也不是把对话全部永久保存。

---

## 2. 先建立全景：这不是一个文件，而是一组持久化机制

在源码内部，“memory”这个词覆盖了几类相邻但不同的机制：

```text
持久上下文家族
│
├── Instruction Memory
│   ├── CLAUDE.md / CLAUDE.local.md
│   └── .claude/rules/*.md
│
├── Auto Memory
│   ├── MEMORY.md 索引
│   └── topic memory files
│
├── Agent Memory
│   └── 每种自定义 agent 独立的 MEMORY.md + topic files
│
└── Session Memory / Compact Summary
    └── 当前会话连续性；本次只讲边界
```

它们都在回答“未来模型还需要看到什么”，但写入者、加载时机、作用域和生命周期不同。

| 机制 | 主要写入者 | 加载方式 | 典型内容 |
|---|---|---|---|
| `CLAUDE.md` | 人/团队 | 启动时或目录发现后直接注入 | 项目约定、命令、非显然规则 |
| `.claude/rules/*.md` | 人/团队 | 全局或按文件路径条件加载 | 测试、安全、语言/模块规则 |
| Auto Memory | 主 Agent / 后台提取器 | 行为说明 + 按需召回正文 | 用户偏好、反馈、项目动机 |
| Agent Memory | 具有 `memory:` 的自定义 agent | agent spawn 时注入专属 memory prompt/index | reviewer/architect 等专业经验 |
| Session Memory | 系统 | 会话内摘要与恢复 | 当前工作进展和短期连续性 |

### 关于 AGENT.md / AGENTS.md 的命名

当前运行时的 instruction discovery 直接识别的是 `CLAUDE.md`、`CLAUDE.local.md` 和 `.claude/rules/*.md`。`AGENTS.md` 会在 `/init` 的兼容性调查中被读取，用来帮助生成或改进 `CLAUDE.md`，但它不在 [`getMemoryFiles()`](../src/utils/claudemd.ts) 的直接加载集合里。

如果“AGENT.md”指的是自定义 agent 定义文件，则它通常位于 `.claude/agents/<name>.md`。定义文件本身是 agent 的 prompt/config；通过 frontmatter 中的 `memory: user | project | local`，它可以为这个 agent 开启独立的 Agent Memory。

### 本次深入哪一层

这次会先把 `CLAUDE.md/rules`、Agent Memory 与 Session Memory 补齐，再用最多时间深入 Auto Memory 的创建和召回。Session Memory 只讲滚动摘要和 compact 消费接口，完整 compact 流程留到下一次 Context 主题。

---

## 3. CLAUDE.md 与 rules：人写的 Instruction Memory

[`src/utils/claudemd.ts`](../src/utils/claudemd.ts) 的文件头直接把这一体系称为 memory，并定义了加载顺序：

```text
Managed → User → Project → Local
```

越靠近当前工作目录、越晚加载的文件，优先级越高，模型也会更加关注。

### 常见位置

```text
Managed   系统管理路径中的 CLAUDE.md / rules
User      ~/.claude/CLAUDE.md
          ~/.claude/rules/*.md
Project   <repo>/CLAUDE.md
          <repo>/.claude/CLAUDE.md
          <repo>/.claude/rules/*.md
Local     <repo>/CLAUDE.local.md
```

Project 和 Local 文件会从当前目录一路向上发现；更靠近当前目录的指令后加载。`CLAUDE.local.md` 适合不提交版本库的个人项目指令。

### CLAUDE.md 适合什么

```markdown
# Project Instructions

- 修改认证模块后运行 `bun test auth`。
- 生产迁移必须先经过 staging dry-run。
- PR 描述需要说明用户可见行为变化。
```

它适合“每次在这个范围内工作都应该看到”的显式约定。代价也很直接：内容会进入上下文，因此应该保持短、稳定、不可从仓库轻易推导。

`@path`、`@./relative/path`、`@~/path` 等 include 可以拆分长说明；外部 include 还会经过信任/批准检查，并避免循环引用。

### rules 为什么不是另一个大 CLAUDE.md

`.claude/rules/` 可以按主题拆分：

```text
.claude/rules/
├── testing.md
├── security.md
└── frontend/
    └── react.md
```

无 `paths` frontmatter 的 rule 会作为无条件项目指令加载；带 `paths` 的 rule 只在目标文件匹配 glob 时加载：

```markdown
---
paths:
  - "src/auth/**"
  - "tests/auth/**"
---

- 认证测试必须使用真实测试数据库。
- 修改 token 校验时必须覆盖过期和时钟漂移场景。
```

源码中的 [`processConditionedMdRules()`](../src/utils/claudemd.ts) 会把目标文件转换成相对路径，再用 glob 筛选匹配规则。嵌套目录的 `CLAUDE.md` 和 rules 也会在 Agent 实际接触相应文件时动态加入，形成“越接近文件，指令越具体”的层级。

### Instruction Memory 与 Auto Memory 的本质差异

| | Instruction Memory | Auto Memory |
|---|---|---|
| 写入责任 | 人/团队明确维护 | Agent 主动写入或后台提取 |
| 载入策略 | 直接注入或按路径条件加载 | 索引/manifest + 正文相关性召回 |
| 内容语气 | “必须/应该怎样做” | “过去学到了什么、为什么” |
| 稳定性 | 相对稳定、可版本控制 | 逐步积累、可能更新 |
| 强制性 | 影响模型行为，但仍不是机械策略引擎 | 作为决策上下文，不是硬约束 |

安全和权限要求如果必须被机械执行，仍应使用 settings、permissions、hooks 或 sandbox；不能只依赖 Markdown 指令。

---

## 4. Agent Memory：每种专家 Agent 的独立经验

自定义 agent 定义可以在 frontmatter 中声明 memory scope：

```markdown
---
name: code-reviewer
description: 审查当前改动中的正确性、可维护性与风险
memory: project
tools: Read, Grep, Glob
---

审查最近改动，并把反复出现的架构模式、常见问题和审查经验写入 agent memory。
```

[`loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts) 接受三个 scope：

| scope | 目录 | 用途 |
|---|---|---|
| `user` | `<memoryBase>/agent-memory/<agentType>/` | 跨项目通用的专家经验 |
| `project` | `.claude/agent-memory/<agentType>/` | 当前项目经验，可通过版本控制共享 |
| `local` | `.claude/agent-memory-local/<agentType>/` | 当前项目和机器的私有经验 |

### 它怎样进入 Agent

[`loadAgentMemoryPrompt()`](../src/tools/AgentTool/agentMemory.ts) 在 agent spawn 时：

1. 根据 agent type 与 scope 计算独立目录；
2. 异步确保目录存在；
3. 复用 Auto Memory 的 `buildMemoryPrompt()`；
4. 读取该目录的 `MEMORY.md` 索引，并告诉 agent 如何搜索/读取同目录的 topic files；
5. 增加 user/project/local 的 scope-specific guidance；
6. 将结果追加到这个 agent 的 system prompt。

启用 memory 的 agent 即使原本只声明了部分工具，也会补充 File Read/Edit/Write，使它能够维护自己的记忆文件。

### 为什么 Agent Memory 不能简单并入全局 Auto Memory

```text
主 Agent Auto Memory
  └── 用户偏好、合作方式、项目背景

code-reviewer Agent Memory
  └── 常见缺陷、审查模式、架构约定

test-runner Agent Memory
  └── 测试入口、常见失败、flaky test 规律
```

隔离让不同专家积累自己的 institutional knowledge，同时避免所有专业细节都污染主 Agent 的长期上下文。

---

## 5. Session Memory：当前会话的滚动工作摘要

Session Memory 不是跨会话长期知识库，而是当前 session 的结构化工作状态。它回答的是：

> 如果原始消息即将被压缩，或者这个 session 之后被恢复，怎样保留当前任务、进度、错误与关键结果？

### 存储位置与结构

[`getSessionMemoryPath()`](../src/utils/permissions/filesystem.ts) 为每个项目和 session 生成独立路径：

```text
<projectDir>/<sessionId>/session-memory/summary.md
```

目录权限默认是 `0700`，文件权限是 `0600`。首次创建时会写入固定模板，默认包含：

```text
Task specification
Current State
Files and Functions
Workflow
Errors & Corrections
Codebase and System Documentation
Learnings
Key results
Worklog
```

其中 `Current State`、`Errors & Corrections` 和 `Key results` 对压缩后的连续性尤其重要。模板还可以通过用户配置目录下的 `session-memory/config/template.md` 自定义。

### 它怎样滚动更新

[`initSessionMemory()`](../src/services/SessionMemory/sessionMemory.ts) 在启动时注册 post-sampling hook；真正的 gate 检查和配置加载延迟到 hook 执行时。

```text
主会话完成一次 sampling
        │
        ▼
post-sampling hook
        │
        ├── 仅 repl_main_thread
        ├── 检查 tengu_session_memory
        ├── 检查 token / tool-call 阈值
        └── sequential extractSessionMemory
                  │
                  ▼
          forked agent 编辑 summary.md
```

当前默认配置位于 [`sessionMemoryUtils.ts`](../src/services/SessionMemory/sessionMemoryUtils.ts)，但可以被远端配置覆盖：

| 条件 | 默认值 | 含义 |
|---|---:|---|
| `minimumMessageTokensToInit` | 10,000 | context 达到此规模才初始化 |
| `minimumTokensBetweenUpdate` | 5,000 | 两次更新之间至少增长的 context tokens |
| `toolCallsBetweenUpdates` | 3 | 更新节奏的工具调用信号 |

token 增长条件始终必需；工具调用阈值满足，或者最近 assistant turn 没有工具调用、形成自然停顿时，才会执行更新。

提取使用 `runForkedAgent(querySource='session_memory')`，只允许编辑指定的 `summary.md`，并用 sequential wrapper 避免并发更新相互覆盖。成功后记录 `lastSummarizedMessageId`，明确这份摘要覆盖到了哪条消息。

### Session Memory 与 Auto Memory 的区别

| | Session Memory | Auto Memory |
|---|---|---|
| 作用域 | 当前 session | 跨 session / 项目相关长期记忆 |
| 组织方式 | 一个结构化滚动摘要 | MEMORY.md + 多个 topic files |
| 更新依据 | context 增长、工具调用和自然停顿 | 用户反馈、不可推导信息、后台提取 |
| 主要消费者 | compact、resume、away summary 等 | 未来用户查询与 Agent 决策 |
| 核心目标 | 当前工作不掉线 | 长期合作不失忆 |

### Compact 如何消费 Session Memory

当 `tengu_session_memory` 与 `tengu_sm_compact` 都开启（或由环境变量覆盖）时，[`trySessionMemoryCompaction()`](../src/services/compact/sessionMemoryCompact.ts) 会在传统 compact 之前尝试：

1. 等待正在进行的 session memory 更新，最多等待 15 秒；
2. 读取 `summary.md`，空模板则回退传统 compact；
3. 用 `lastSummarizedMessageId` 找到已经被摘要覆盖的消息边界；
4. 保留边界之后的一段最近消息，并避免切断 tool_use/tool_result 对；
5. 把 session memory 作为 compact summary；
6. 重新执行 SessionStart compact hooks，恢复 `CLAUDE.md` 等上下文；
7. 如果结果仍超过阈值，则回退传统 compact。

这说明 Session Memory 不只是“旁路笔记”，而是 Context 压缩的一种预计算摘要。它提前、增量地维护工作状态，让 compact 不必在最后一刻才从整段历史重新概括一遍。

本次分享讲到这个接口即可；消息保留窗口、compact boundary 和回退策略留到下一次 Context 主题。

---

## 6. Auto Memory：一条记忆的两次流动

Memory 有两个方向完全不同的数据流。

```text
写入路径：

用户对话
   │
   ├── 主 Agent 主动写入
   └── extractMemories 后台提取
            │
            ▼
      memory/*.md + MEMORY.md


读取路径：

MEMORY.md ──feature path──→ System Prompt（可直接注入）
memory/*.md ──相关性选择→ relevant_memories（正文按需）
                                      │
                                      ▼
                                   主模型
```

先记住三个短语：

- **索引持久化**：MEMORY.md 始终在磁盘，是否直接注入由 feature path 决定；
- **正文按需**：只有当前问题相关的记忆才进入上下文；
- **对话后沉淀**：新信息可以在一次工作结束后变成长期记忆。

---

## 7. 记忆文件长什么样

每条记忆是一个带 frontmatter 的 Markdown 文件。

```markdown
---
name: feedback_testing
description: 集成测试必须使用真实数据库，禁止 mock
type: feedback
---

集成测试必须使用真实数据库，不使用 mock。

**Why:** 上季度 mock 测试通过，但生产迁移失败。

**How to apply:** 编写集成测试时连接真实测试数据库；
如果测试环境不可用，先说明阻塞，不要静默退化成 mock。
```

这里的 `description` 不只是给人看的摘要。后面的相关性选择器正是依靠文件名和 description 判断“当前问题需要哪条记忆”。

### 四种语义类型

[`src/memdir/memoryTypes.ts`](../src/memdir/memoryTypes.ts) 定义了四种内容类型：

| 类型 | 保存什么 | 示例 |
|---|---|---|
| `user` | 用户角色、目标、知识与偏好 | 用户熟悉 Go，但第一次维护 React |
| `feedback` | 对 Agent 行为的纠正或肯定 | 不要 mock 数据库；PR 保持单一主题 |
| `project` | 无法从代码推导的项目状态与动机 | 周四起冻结非关键合并 |
| `reference` | 外部系统中的信息入口 | pipeline bug 统一在 Linear INGEST 中追踪 |

### 语义类型不等于存储路径

代码里还有一套 `User | Project | Local | Managed | AutoMem` 路径类型；启用 `TEAMMEM` feature 后还会包含 `TeamMem`。它描述“文件放在哪里”，不是“记忆表达什么”。

这两套类型解决的是不同问题，不应画成一一对应关系。

---

## 8. 一条记忆是怎样创建的

### 路径一：主 Agent 直接写入

当用户明确说“记住这条约定”，或者主 Agent 判断这是稳定且不可推导的背景，它可以直接写入 Memory 文件并维护索引。

优势是意图明确、内容及时；风险是主 Agent 可能正在忙于当前任务，漏掉值得沉淀的信息。

### 路径二：extractMemories 后台提取

一次 query loop 结束后，[`executeExtractMemories()`](../src/services/extractMemories/extractMemories.ts) 会在满足 feature gate、设置和运行模式等条件时启动后台提取。

```text
handleStopHooks
    │
    ▼
executeExtractMemories()
    │
    ├── 只处理主 Agent
    ├── 检查 auto-memory 是否启用
    ├── 计算 cursor 之后的新消息
    ├── 预注入现有 memory manifest
    └── runForkedAgent(maxTurns = 5)
             │
             ▼
       读取 / 判断 / 写入记忆
```

#### 为什么先注入 manifest

提取器会复用 [`memoryScan.ts`](../src/memdir/memoryScan.ts) 的扫描结果，把已有记忆的文件名、类型、时间和 description 放进 prompt。

它因此不必先花一轮 `ls` 才知道已有内容，也更容易更新旧记忆而不是重复创建近义文件。

#### 主 Agent 与后台提取器如何避免撞车

[`hasMemoryWritesSince()`](../src/services/extractMemories/extractMemories.ts) 会检查 cursor 之后的 assistant 消息：如果主 Agent 已经通过 Write/Edit 写入 auto-memory 路径，后台提取器本轮直接跳过并推进 cursor。

```text
主 Agent 已写 Memory？
       │
   ┌───┴───┐
   │       │
  是       否
   │       │
跳过提取   启动后台提取
```

这不是普通的“最后写入者获胜”，而是让两条写入路径在每个消息区间互斥。

#### 并发时为什么不会无限启动提取器

如果一次提取仍在进行，新的调用只保存最新 context。当前提取完成后再运行 trailing extraction，并根据已经推进的 cursor 只处理新增消息。

这是一个小但很漂亮的设计：合并中间触发，只保留信息最完整的最新上下文。

---

## 9. MEMORY.md：它是检索入口，但是否直接注入受 feature 控制

每个 Memory 目录都有一个 `MEMORY.md` 入口文件：

```markdown
# Memory Index

- [Testing Policy](feedback_testing.md) — 集成测试必须使用真实数据库
- [Release Freeze](project_release_freeze.md) — 周四开始冻结非关键合并
- [Pipeline Tracker](reference_pipeline.md) — pipeline bug 在 Linear INGEST 追踪
```

[`buildMemoryPrompt()`](../src/memdir/memdir.ts) 可以读取它并构造 Memory system prompt；[`getMemoryFiles()`](../src/utils/claudemd.ts) 也会发现 AutoMem 的入口文件。

但“MEMORY.md 始终在上下文”不是所有 feature 组合下都成立：当 `tengu_moth_copse` 开启时，[`filterInjectedMemoryFiles()`](../src/utils/claudemd.ts) 会从直接注入集合中移除 AutoMem/TeamMem 索引，改由 `findRelevantMemories` prefetch 召回 topic files。

因此更准确的说法是：**MEMORY.md 始终是持久化检索入口；它可以直接注入，也可以只服务于 memory 管理与召回，取决于当前 feature 路径。**

### 为什么索引必须短

[`memdir.ts`](../src/memdir/memdir.ts) 对入口文件设置了两个硬限制：

- 最多 200 行；
- 最多 25,000 bytes。

先按行截断，再按字节截断到合适的换行位置，并提示触发了哪个限制。

因此 `MEMORY.md` 应该是索引：一条记忆一行，名称稳定，description 具体。把正文全部堆进索引会同时伤害 prompt cache、上下文预算和召回可读性。

---

## 10. 正文如何按需进入上下文

用户在新会话中说：

> 帮我给新的订单模块补一组集成测试。

此时最重要的调用链是：

```text
startRelevantMemoryPrefetch()
          │
          ▼
collectSurfacedMemories()
          │  已出现的路径 + 会话累计 bytes
          ▼
findRelevantMemories()
          │
          ├── scanMemoryFiles()
          ├── 排除已经出现的记忆
          ├── sideQuery(Sonnet)
          └── 最多选择 5 个文件名
                    │
                    ▼
readMemoriesForSurfacing()
          │
          ▼
relevant_memories attachment
```

### 6.1 候选：扫描 header，而不是先读全文

[`scanMemoryFiles()`](../src/memdir/memoryScan.ts) 最多扫描 200 个文件，只读取前 30 行 frontmatter，返回：

- filename；
- description；
- type；
- mtime；
- absolute path。

这个阶段建立的是轻量 manifest，不把每个正文都塞给选择器。

### 6.2 排序：让小模型做高精度选择

[`findRelevantMemories()`](../src/memdir/findRelevantMemories.ts) 把用户 query、memory manifest 和最近成功使用的工具交给 side query。

选择 prompt 的策略非常克制：

- 最多返回 5 个 filename；
- 只有“明确有帮助”才选择；
- 不确定就不选；
- 可以返回空列表；
- 模型正在使用某工具时，不重复注入该工具的普通使用文档；但警告、坑和已知问题仍然可以选。

输出使用 JSON schema，并再次过滤不存在的 filename，避免模型创造路径。

这不是传统的向量检索。它是 **frontmatter manifest + LLM selector**：实现简单，description 可解释，也便于在产品还不需要大规模向量基础设施时快速演进。

### 6.3 读取：选择之后才支付正文成本

[`readMemoriesForSurfacing()`](../src/utils/attachments.ts) 对每个选中的文件执行受限读取：

- 最多 200 行；
- 最多 4,096 bytes；
- 截断时仍保留开头内容并附加提示，而不是整条丢弃；
- 最终包装成 `relevant_memories` attachment。

系统还有 60KB 的会话累计字节预算。这里是 bytes，不应直接换算成 60K tokens；实际 token 数取决于语言与 tokenizer。

### 6.4 为什么召回不会阻塞主流程

`startRelevantMemoryPrefetch()` 在用户轮开始时异步启动选择，主模型和工具可以继续工作。收集点只消费已经完成的结果；如果尚未完成，就跳过并在后续 iteration 重试。

用户按 Escape 时，child abort controller 也会取消 side query。

这让 Memory retrieval 更像“机会式预取”，而不是每轮必须等待的同步检索关卡。

### 6.5 为什么同一条记忆不会反复出现

`collectSurfacedMemories()` 扫描当前 messages 中已有的 `relevant_memories`：

- path 集合用于选择前去重；
- content length 累计值用于 60KB throttle；
- `readFileState` 还会过滤模型已经主动读取过的文件。

选择前去重很重要：否则 selector 的 5 个名额可能全被“最终还是会被过滤”的旧记忆占掉。

---

## 11. 压缩发生后，记忆去哪了

这里先只讨论 Memory 边界，不展开完整 compact 实现。

### 11.1 持久化索引仍然存在

压缩替换历史消息时，磁盘上的 `MEMORY.md` 和 topic files 没有被删除；后压缩清理还会使 instruction/memory 相关缓存失效。若当前 feature 路径直接注入索引，后续 prompt 会重新加载；若使用纯 prefetch 路径，topic files 仍可再次被 selector 发现。

### 11.2 召回的正文附件会离开当前 transcript

`relevant_memories` 是消息附件。压缩后，旧附件不再作为原始消息留在压缩后的 transcript 中；有用信息是否进入摘要，取决于压缩内容。

### 11.3 下一轮可以重新召回

去重路径和会话字节数不是维护在另一套永久 session state 中，而是通过扫描当前 messages 得到。

压缩后旧附件已经不在 transcript：

- 同一条记忆可以再次成为候选；
- 旧附件的累计 bytes 不再占用新 transcript 的召回预算；
- 持久化文件仍然是事实来源。

这是 [`collectSurfacedMemories()`](../src/utils/attachments.ts) 注释中明确说明的设计目标：compact 会自然重置去重与累计预算。

```text
压缩前：[可选 MEMORY.md 注入] + relevant_memories + 对话历史
                         │
                         ▼ compact
压缩后：[可选 MEMORY.md 注入] + 摘要
                         │
                         ▼ 新用户查询
         findRelevantMemories() 可再次召回正文
```

下一次 Context 分享可以继续追问：摘要如何生成、哪些附件会重建、最近文件和 Skill 如何恢复、自动压缩何时触发。

---

## 12. 回放：这条测试约定的一生

### 创建

```text
用户：以后不要 mock 数据库，上次出过事故。
```

主 Agent 直接保存，或者 `extractMemories` 在 query 结束后识别为 `feedback`。

### 持久化

```text
feedback_testing.md
  rule: 集成测试使用真实数据库
  why: mock 与生产迁移行为不一致
  how: 环境不可用时报告阻塞，不静默退化

MEMORY.md
  - [Testing Policy](feedback_testing.md) — 集成测试必须使用真实数据库
```

### 新会话加载

在直接注入索引的 feature 路径中，system prompt 出现 MEMORY.md；在 prefetch 路径中，选择器通过 memory manifest 发现 Testing Policy。两者都不会一开始把所有 topic 正文塞给主模型。

### 按需召回

```text
用户：给订单模块补集成测试。
```

selector 根据 query 和 description 选中 `feedback_testing.md`，正文作为 `relevant_memories` 注入。

### 执行

Agent 连接真实测试数据库；如果环境不可用，根据 Why/How 判断应说明阻塞，而不是为了“测试通过”偷偷换成 mock。

### 压缩与重现

对话变长后发生压缩，旧附件离开 transcript。几轮后用户再次讨论集成测试，同一持久化文件可以被重新召回。

一条好 Memory 的价值不只是让 Agent 记住“做什么”，还要保留足够的 **Why**，让未来 Agent 能判断边界情况。

---

## 13. 源码阅读路线

如果准备在分享后带大家读代码，建议按数据流而不是按目录字母顺序：

1. [`src/utils/claudemd.ts`](../src/utils/claudemd.ts)  
   先看 CLAUDE.md/rules 的发现顺序、include、条件规则和注入。
2. [`src/tools/AgentTool/agentMemory.ts`](../src/tools/AgentTool/agentMemory.ts) 与 [`loadAgentsDir.ts`](../src/tools/AgentTool/loadAgentsDir.ts)  
   看 agent definition 的 `memory:` 如何产生独立持久化目录。
3. [`src/services/SessionMemory/sessionMemory.ts`](../src/services/SessionMemory/sessionMemory.ts)、[`sessionMemoryUtils.ts`](../src/services/SessionMemory/sessionMemoryUtils.ts) 与 [`sessionMemoryCompact.ts`](../src/services/compact/sessionMemoryCompact.ts)  
   看当前会话摘要如何增量生成、记录消息边界并成为 compact 的预计算输入。
4. [`src/memdir/memoryTypes.ts`](../src/memdir/memoryTypes.ts)  
   先看什么值得保存，以及四种语义类型。
5. [`src/services/extractMemories/extractMemories.ts`](../src/services/extractMemories/extractMemories.ts)  
   看后台提取、cursor、互斥、并发合并和权限边界。
6. [`src/memdir/memdir.ts`](../src/memdir/memdir.ts)  
   看 MEMORY.md 如何进入 prompt，以及入口文件限制。
7. [`src/memdir/memoryScan.ts`](../src/memdir/memoryScan.ts)  
   看轻量 manifest 如何构建。
8. [`src/memdir/findRelevantMemories.ts`](../src/memdir/findRelevantMemories.ts)  
   看 side query 的选择 prompt 和结构化输出。
9. [`src/utils/attachments.ts`](../src/utils/attachments.ts)  
   看 prefetch、读取预算、attachment、去重和 compact 自然重置。
10. [`src/services/compact/compact.ts`](../src/services/compact/compact.ts)  
   最后只看 `shouldExcludeFromPostCompactRestore()` 等 Memory 接口，完整 compact 留到下一次。

### 当前 main 分支的关键常量

| 常量/行为 | 当前值 | 文件 |
|---|---:|---|
| MEMORY.md 行数上限 | 200 行 | `memdir.ts` |
| MEMORY.md 字节上限 | 25,000 bytes | `memdir.ts` |
| 扫描 memory 文件数 | 200 | `memoryScan.ts` |
| frontmatter 扫描范围 | 前 30 行 | `memoryScan.ts` |
| selector 选择上限 | 5 条 | `findRelevantMemories.ts` |
| 单条正文读取 | 200 行 / 4,096 bytes | `attachments.ts` |
| 会话累计召回预算 | 60KB | `attachments.ts` |
| 后台提取最大轮数 | 5 turns | `extractMemories.ts` |
| Session Memory 初始化 | 10,000 tokens | `sessionMemoryUtils.ts` |
| Session Memory 更新增长 | 5,000 tokens | `sessionMemoryUtils.ts` |
| Session Memory 工具调用信号 | 3 calls | `sessionMemoryUtils.ts` |

这些值是实现细节，不是 Memory 的永恒定义。分享时应把它们标为“当前 main 分支”，避免把配置或版本行为讲成产品不变量。

---

## 14. 我们可以怎样继续改进

当前实现已经拥有清晰、务实的最小闭环，但也留下了值得讨论的方向：

### 召回解释

selector 当前只返回 filename。未来可以在 debug 或产品界面显示：

- 为什么选择这条记忆；
- 来自哪次 session / message；
- 本次回答是否真正使用了它。

### 来源可追溯

Memory 文件当前更像提炼后的知识卡片。增加 source session、source message 或证据片段，可以让纠错、审计和冲突处理更可靠。

### 冲突和时间

项目状态会变化。未来不仅要解决“召回什么”，还要解决：

- 新旧事实冲突时谁覆盖谁；
- 哪些事实只在某段时间有效；
- private 与 team memory 冲突时如何解释优先级。

### 从文件索引走向 LLM Wiki

当记忆数量继续增长，可以逐步增加 backlinks、tags、source 和关联关系；先成为可读、可解释的 LLM Wiki，再决定是否需要向量检索或时间知识图谱。

---

## 总结

```text
Memory 不是“更多聊天记录”

不可推导的信息
      │
      ▼
结构化 Markdown + MEMORY.md
      │
      ├── 指令/索引按 feature path 注入
      └── topic 正文经 selector 按需进入上下文
                         │
                         ▼
                 帮助主模型做当前决策
                         │
                         ▼
            compact 后仍可从持久化文件重新召回
```

三个 takeaway：

1. **Instruction、Auto、Agent、Session Memory 同属持久上下文家族，但作用域和加载策略不同。**
2. **显式规则分层加载，长期记忆按需召回，专家经验按身份隔离，会话状态滚动摘要。**
3. **Session Memory 为 compact 提供预计算摘要；压缩会清理旧附件，但不会删除长期持久化文件。**

下一次 Context 主题可以从这里接着问：当工作台真的放不下时，系统到底删了什么、总结了什么，又重建了什么？
