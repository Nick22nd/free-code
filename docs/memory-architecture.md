# Memory Architecture

This document explains the memory systems in this repository from a secondary-development perspective: mechanisms, storage locations, lifecycle, interactions, and related code.

## Overview

The project has several memory-like systems. They overlap in purpose, but they are not the same subsystem:

- `CLAUDE.md` instruction memory: explicit instruction files loaded into context.
- Auto-memory / memdir: persistent file-based memory scoped to the current project.
- Team memory: shared memory under the auto-memory directory, synced through a server API.
- Agent memory: persistent memory scoped to a custom agent type.
- Session memory: per-session summary used mainly for compaction and current-conversation continuity.

For most long-term behavior customization, the main subsystem is auto-memory under `src/memdir`.

## Storage Locations

The config home is resolved by `getClaudeConfigHomeDir()` in `src/utils/envUtils.ts`.

Default:

```text
~/.claude
```

Override:

```text
CLAUDE_CONFIG_DIR
```

### Auto-Memory

Auto-memory path is computed in `src/memdir/paths.ts`.

Default shape:

```text
<configHome>/projects/<sanitized canonical git root>/memory/
```

Entrypoint:

```text
<autoMemoryDir>/MEMORY.md
```

`MEMORY.md` is an index, not the full memory store. The detailed memories live in topic `.md` files in the same directory.

Example memory file:

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

Supported `type` values are defined in `src/memdir/memoryTypes.ts`:

```text
user
feedback
project
reference
```

### Team Memory

Team memory is a subdirectory of auto-memory:

```text
<autoMemoryDir>/team/
<autoMemoryDir>/team/MEMORY.md
```

Path helpers live in `src/memdir/teamMemPaths.ts`.

Team memory is feature-gated behind `TEAMMEM` and also requires auto-memory to be enabled.

### Agent Memory

Agent memory is handled by `src/tools/AgentTool/agentMemory.ts`.

Scopes:

```text
user:    <memoryBase>/agent-memory/<agentType>/
project: <cwd>/.claude/agent-memory/<agentType>/
local:   <cwd>/.claude/agent-memory-local/<agentType>/
```

In remote mode, local agent memory may be redirected under:

```text
CLAUDE_CODE_REMOTE_MEMORY_DIR/projects/<project>/agent-memory-local/<agentType>/
```

### Session Memory

Session memory is current-session state, not durable cross-session knowledge.

Path:

```text
<configHome>/projects/<sanitized cwd>/<sessionId>/session-memory/summary.md
```

The path helpers are in `src/utils/permissions/filesystem.ts`:

- `getSessionMemoryDir()`
- `getSessionMemoryPath()`

Implementation lives in `src/services/SessionMemory/sessionMemory.ts`.

### CLAUDE.md Memory

Traditional instruction memory is discovered by `src/utils/claudemd.ts`.

Common locations:

```text
User:    <configHome>/CLAUDE.md
Project: <cwd>/CLAUDE.md
Project: <cwd>/.claude/CLAUDE.md
Project: <cwd>/.claude/rules/*.md
Local:   <cwd>/CLAUDE.local.md
Managed: managed settings path / CLAUDE.md
```

Path selection for memory types is in `src/utils/config.ts`.

## Enablement

Auto-memory is enabled by default.

The enablement priority is implemented in `isAutoMemoryEnabled()` in `src/memdir/paths.ts`:

1. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=true` disables auto-memory.
2. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=false` forces it on.
3. `CLAUDE_CODE_SIMPLE` / `--bare` disables it.
4. Remote mode without `CLAUDE_CODE_REMOTE_MEMORY_DIR` disables it.
5. `autoMemoryEnabled` in settings controls it.
6. Otherwise it is enabled.

Auto-memory directory overrides:

- `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`: full path override, mainly for SDK/Cowork.
- `autoMemoryDirectory` in trusted settings sources: policy, flag, local, or user settings.

Project settings are intentionally excluded from `autoMemoryDirectory` for security, so a checked-in repo cannot redirect memory writes to sensitive locations.

## Startup And Context Injection

The system prompt includes memory behavior instructions through:

- `src/constants/prompts.ts`
- `src/memdir/memdir.ts`

Main function:

```ts
loadMemoryPrompt()
```

`loadMemoryPrompt()`:

- Checks whether auto-memory is enabled.
- Creates the memory directory if needed.
- Builds either an auto-only prompt or a combined auto + team memory prompt.
- Adds instructions for when and how to save memories.
- In KAIROS mode, switches to append-only daily log behavior.

The traditional instruction files and memory indexes are loaded into user context through:

- `src/context.ts`
- `src/utils/claudemd.ts`

Important functions:

```ts
getMemoryFiles()
getClaudeMds()
filterInjectedMemoryFiles()
```

`getMemoryFiles()` discovers and processes `CLAUDE.md`, `.claude/rules/*.md`, `CLAUDE.local.md`, auto-memory `MEMORY.md`, and team-memory `MEMORY.md`.

It also handles:

- `@include` directives.
- Frontmatter stripping.
- HTML comment stripping.
- `MEMORY.md` truncation.
- Cache invalidation.

## Recall / Read Path

Auto-memory topic files are not all injected into the prompt. Instead, relevant files are selected per turn.

Flow:

1. `src/query.ts` starts memory prefetch with `startRelevantMemoryPrefetch()`.
2. `src/utils/attachments.ts` scans for the last user message.
3. `src/memdir/memoryScan.ts` scans memory topic files and reads frontmatter.
4. `src/memdir/findRelevantMemories.ts` asks a side query to select up to 5 relevant memories.
5. Selected files are read and injected as `relevant_memories` attachments.

Important functions:

```ts
startRelevantMemoryPrefetch()
findRelevantMemories()
scanMemoryFiles()
readMemoriesForSurfacing()
collectSurfacedMemories()
```

The scan excludes `MEMORY.md`. `MEMORY.md` is treated as the always-loaded index; detailed topic files are recalled only when relevant.

Recalled memories include freshness text from `src/memdir/memoryAge.ts`, so stale memories are presented as stale context rather than current truth.

## Write Path

There are two write paths.

### Direct Main-Agent Writes

The main agent can directly write memory files because `loadMemoryPrompt()` tells it how to do so.

The prompt says:

- If the user explicitly asks to remember something, save it immediately.
- If the user asks to forget something, find and remove the relevant entry.
- Save one topic per file.
- Keep `MEMORY.md` as a concise index.
- Avoid duplicates.
- Update stale or wrong memories.

Prompt construction is in:

```text
src/memdir/memdir.ts
src/memdir/teamMemPrompts.ts
src/memdir/memoryTypes.ts
```

### Background Extraction

If the main agent does not write memory, a background fork can extract durable memories at turn end.

Core files:

```text
src/services/extractMemories/extractMemories.ts
src/services/extractMemories/prompts.ts
src/query/stopHooks.ts
src/utils/backgroundHousekeeping.ts
```

Lifecycle:

1. `startBackgroundHousekeeping()` calls `initExtractMemories()`.
2. At turn end, `handleStopHooks()` calls `executeExtractMemories()`.
3. `executeExtractMemories()` forks a cache-safe background agent.
4. The forked agent receives a memory extraction prompt.
5. The forked agent may read/search memory and write only inside the memory directory.
6. If files were written, a `memory_saved` system message is emitted.

Important protections:

- Does not run for subagents.
- Does not run if auto-memory is disabled.
- Does not run in remote mode.
- Skips extraction when the main conversation already wrote memory.
- Allows only read/search tools and memory-directory writes.
- Coalesces overlapping runs and runs one trailing extraction if needed.

## Team Memory Sync

Team memory is synced by `src/services/teamMemorySync`.

Key files:

```text
src/services/teamMemorySync/index.ts
src/services/teamMemorySync/watcher.ts
src/services/teamMemorySync/types.ts
src/services/teamMemorySync/secretScanner.ts
src/services/teamMemorySync/teamMemSecretGuard.ts
```

Startup:

```ts
startTeamMemoryWatcher()
```

Sync behavior:

- Initial pull from server.
- File watcher starts on the local team memory directory.
- Local writes schedule a push.
- Pull writes server entries to local disk.
- Push uploads only changed entries using content hashes.
- ETag / `If-Match` handles conflicts.
- Local deletion does not delete remote data; the next pull restores it.
- Server wins on pull.
- Local changes are preserved during push conflict retries as much as possible.
- Secret scanner skips files containing detected secrets.

The hook that notices team memory writes is in `src/utils/sessionFileAccessHooks.ts`.

## Agent Memory

Agent memory gives custom agents their own persistent memory directory.

Core file:

```text
src/tools/AgentTool/agentMemory.ts
```

Important functions:

```ts
getAgentMemoryDir()
getAgentMemoryEntrypoint()
isAgentMemoryPath()
loadAgentMemoryPrompt()
```

`loadAgentMemoryPrompt()` builds a memory prompt using the same `buildMemoryPrompt()` helper used by auto-memory, but adds scope-specific guidance:

- user scope: keep learnings general across projects.
- project scope: tailor memories to the project and version control.
- local scope: tailor memories to the project and machine.

Agent creation UI includes a memory step in:

```text
src/components/agents/new-agent-creation/wizard-steps/MemoryStep.tsx
```

## Session Memory

Session memory summarizes the current conversation into a session-local markdown file.

Core file:

```text
src/services/SessionMemory/sessionMemory.ts
```

It is initialized by:

```ts
initSessionMemory()
```

It registers a post-sampling hook and updates `summary.md` after thresholds are met.

The feature is related to auto-compact. It is not intended as long-term user/project memory.

Manual extraction is exposed through:

```ts
manuallyExtractSessionMemory()
```

This is used by summary-related flows.

## UI And Commands

`/memory` command:

```text
src/commands/memory/index.ts
src/commands/memory/memory.tsx
```

The memory selector UI:

```text
src/components/memory/MemoryFileSelector.tsx
```

It can show:

- User memory.
- Project memory.
- Local memory.
- Auto-memory folder.
- Team memory folder.
- Active agent memory folders.
- Auto-memory toggle.
- Auto-dream toggle.

When a memory file is selected, it is opened through the configured editor:

```text
$VISUAL
$EDITOR
default editor fallback
```

Memory update notifications are in:

```text
src/components/memory/MemoryUpdateNotification.tsx
src/components/messages/SystemTextMessage.tsx
```

## Permissions And Safety

Memory paths often live under `.claude`, which is considered a dangerous directory. The project has explicit internal read/write permissions for managed memory files.

Core file:

```text
src/utils/permissions/filesystem.ts
```

Important checks:

```ts
isAutoMemPath()
isAgentMemoryPath()
isSessionMemoryPath()
checkReadableInternalPath()
```

Auto-memory gets a special write carve-out unless `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` is used. The override can point anywhere, so writes go through normal permission flow unless the SDK caller grants permission.

Team memory path safety is stricter:

```text
src/memdir/teamMemPaths.ts
```

It protects against:

- Null bytes.
- Absolute-path keys.
- Backslash traversal.
- URL-encoded traversal.
- Unicode normalization traversal.
- Symlink escape.
- Dangling symlink writes.

Memory file detection for collapsed UI / telemetry lives in:

```text
src/utils/memoryFileDetection.ts
```

## Important Code Map

Path and enablement:

```text
src/memdir/paths.ts
src/memdir/teamMemPaths.ts
src/tools/AgentTool/agentMemory.ts
src/utils/envUtils.ts
src/utils/config.ts
```

Prompt construction:

```text
src/memdir/memdir.ts
src/memdir/teamMemPrompts.ts
src/memdir/memoryTypes.ts
src/constants/prompts.ts
src/QueryEngine.ts
```

Instruction and index loading:

```text
src/utils/claudemd.ts
src/context.ts
```

Relevant memory recall:

```text
src/query.ts
src/utils/attachments.ts
src/memdir/memoryScan.ts
src/memdir/findRelevantMemories.ts
src/memdir/memoryAge.ts
```

Background extraction:

```text
src/utils/backgroundHousekeeping.ts
src/query/stopHooks.ts
src/services/extractMemories/extractMemories.ts
src/services/extractMemories/prompts.ts
```

Team sync:

```text
src/services/teamMemorySync/index.ts
src/services/teamMemorySync/watcher.ts
src/services/teamMemorySync/secretScanner.ts
src/utils/sessionFileAccessHooks.ts
```

Session memory:

```text
src/services/SessionMemory/sessionMemory.ts
src/services/SessionMemory/sessionMemoryUtils.ts
src/services/SessionMemory/prompts.ts
src/services/compact/sessionMemoryCompact.ts
```

UI:

```text
src/commands/memory/index.ts
src/commands/memory/memory.tsx
src/components/memory/MemoryFileSelector.tsx
src/components/memory/MemoryUpdateNotification.tsx
src/components/messages/SystemTextMessage.tsx
```

Permissions and detection:

```text
src/utils/permissions/filesystem.ts
src/utils/memoryFileDetection.ts
src/utils/teamMemoryOps.ts
```

## Development Entry Points

To change where memory is stored:

- Start with `src/memdir/paths.ts`.
- For team memory, also update `src/memdir/teamMemPaths.ts`.
- For agent memory, update `src/tools/AgentTool/agentMemory.ts`.
- Review permission carve-outs in `src/utils/permissions/filesystem.ts`.

To change what should be saved:

- Update prompt sections in `src/memdir/memoryTypes.ts`.
- Update auto-only prompt construction in `src/memdir/memdir.ts`.
- Update team combined prompt in `src/memdir/teamMemPrompts.ts`.
- Update background extraction prompts in `src/services/extractMemories/prompts.ts`.

To change automatic extraction:

- Start with `src/services/extractMemories/extractMemories.ts`.
- Check turn-end trigger logic in `src/query/stopHooks.ts`.
- Check initialization in `src/utils/backgroundHousekeeping.ts`.

To change recall ranking:

- Start with `src/memdir/findRelevantMemories.ts`.
- Check manifest scanning in `src/memdir/memoryScan.ts`.
- Check attachment injection in `src/utils/attachments.ts`.

To change `/memory` UI:

- Start with `src/components/memory/MemoryFileSelector.tsx`.
- Check command wrapper in `src/commands/memory/memory.tsx`.

To change team sync:

- Start with `src/services/teamMemorySync/index.ts`.
- Check watcher behavior in `src/services/teamMemorySync/watcher.ts`.
- Check write notifications in `src/utils/sessionFileAccessHooks.ts`.

