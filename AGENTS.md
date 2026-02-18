# AGENTS.md

## Mission
Build and maintain a text-first, AI-generated daily newspaper that is neutral, factual, and non-sensational.

## Engineering Priorities
1. Maximize readability.
2. Minimize complexity.
3. Prefer small, focused diffs over broad refactors.
4. Keep behavior deterministic and cron-safe.

## Content/Product Guardrails
- Output must remain neutral and fact-first.
- Avoid sensational framing and speculation.
- Preserve source attribution/links.
- Do not introduce paywalled-only dependencies for core coverage.

## Required Update Scope
When changing functionality:
- Update relevant documentation in `README.md`.
- Update `.github/workflows/*.yml` if run behavior, paths, env vars, or schedules change.
- Keep config examples aligned with code behavior.

## Code Quality Standards
- Use clear naming and small functions.
- Add comments only where logic is non-obvious.
- Avoid over-engineering and unnecessary abstractions.
- Prefer standard library unless a dependency provides clear value.
- Preserve backward compatibility of config keys where practical.

## Security Expectations
- Follow least-privilege principles for workflow permissions.
- Never hardcode secrets or tokens.
- Read secrets from environment variables only.
- Validate/escape external content before rendering into HTML.
- Keep output text-only constraints intact (no injected scripts).

## Validation Requirements (must run before finalizing)
- Always use the `--dry-run` flag when invoking the `daily_paper` script for testing or verification to prevent unnecessary API calls and costs.
- If changes affect summarization logic (item or topic summaries), ensure mock data used by dry-run is updated to reflect these changes.
- Run syntax check for changed Python files:
  - `python -m compileall -q .`
- If tests exist, run the relevant subset.
- Ensure generated output path and archive behavior still work.

## Decision Heuristics
Act as both developer and product owner:
- If unsure, choose the simpler design that improves reader clarity.
- Prioritize duplicate reduction, source quality, and summary usefulness over feature sprawl.
- Prefer actionable, thematic summaries over repetitive restatement.

## Definition of Done
A change is complete when:
1. Code is syntactically valid.
2. Core run path still generates the daily paper.
3. README/workflow updates are included when applicable.
4. Output remains consistent with the mission and guardrails above.
