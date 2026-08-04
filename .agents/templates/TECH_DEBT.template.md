# Tech Debt & Compromise Tracker

Record only intentional technical compromises made to satisfy the active specification. Do not record ordinary implementation decisions or future feature ideas.

**Write path:** The **Repository Evolution** skill writes entries to this file. **Implementation** does not write here directly — it proposes a tech-debt entry via a learning file in `learnings/pending/` with an Evolution Candidate whose `Destination: TECH_DEBT`. Implementation may add the `// TECHDEBT: DEBT-001` marker in code, but the entry itself is created by the evolver.

---

## [DEBT-001] – Short Title

- **Date Added:** YYYY-MM-DD
- **Status:** OPEN | RESOLVED
- **File Location:** `path/to/file.ts` (`// TECHDEBT: DEBT-001`)
- **Spec Reference:** `SPECS.md`
- **Introduced By:** Commit hash (optional)

### Compromise

Describe the temporary implementation or deviation from the preferred design.

### Justification

Explain why the compromise was necessary to complete the current spec.

### Impact

Describe the risks or limitations introduced.

Examples:
- Performance degradation
- Duplicate logic
- Missing validation
- Reduced maintainability

### Remediation

Describe the preferred long-term implementation.

### Verification

How will you know the debt has been paid?

Examples:
- Duplicate helper removed
- Shared abstraction introduced
- Integration tests pass
- Performance benchmark restored

### Resolution

- **Resolved By:**
- **Resolved On:**
- **Notes:**