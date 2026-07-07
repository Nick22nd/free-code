# Memory sensitive-data policy

The memory pipeline applies the same deterministic policy at three boundaries:

1. **Extraction/generation:** auto-memory and session-memory Write/Edit payloads are filtered before reaching the filesystem. Extraction prompts also tell the model not to generate sensitive memory.
2. **Indexing:** sensitive descriptions are redacted, or omitted entirely in `exclude` mode, before they are sent to the relevance selector.
3. **Recall:** the user query is filtered before relevance selection and memory content is filtered again immediately before context injection. This protects old or manually edited memory files too.

High-confidence credential patterns (private keys, common API token prefixes, and labelled passwords/secrets) are enabled by default.

Add organization-specific words or phrases with a comma- or newline-separated environment variable:

```powershell
$env:CLAUDE_CODE_MEMORY_SENSITIVE_TERMS='internal-project-name,customer-account-42'
```

The default action is `redact`, replacing matches with `[REDACTED]` while retaining useful surrounding context:

```powershell
$env:CLAUDE_CODE_MEMORY_SENSITIVE_ACTION='redact'
```

Use `exclude` for stricter environments. A matching generated Write/Edit is rejected, and existing memory files with sensitive frontmatter descriptions are excluded from automatic recall:

```powershell
$env:CLAUDE_CODE_MEMORY_SENSITIVE_ACTION='exclude'
```

The term list is literal and case-insensitive. Regexes are intentionally not accepted from configuration, avoiding invalid expressions and regex denial-of-service risks. Broad PII categories should be added only when required because generic name, email, or phone detection has substantial false-positive cost.
