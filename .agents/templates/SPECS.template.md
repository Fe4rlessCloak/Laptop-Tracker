# Spec: [Feature / Module Name]

## 1. Objective & Scope
* **Goal:** [Concise 1-2 sentence description of what is being built]
* **Target Files/Directories:** `[e.g., src/components/auth/, src/api/routes/]`
* **Out of Scope:** [What explicitly should NOT be touched in this spec]

## 2. Dependencies & Prerequisites
- [ ] [e.g., Base database schema migrated]
- [ ] [e.g., External API keys configured]

## 3. Implementation Units (Execution Order)
*Implement in logical order of foundational dependencies first, regardless of list position.*

- [ ] **Unit 1: [Data Models / Base Utilities]**
  - [ ] Implement `[Path]`
  - [ ] Add unit test in `[Path]`
- [ ] **Unit 2: [Core Business / API Logic]**
  - [ ] Implement `[Path]`
  - [ ] Verify endpoint response
- [ ] **Unit 3: [UI & Consumer Integration]**
  - [ ] Implement `[Path]`
  - [ ] Wire up state and loading/error states

## 4. Verification Criteria
*Task is complete only when verified by an observable signal.*

* **Build Command:** `[e.g., pnpm build]`
* **Test Command:** `[e.g., pnpm test src/auth]`
* **Expected Observable Behavior:** [e.g., Submitting form returns HTTP 201 and redirects to /dashboard]

## 5. Compatibility  

- Preserve existing public APIs unless specified.
- Preserve backward compatibility unless explicitly waived.
