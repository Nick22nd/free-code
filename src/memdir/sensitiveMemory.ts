/**
 * Deterministic sensitive-data policy for persistent memory.
 *
 * Configure project/user-specific terms with
 * CLAUDE_CODE_MEMORY_SENSITIVE_TERMS (comma or newline separated). Built-in
 * patterns cover common credentials even when no custom terms are configured.
 * Set CLAUDE_CODE_MEMORY_SENSITIVE_ACTION=exclude to reject matching writes;
 * the default is "redact".
 */

export type SensitiveMemoryAction = 'redact' | 'exclude'

export type SensitiveMemoryResult = {
  text: string
  matched: boolean
  matchCount: number
}

const REDACTION = '[REDACTED]'

// Deliberately conservative: high-confidence credential shapes only. Broad
// PII detection (names, addresses, phone numbers) creates too many false
// positives and should be supplied through the custom term list.
const BUILT_IN_PATTERNS: readonly RegExp[] = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/gi,
  /\b(?:sk-ant-|sk-proj-|sk-live-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}\b/g,
  /\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*["']?[^\s,"']{8,}/gi,
]

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function getSensitiveMemoryAction(): SensitiveMemoryAction {
  return process.env.CLAUDE_CODE_MEMORY_SENSITIVE_ACTION
    ?.trim()
    .toLowerCase() === 'exclude'
    ? 'exclude'
    : 'redact'
}

export function getSensitiveMemoryTerms(): string[] {
  const raw = process.env.CLAUDE_CODE_MEMORY_SENSITIVE_TERMS ?? ''
  return [...new Set(raw.split(/[,\n\r]+/).map(v => v.trim()).filter(Boolean))]
}

export function sanitizeMemoryText(text: string): SensitiveMemoryResult {
  let output = text
  let matchCount = 0
  const patterns = [
    ...BUILT_IN_PATTERNS,
    ...getSensitiveMemoryTerms().map(
      term => new RegExp(escapeRegExp(term), 'giu'),
    ),
  ]

  for (const pattern of patterns) {
    output = output.replace(pattern, () => {
      matchCount++
      return REDACTION
    })
  }
  return { text: output, matched: matchCount > 0, matchCount }
}

/** Sanitize Write/Edit payloads before a memory tool reaches the filesystem. */
export function applySensitiveMemoryPolicyToToolInput(
  input: Record<string, unknown>,
): { input: Record<string, unknown>; matched: boolean; matchCount: number } {
  const next = { ...input }
  let matched = false
  let matchCount = 0
  for (const key of ['content', 'new_string'] as const) {
    const value = next[key]
    if (typeof value !== 'string') continue
    const result = sanitizeMemoryText(value)
    next[key] = result.text
    matched ||= result.matched
    matchCount += result.matchCount
  }
  return { input: next, matched, matchCount }
}

export function sensitiveMemoryPromptGuidance(): string {
  const terms = getSensitiveMemoryTerms()
  const configured =
    terms.length > 0
      ? ` Configured sensitive terms (${terms.length}) must never be copied verbatim.`
      : ''
  return `Sensitive-memory policy: never persist credentials, private keys, tokens, passwords, or user-designated sensitive terms.${configured} Replace sensitive values with ${REDACTION}; if the surrounding fact is no longer useful after redaction, do not save it.`
}
