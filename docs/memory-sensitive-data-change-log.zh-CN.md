# 记忆敏感信息处理修改说明

## 修改摘要

本次修改为记忆的提取、生成/持久化和召回链路增加统一敏感信息策略。默认对敏感值进行 `[REDACTED]` 替换，也可以配置为拒绝包含敏感信息的记忆写入。

## 新增文件

### `src/memdir/sensitiveMemory.ts`

新增共享策略模块，提供：

- 内置高置信凭据规则。
- 自定义敏感词读取与字面量安全匹配。
- `redact` / `exclude` 模式解析。
- 普通文本脱敏。
- Write/Edit 工具输入过滤。
- 提取代理使用的敏感信息提示词。

### `src/memdir/sensitiveMemory.test.ts`

新增 4 组单元测试，覆盖自定义词、内置凭据、工具输入过滤及模式解析。

### 文档

- `docs/memory-sensitive-data-design.zh-CN.md`：完整设计、边界、数据流和后续演进。
- `docs/memory-sensitive-data-change-log.zh-CN.md`：本次文件级修改及验证记录。
- `docs/memory-sensitive-data.md`：面向使用者的简明配置说明。

## 修改文件

| 文件 | 修改内容 |
| --- | --- |
| `src/services/extractMemories/extractMemories.ts` | 在自动记忆及 AutoDream 共用的工具权限入口过滤 Write/Edit；`exclude` 模式拒绝命中写入。 |
| `src/services/extractMemories/prompts.ts` | 向后台提取代理加入敏感信息处理约束。 |
| `src/memdir/memoryTypes.ts` | 在主记忆提示词的“不应保存”规则中加入凭据和用户指定敏感词。 |
| `src/memdir/memoryScan.ts` | frontmatter 描述在进入候选清单前脱敏；`exclude` 模式排除命中文件。 |
| `src/memdir/findRelevantMemories.ts` | 相关性选择前脱敏用户查询。 |
| `src/utils/attachments.ts` | 记忆正文注入模型上下文前执行最终脱敏。 |
| `src/services/SessionMemory/sessionMemory.ts` | SessionMemory Edit 写入前应用相同策略。 |
| `src/services/SessionMemory/sessionMemoryUtils.ts` | SessionMemory 读取并用于续接前执行脱敏。 |

## 配置

```powershell
# 逗号或换行分隔；按字面量、大小写不敏感匹配
$env:CLAUDE_CODE_MEMORY_SENSITIVE_TERMS='项目代号,客户甲'

# 默认 redact；严格环境可设为 exclude
$env:CLAUDE_CODE_MEMORY_SENSITIVE_ACTION='redact'
```

## 行为变化

### 默认行为

- 即使不配置自定义词，凭据、私钥和常见 Token 也会被脱敏。
- 命中内容替换为 `[REDACTED]`，非敏感上下文继续保存和召回。
- 历史文件不会被原地修改，但召回时不会把命中值注入上下文。

### 严格模式

- 生成的 Write/Edit 内容命中敏感规则时，本次写入被拒绝。
- frontmatter 描述命中的文件不会参与自动相关性召回。
- 最终正文仍执行脱敏，以防历史或人工文件漏过索引检查。

## 验证记录

执行命令：

```powershell
bun test src/memdir/sensitiveMemory.test.ts
bun run build:dev
```

结果：

- 单元测试：4 项通过，0 项失败。
- 开发构建：成功生成开发 CLI。
- `tsc --noEmit`：仓库当前存在大量与本功能无关的缺失快照模块和基线类型错误，因此不能作为本次修改的通过门槛；本次开发构建已通过。

## 已知限制

- 当前自定义配置通过环境变量提供，尚未接入 Settings UI。
- 不对原始会话日志做脱敏。
- 不默认识别宽泛 PII，以避免姓名、邮箱和电话号码误杀。
- 不自动改写已有记忆文件；旧文件在召回出口得到保护。

## 回滚方式

回滚时应同时移除共享策略模块及上述八个调用点，避免只移除写入过滤却保留不一致的召回规则。配置环境变量本身不会修改磁盘数据，删除环境变量即可恢复仅使用内置凭据规则的默认行为。
