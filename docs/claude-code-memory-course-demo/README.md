# 课程代码：可追溯的 Claude Code Memory

这是一份可以直接搬进课程目录的单文件教学 Demo。它延续 [`s09_memory`](https://github.com/shareAI-lab/learn-claude-code/tree/main/s09_memory) 的核心结构：

```text
Markdown 主题文件 → MEMORY.md 索引 → 按需召回 → 回合后提取 → 定期整理
```

在此基础上增加四个适合继续讲解的点：

1. 每条记忆记录 `source_session` 和 `source_message`；
2. 召回结果显示“为什么选中”；
3. Session Memory 单独保存当前任务状态；
4. Dream 使用临时目录完成安全替换，失败时保留原文件。

## 运行

要求 Python 3.10+。

```bash
pip install anthropic python-dotenv
export ANTHROPIC_API_KEY=your-key
export MODEL_ID=claude-sonnet-4-5
python code.py
```

PowerShell：

```powershell
pip install anthropic python-dotenv
$env:ANTHROPIC_API_KEY = "your-key"
$env:MODEL_ID = "claude-sonnet-4-5"
python .\code.py
```

如使用兼容 Anthropic Messages API 的服务，可以额外设置 `ANTHROPIC_BASE_URL`。

## 离线自检

无需安装依赖，也无需 API Key：

```bash
python code.py --self-test
```

它会在临时目录验证：

```text
写入 → 索引 → 召回 → 来源追踪 → Session Memory → 删除
```

## 演示脚本

启动后依次输入：

```text
记住：这个项目的集成测试不要 mock 数据库，因为之前 mock 掩盖过迁移错误。
/memory
/trace real-database-tests.md
/new
请帮我设计一条数据库集成测试。
/session
```

可观察到：

- `.memory/*.md` 保存正文与来源；
- `.memory/MEMORY.md` 只保存短索引；
- 新会话根据 `name + description` 选择最多 5 条相关记忆；
- `[Recall]` 输出选择原因；
- `/trace` 可以从来源 id 回到 `.transcripts/<session>.jsonl` 中的原始消息；
- `.sessions/<session-id>/session-memory.md` 只服务当前会话连续性。

## 命令

| 命令 | 作用 |
| --- | --- |
| `/memory` | 查看短索引 |
| `/trace <filename>` | 查看记忆正文与来源 |
| `/session` | 查看当前 Session Memory |
| `/dream` | 达到阈值后合并、去重记忆 |
| `/new` | 模拟开启新会话 |
| `/exit` | 退出 |

## 代码阅读顺序

建议课堂上按数据流讲，而不是从第一行顺序念：

1. `MemoryStore.write()`：主题文件和来源字段；
2. `MemoryStore.rebuild_index()`：正文与索引分离；
3. `MemoryEngine.recall()`：LLM selector 与关键词降级；
4. `MemoryEngine.render_recalled()`：召回理由和来源进入上下文；
5. `MemoryEngine.extract()`：回合结束后的保守提取；
6. `SessionJournal`：当前会话与长期记忆分工；
7. `MemoryEngine.dream()`：安全整理；
8. `CodingAgent.answer()`：把各阶段串起来。

## 与生产实现的边界

这是教学代码，刻意省略了生产系统中的 feature flag、异步 prefetch、文件锁、Team Memory 远端同步、敏感信息扫描、精确 token 预算和受限 forked agent。课程里应明确：

> Demo 展示机制，生产实现负责并发、安全、预算和兼容性。
