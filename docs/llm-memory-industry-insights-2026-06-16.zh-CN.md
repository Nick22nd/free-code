# 大模型记忆：研究、产品与工程实践洞察

日期：2026-06-16

## 结论摘要

大模型记忆正在从“把聊天历史塞回上下文”升级为一套独立的产品与基础设施层：它包含记忆抽取、结构化存储、检索、合并、遗忘、来源解释、权限治理和评估闭环。最近的研究和产品实践基本达成了一个共识：长期记忆不是更大的上下文窗口，而是可治理、可召回、可更新、可删除的外部状态。

对本项目而言，现有 `memdir`、`SessionMemory`、`teamMemorySync` 和 `CLAUDE.md`/auto-memory 体系已经具备文件式长期记忆、会话摘要、团队共享与安全边界。最值得优先引入的不是新数据库，而是三类能力：记忆来源与使用可解释、后台整理与冲突合并、面向记忆质量的评估与遥测。

## 行业信号

### 1. 产品正在把“记忆”做成可解释的个性化层

OpenAI 的 ChatGPT Memory 已经从早期“保存的记忆”扩展为持续更新的 memory summary，并且把记忆来源暴露给用户：过去聊天、保存记忆、自定义指令、文件、连接应用等都可能成为个性化来源。它还强调用户可以查看、编辑、删除、关闭记忆，并能看到某次回答使用了哪些来源。这个方向说明，记忆能力的竞争点不只是召回准确率，而是“用户是否理解并控制系统为什么记得、何时使用、如何忘记”。

Claude Code 的公开文档则把记忆拆成两套互补机制：用户/团队写的 `CLAUDE.md` 指令，以及 Claude 自己积累的 auto memory。它明确提醒这些记忆是上下文，不是强制执行配置；必须强制执行的规则应走 hooks 或 settings。这一点对 coding agent 很关键：记忆适合影响行为，不能替代权限、沙箱和安全策略。

### 2. 框架侧形成三分法：语义、情节、程序性记忆

LangGraph 文档把长期记忆分成 semantic、episodic、procedural 三类：事实、经历、规则。它也强调记忆更新可以在主路径同步发生，也可以异步后台发生。这个分类很实用，因为很多产品失败不是“没记住”，而是把不同记忆混在一起：用户偏好、项目事实、成功/失败案例、工具调用经验、系统规则需要不同生命周期和权限。

本项目目前的 `user / feedback / project / reference` 分类更偏 coding-agent 场景，已经很实用。但还缺一个明确的“episodic examples”层：例如“某类任务曾经怎么做成功/失败”的少样本案例，它不应直接变成规则，也不应混入用户画像。

### 3. 研究侧从向量检索走向动态图与自组织记忆

Mem0 论文把生产级长期记忆定义为动态抽取、整合、检索，并报告相比全上下文方法可显著降低延迟和 token 成本；其 graph memory 版本尝试捕捉记忆间关系。Zep/Graphiti 的论文进一步把企业记忆建模为时间知识图谱，强调动态业务数据、对话数据和历史关系。A-MEM 则借鉴 Zettelkasten，把新记忆写入时自动生成关键词、标签和链接，并允许旧记忆随新信息演化。

这些工作的共同点是：单纯“相似度搜索 markdown 片段”会遇到关系缺失、时间冲突和过期事实问题。下一代记忆系统会维护记忆之间的关系、来源、时间、置信度和冲突状态。

### 4. 隐私与用户代理权成为硬约束

2026 年关于 ChatGPT memory 的用户研究指出，记忆可能包含大量个人数据和心理画像，而且很多记忆由系统单方面创建。无论具体产品如何实现，这都提示了一个产品风险：自动记忆越强，越需要让用户知道“它记住了什么、为什么记、从哪里来、如何删除、删除是否彻底”。

对团队记忆尤其要谨慎。团队共享记忆如果混入个人偏好、秘密、客户信息或短期状态，会带来协作污染和合规风险。本项目已有 `teamMemSecretGuard`、scope guidance 和 stale-memory 提醒，方向正确，可以继续强化。

## 对本项目的现状判断

项目已有的基础不错：

- `src/memdir` 提供长期文件式记忆，`MEMORY.md` 作为索引，具体记忆分散到 topic markdown。
- `src/memdir/memoryTypes.ts` 已经定义 `user / feedback / project / reference`，并明确“不要保存可由代码、git、文档推导出的信息”。
- `src/memdir/findRelevantMemories.ts` 已经有基于 header/description 的 LLM 选择器，且限制最多 5 条，避免过度注入。
- `src/services/SessionMemory/sessionMemory.ts` 已经有后台 forked agent 做会话摘要，且按 token 与 tool-call 阈值触发。
- `src/services/teamMemorySync` 已有团队共享、增量同步、冲突处理、大小限制和 secret 扫描。
- `docs/memory-architecture.zh-CN.md` 已经把 auto-memory、team memory、agent memory、session memory、CLAUDE.md 的差异写清楚。

短板也比较明确：

- 记忆被使用时，用户侧解释仍偏弱。OpenAI 的 Memory Sources 模式值得借鉴。
- 记忆质量评估主要依赖 prompt 和遥测，缺少离线评测集：召回正确率、误召回率、陈旧事实使用率、敏感信息误写率。
- 记忆结构仍以 markdown/frontmatter 为主，适合透明与可编辑，但对跨记忆关系、时间冲突、同义合并支持有限。
- session memory 和 long-term memory 之间的晋升机制还可以更清晰：哪些会话摘要能变成长期记忆，哪些只能用于 compaction。
- team memory 虽有同步和 secret guard，但还可以加强“个人偏好不得进入团队记忆”的检测和审计。

## 建议引入项

### P0：记忆使用来源解释

在每次注入或选择长期记忆时，保留一份轻量 trace：文件路径、frontmatter name/type、mtime、选择理由、是否来自 private/team/session。UI 可先做成调试面板或回答后的折叠提示，不必一开始完整产品化。

价值：提升用户信任，方便排查“为什么它提到了这个旧事实”，也能为后续 eval 收集样本。

可落点：

- `src/memdir/findRelevantMemories.ts` 返回结果增加 optional reason。
- 在调用 `sideQuery` 的 JSON schema 中要求输出 `{ filename, reason }`。
- 在消息渲染或 memory notification 中暴露最近使用的 memory source。

### P0：记忆质量评估集

建立一个小型 eval 套件，覆盖以下 case：

- 应召回：用户偏好、项目背景、外部 reference。
- 不应召回：无关关键词、已被要求 ignore 的记忆、过期文件路径。
- 应验证：记忆提到函数/文件/flag 时，必须 grep 或读文件。
- 应拒写：secret、短期任务日志、可从 repo 推导的架构信息。
- team/private scope：个人沟通偏好不能保存到 team memory。

价值：这个项目的 memory prompt 已经很细，继续堆 prompt 的边际收益会下降；eval 可以防止后续改动把行为弄坏。

可落点：

- 新增 `src/memdir/__tests__` 或现有测试目录中的 fixture。
- 复用 `scanMemoryFiles`、`formatMemoryManifest`、`selectRelevantMemories` 的边界逻辑。
- 为 prompt 行为做少量 golden tests。

### P1：后台记忆整理器

增加一个低频后台任务，对 memory dir 做整理：检测重复、冲突、过期、太长、缺少 `type`、描述不准、同主题可合并项。先只生成建议，不自动改写；后续可加用户确认或 auto mode。

价值：OpenAI 新 memory system 和 Letta sleep-time agents 都在强调后台整理。长期记忆的主要退化不是写不进去，而是越积越乱、互相矛盾、过期后还被使用。

可落点：

- 新建 `src/memdir/memoryConsolidation.ts`。
- 输出 consolidation report，或通过 `/memory` 增加“review memory health”入口。
- 对 team memory 默认只建议，不自动写。

### P1：显式区分 episodic examples

新增一种记忆类型或子类型，用来保存“过去成功/失败案例”的可检索 few-shot，而不是把它们写成硬规则。比如：

```yaml
type: example
task_kind: pr-review
outcome: success
```

价值：coding agent 很多能力来自“类似任务怎么处理过”，但把案例硬编码成规则容易过拟合。episodic examples 能给模型示例，又保持规则层干净。

注意：这项需要谨慎，因为现有 `WHAT_NOT_TO_SAVE` 明确排除 debugging fix recipes。可以先限定为“用户明确认可且不可从代码/git推导的协作模式案例”，不要保存普通 bug 修复步骤。

### P1：记忆 freshness 与 volatility

已有 `memoryAge.ts` 和 staleness prompt，可继续做结构化：为 `project` 类型增加 optional `valid_until`、`last_verified_at`、`source`、`confidence`。对 `reference` 可要求 `last_checked_at`。

价值：最近研究里的时间知识图谱方向说明，时间不是普通 metadata。项目事实会过期，用户长期偏好相对稳定，外部链接可能失效；不同类型应有不同默认半衰期。

### P2：关系索引，而不是立刻上图数据库

先不要急着引入 Neo4j/Graphiti/向量库。可以在 markdown frontmatter 中加入轻量关系：

```yaml
related:
  - testing-policy
supersedes:
  - old-db-mocking-rule
conflicts_with:
  - legacy-ci-note
```

价值：保留文件式透明性，同时为后续图检索铺路。A-MEM/Zep 的启发是关系重要，但本项目未必需要马上付出 infra 成本。

### P2：team memory 审计与权限分层

增强团队共享记忆的审计能力：谁/哪个 agent 写入、何时同步、是否跳过 secret、是否从 private 候选升级而来。对于 Enterprise/managed settings 场景，可支持只读 team memory 或 require approval before team write。

价值：团队记忆是最高杠杆，也是最高风险。它应该更像共享知识库，而不是所有 agent 的自动便签。

## 不建议短期引入

- 不建议立刻把所有记忆迁移到向量数据库。现有文件式记忆透明、可 diff、可手工修复，对 coding agent 很珍贵。
- 不建议让 agent 无约束重写自己的 system prompt。procedural memory 很强，但风险高；更适合作为建议或受控 patch。
- 不建议把完整会话长期保存为可检索记忆。它会增加隐私、成本和干扰；应继续坚持抽取后的高信号记忆。
- 不建议把 `CLAUDE.md` 当作强制策略。安全与权限仍应走 hooks、settings、sandbox。

## 一个务实路线图

1. 两周内：给 `findRelevantMemories` 增加选择理由和来源 trace；为 `/memory` 或 debug 输出展示最近召回的记忆。
2. 一个月内：建立 memory eval fixture，覆盖 recall、ignore、staleness、scope、secret、do-not-save。
3. 一个季度内：实现 memory health/consolidation report，先只建议重复、冲突、过期、描述不准。
4. 后续：引入 lightweight relationship frontmatter；观察是否真有必要升级到图索引或向量检索。

## 参考来源

- OpenAI Help Center: [Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq)
- Anthropic Claude Code Docs: [How Claude remembers your project](https://code.claude.com/docs/en/memory)
- LangGraph Docs: [Memory overview](https://docs.langchain.com/oss/python/concepts/memory)
- Letta Docs: [Introduction to Stateful Agents](https://docs.letta.com/guides/core-concepts/stateful-agents)
- Mem0 Docs: [Platform overview](https://docs.mem0.ai/platform/overview)
- Chhikara et al., 2025: [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/abs/2504.19413)
- Xu et al., 2025: [A-MEM: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110)
- Rasmussen et al., 2025: [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)
- Dash et al., 2026: [The Algorithmic Self-Portrait: Deconstructing Memory in ChatGPT](https://arxiv.org/abs/2602.01450)
- Tummalapenta and Addanki, 2026: [Memory Architectures for Multi-Turn Text-to-SQL](https://arxiv.org/abs/2605.26394)
