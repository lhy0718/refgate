---
description: Run Refgate public repository hygiene checks
argument-hint: [root]
---

Run public repository hygiene checks before pushing, tagging, or publishing.

Input:

- repository root: `$1`

Use `.` if no root is supplied. Use `refgate` if installed. If not installed and
this is a Refgate source checkout, use `PYTHONPATH=src python3 -m refgate`.

Run:

```bash
refgate publish-check --root ROOT --json
```

Also run a plain text scan for local paths and sensitive credential material
using the current repository's documented scan pattern. If any finding appears,
fix it before staging or pushing.
