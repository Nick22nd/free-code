import {
  appendFileSync,
  mkdirSync,
  rmSync,
  writeFileSync,
} from 'fs'
import { join, resolve } from 'path'

export type ContextInspectorStage =
  | 'instructions_loaded'
  | 'agent_memory_loaded'
  | 'memory_prefetch_started'
  | 'memory_recall_resolved'
  | 'session_memory_updated'
  | 'api_request_ready'

export type ContextInspectorEvent = {
  version: 1
  id: string
  runId: string
  sequence: number
  timestamp: string
  stage: ContextInspectorStage
  pid: number
  cwd: string
  data: unknown
}

const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`
let sequence = 0
let initialized = false

export function isContextInspectorEnabled(): boolean {
  const value = process.env.CLAUDE_CODE_CONTEXT_INSPECTOR?.toLowerCase()
  return value === '1' || value === 'true'
}

export function getContextInspectorDir(): string {
  const configured = process.env.CLAUDE_CODE_CONTEXT_INSPECTOR_DIR
  return configured
    ? resolve(configured)
    : join(process.cwd(), '.claude', 'context-inspector')
}

function initializeOutputDir(): void {
  if (initialized) return
  initialized = true

  const outputDir = getContextInspectorDir()
  mkdirSync(outputDir, { recursive: true })

  const reset = process.env.CLAUDE_CODE_CONTEXT_INSPECTOR_RESET?.toLowerCase()
  if (reset === '1' || reset === 'true') {
    rmSync(join(outputDir, 'events.jsonl'), { force: true })
    rmSync(join(outputDir, 'latest.json'), { force: true })
  }
}

function maximumStringLength(): number {
  const configured = Number.parseInt(
    process.env.CLAUDE_CODE_CONTEXT_INSPECTOR_MAX_CHARS ?? '',
    10,
  )
  return Number.isFinite(configured) && configured > 0 ? configured : 200_000
}

function sanitize(
  value: unknown,
  seen: WeakSet<object>,
  depth = 0,
): unknown {
  if (value === null || value === undefined) return value
  if (typeof value === 'string') {
    const limit = maximumStringLength()
    return value.length <= limit
      ? value
      : `${value.slice(0, limit)}\n… [context inspector truncated ${value.length - limit} chars]`
  }
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return typeof value === 'bigint' ? value.toString() : value
  }
  if (typeof value === 'function' || typeof value === 'symbol') {
    return `[${typeof value}]`
  }
  if (depth >= 10) return '[maximum depth reached]'
  if (value instanceof Error) {
    return { name: value.name, message: value.message, stack: value.stack }
  }
  if (value instanceof Date) return value.toISOString()
  if (typeof value !== 'object') return String(value)
  if (seen.has(value)) return '[circular]'
  seen.add(value)

  if (Array.isArray(value)) {
    const maxItems = 1_000
    const items = value
      .slice(0, maxItems)
      .map(item => sanitize(item, seen, depth + 1))
    if (value.length > maxItems) {
      items.push(`[${value.length - maxItems} more items]`)
    }
    return items
  }

  const result: Record<string, unknown> = {}
  const entries = Object.entries(value as Record<string, unknown>)
  for (const [key, child] of entries.slice(0, 500)) {
    result[key] = sanitize(child, seen, depth + 1)
  }
  if (entries.length > 500) {
    result.__truncatedKeys = entries.length - 500
  }
  return result
}

function shouldBreakAt(stage: ContextInspectorStage): boolean {
  const configured = process.env.CLAUDE_CODE_CONTEXT_INSPECTOR_BREAKPOINTS
  if (!configured) return false
  const stages = new Set(
    configured
      .split(',')
      .map(value => value.trim())
      .filter(Boolean),
  )
  return stages.has('all') || stages.has(stage)
}

/**
 * Writes one opt-in context snapshot and returns whether the caller should
 * execute a local `debugger` statement. Keeping the statement at the caller
 * preserves that checkpoint's local variables in the debugger.
 */
export function contextInspectorCheckpoint(
  stage: ContextInspectorStage,
  data: unknown,
): boolean {
  if (!isContextInspectorEnabled()) return false

  try {
    initializeOutputDir()
    sequence += 1
    const event: ContextInspectorEvent = {
      version: 1,
      id: `${runId}-${sequence}`,
      runId,
      sequence,
      timestamp: new Date().toISOString(),
      stage,
      pid: process.pid,
      cwd: process.cwd(),
      data: sanitize(data, new WeakSet()),
    }
    const json = JSON.stringify(event)
    const outputDir = getContextInspectorDir()
    appendFileSync(join(outputDir, 'events.jsonl'), `${json}\n`, 'utf8')
    writeFileSync(join(outputDir, 'latest.json'), `${json}\n`, 'utf8')
  } catch {
    // Debug tooling must never affect the main program.
  }

  return shouldBreakAt(stage)
}
