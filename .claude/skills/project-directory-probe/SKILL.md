---
name: project-directory-probe
description: Diagnostic project skill that proves whether this repository's .claude/skills directory is discovered and its SKILL.md body is loaded. Use when asked to test project skill discovery or verify Claude configuration directory loading.
---

# Project Directory Probe

When invoked, do not inspect other files and do not perform external actions. Reply with exactly:

```text
PROJECT_SKILL_DISCOVERY_OK
skill=project-directory-probe
source=.claude/skills/project-directory-probe/SKILL.md
```

This fixed response distinguishes successful metadata discovery from successful loading of this instruction body.
