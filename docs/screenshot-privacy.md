# Screenshot privacy

Screenshot masking is **best effort, not a guarantee**. Unsupported fields, unusual paint and masking faults can leave sensitive content visible. Do not point Reverie at real secrets without your own review. Prefer synthetic test data, and inspect screenshots before sharing or exporting them.

## Field-local masks

Reverie attempts to cover populated password fields, one-time-code inputs, numeric authentication-code fields, and fields containing registered sensitive values. Matching uses exact values or Unicode NFKC equality. It does not use numeric substrings, case folding or punctuation removal. Ordinary postal, ZIP, case and status codes are not treated as authentication codes.

Sensitive input values and the actual target field are tracked in memory. If a target disappears, is replaced, or belongs to an earlier document, it is not used to mask other fields. Masks stay local to recognized fields, with a small margin for uncertain paint. There is no whole-frame or blanket iframe fallback. Inspectable fields in closed shadow roots can receive local masks; unsupported roots and frames can remain visible.

Empty native text fields keep placeholders and borders visible. Populated masks use opaque diagonal stripes and retain ordinary borders where practical. The pilot treats stripes as privacy masks, not application defects. A mask cannot prove a hidden value, a covered control, or a passing visual check. Masking changes image pixels, not page values or layout.

## Trusted selectors

Set `REVERIE_SECRET_SELECTORS` in the operator environment to a JSON array of CSS selectors for form or text fields:

```sh
export REVERIE_SECRET_SELECTORS='["#account-pin", "[data-private]"]'
```

The default is `[]`. Set it before starting a worker; restart the worker after changing its environment configuration. This is trusted configuration, not a selector channel for specs or model requests. Invalid JSON, invalid selectors and non-field matches are ignored with sanitized warnings. Arbitrary display regions, images and graphics are not covered by this setting.

## Faults and capture formats

Mask inspection and drawing faults warn and keep the fresh capture when screenshot acquisition succeeds. A warning does not include field values, selectors or exception details. Unsupported or changing content may remain visible. Browser screenshot transport failures still fail; separate consistency and action guards can refuse concurrent operations or stale visual decisions.

The capture boundary acquires lossless PNG pixels before masking to avoid pre-mask JPEG bleed. It normally returns the requested PNG or JPEG format. If conversion fails, it can return PNG instead; model inputs, MCP images and viewers detect the actual format.

## Existing evidence and concurrency

Registration clears cached images and pending review-frame references. Existing saved frames and clips are not rewritten or recalled. Review historical evidence separately before sharing it. Already prepared or in-flight images cannot be recalled.

Standalone Agent callers must serialize sensitive-value registration with model operations. Capture and image handoff are not atomic with compositor or registration changes. Screenshot masking does not guarantee secrecy, and structured observations and text logs follow separate handling rules.

## Images used for UI review

UI review uses bytes registered by this session’s capture pipeline and verifies that saved files are unchanged. Unregistered legacy files, altered files and symlinks are not model review evidence. Missing or invalid final evidence requires a fresh capture or a declined review; earlier images cannot substitute for a failed final capture. Review results are rejected if the observation or control state changes during model processing.

This provenance check does not prove that every secret was masked. The best-effort policy and need for personal review still apply. Historical files remain available for human replay and are not retroactively sanitized.

Frames saved as evidence are immutable. Choose an unused filename when exporting a screenshot directly into a run’s frames directory. Normal screenshot exports outside that directory keep their ordinary overwrite behavior.
