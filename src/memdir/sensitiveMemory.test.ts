import { afterEach, describe, expect, test } from 'bun:test'
import {
  applySensitiveMemoryPolicyToToolInput,
  getSensitiveMemoryAction,
  sanitizeMemoryText,
} from './sensitiveMemory.js'

const originalTerms = process.env.CLAUDE_CODE_MEMORY_SENSITIVE_TERMS
const originalAction = process.env.CLAUDE_CODE_MEMORY_SENSITIVE_ACTION

afterEach(() => {
  if (originalTerms === undefined)
    delete process.env.CLAUDE_CODE_MEMORY_SENSITIVE_TERMS
  else process.env.CLAUDE_CODE_MEMORY_SENSITIVE_TERMS = originalTerms
  if (originalAction === undefined)
    delete process.env.CLAUDE_CODE_MEMORY_SENSITIVE_ACTION
  else process.env.CLAUDE_CODE_MEMORY_SENSITIVE_ACTION = originalAction
})

describe('sensitive memory policy', () => {
  test('redacts configured literal terms case-insensitively', () => {
    process.env.CLAUDE_CODE_MEMORY_SENSITIVE_TERMS = 'Project Atlas,客户甲'
    const result = sanitizeMemoryText('project atlas belongs to 客户甲')
    expect(result.text).toBe('[REDACTED] belongs to [REDACTED]')
    expect(result.matchCount).toBe(2)
  })

  test('redacts high-confidence credentials by default', () => {
    const result = sanitizeMemoryText(
      'api_key=1234567890abcdef and ghp_1234567890abcdefghijklmnop',
    )
    expect(result.text).not.toContain('1234567890abcdef')
    expect(result.matchCount).toBe(2)
  })

  test('filters generated Write and Edit fields without changing paths', () => {
    process.env.CLAUDE_CODE_MEMORY_SENSITIVE_TERMS = 'secret launch'
    const result = applySensitiveMemoryPolicyToToolInput({
      file_path: 'memory/project.md',
      content: 'secret launch is Friday',
      old_string: 'unchanged',
      new_string: 'SECRET LAUNCH is Monday',
    })
    expect(result.input.file_path).toBe('memory/project.md')
    expect(result.input.content).toBe('[REDACTED] is Friday')
    expect(result.input.new_string).toBe('[REDACTED] is Monday')
  })

  test('defaults to redact and accepts exclude mode', () => {
    delete process.env.CLAUDE_CODE_MEMORY_SENSITIVE_ACTION
    expect(getSensitiveMemoryAction()).toBe('redact')
    process.env.CLAUDE_CODE_MEMORY_SENSITIVE_ACTION = 'EXCLUDE'
    expect(getSensitiveMemoryAction()).toBe('exclude')
  })
})
