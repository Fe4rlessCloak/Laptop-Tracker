# Domain Skill: GitHub Actions Verification

## Purpose

Apply these rules when changing the release workflow in [.github/workflows/release.yml](../../.github/workflows/release.yml).

---

## Domain Principles

- Static YAML/schema validation and hosted action execution are different evidence. A valid workflow can still fail in a third-party action's template engine.
- Select supported versions from release-specific documentation, input schemas, and breaking-change notes. A newer major or the default branch is not proof that the selected release behaves correctly.
- Never weaken workflow permissions/security or expose tokens to satisfy verification.

---

## Required Patterns

- Before changing an action input, inspect documentation and tests for the selected release, especially template expressions. Record why the pinned version is appropriate.
- Run available static checks, then verify the actual hosted run and expected artifact publication before claiming success. Missing hosted evidence must be reported explicitly.
- Preserve the existing working metadata configuration unless new behavior requires a tested change. The 2026-08 incident is historical evidence, not proof that an upstream defect remains unfixed indefinitely.

---

## Avoid

- Do not blindly choose the latest major or inspect only upstream's default branch when deploying a different release.
- Do not treat local tests, image builds, or static validators as proof of successful registry publication.
- Do not copy version lists or time-sensitive upstream bug claims into permanent policy.

---

## Blueprint

Existing tag inputs in [.github/workflows/release.yml](../../.github/workflows/release.yml) provide a concrete baseline:

```yaml
- name: Compute image tags
  id: meta
  uses: docker/metadata-action@v6
  with:
    images: ghcr.io/fe4rlesscloak/laptop-tracker
    tags: |
      type=sha,format=short
      type=raw,value=latest
      type=raw,value={{tag}}
```

When changing this baseline, verify branch and tag trigger behavior in hosted runs, including empty-tag handling and the resulting published tags. This example records the existing pattern; it is not a recommendation to auto-upgrade other actions.

---

## Verification

- [ ] Selected release documentation/input schema and breaking changes reviewed.
- [ ] Static checks and local application tests performed where available.
- [ ] Hosted run succeeds on relevant trigger contexts.
- [ ] Expected image tags/artifacts are published, or unavailable evidence is explicitly reported.
- [ ] Credentials and minimum-required permissions remain protected.
