# Residual Review Findings

Source: LFG keep-frame image Edit on eat/localized-image-edit
Review run: 20260817-012601 (in-process reviewers; cross-model skipped — Cursor serving family unattested)
Applied in tree: empty-mask JPEG sources are re-encoded to PNG before image/png upload (localize.py identity path).

## Residual Review Findings

- P2 server/tests/test_regenerate_localize.py:52 — Missing unit test that an invalid GCS URI raises AttributeValueRegenerationError. Defer failed: no_sink (durable record only; not filed as a tracker ticket).
- P1 server/pipelines/generation/localize.py:31 — LANCZOS size-mismatch resize can inflate the delta mask and fail-close a local edit. Not applied: U1 requires resize-then-localize; existing size-mismatch test encodes that contract.
- P2 server/pipelines/generation/localize.py:35 — Morphology close can push a legal sub-ceiling mask over 0.35. Not applied: ceiling is measured on the mask that is actually composited.
- P2 server/pipelines/generation/localize.py:65 — Morphology open can wipe thin requested edits, then the empty-mask path succeeds. Not applied: close-then-open is the planned speckle drop; fail-closing that path would reject speckle-only candidates.
- P2 server/services/job.py:1389 — Undecodable bytes and other LocalizationImpossibleError causes are remapped to the keep-frame operator copy. Not applied: confidence below the LFG apply bar (no cross-persona 75/100 agreement).
- P2 server/routers/job.py:137 — Keep-frame reject is HTTP 502. Not applied: plan specifies the 502 operator copy; mapping is pre-existing for AttributeValueRegenerationError.

## Coverage notes

- Cross-model adversarial pass skipped (host family unknown on Cursor).
- Validator batch skipped for applied P1 after code-trace confirmation (JPEG magic vs PNG upload).
- Browser tests skipped in pipeline: Edit modal is behind authenticated batch UI; no isolated route to exercise copy without a live catalog stack.
