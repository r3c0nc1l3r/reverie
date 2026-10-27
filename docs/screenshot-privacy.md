# Screenshot privacy

New captures pass through an opaque striped masking boundary before Reverie returns, shares, or saves their image bytes. It covers password fields, one-time-code inputs, and numeric fields labeled as codes or tokens. It also tracks values and targets used through secret entry, redacted fills, and checkpoint or reply answers, in memory for that browser session. Masking changes the image, not the page or its input values.

Empty native text fields keep their placeholders and borders visible. Filled sensitive fields receive fixed opaque diagonal stripes, with their borders visible when geometry permits safe masking. Trusted non-field regions remain covered even when they have no value. Uncertain paint or geometry can require broader coverage. The capture boundary acquires lossless PNG pixels before applying masks, which avoids spreading secret pixels through prior JPEG compression.

The pilot treats stripes as privacy masks, not application defects. A mask cannot establish a hidden value, a covered control, or a passing visual check.

## Trusted private regions

Set `REVERIE_SECRET_SELECTORS` in the operator environment to a JSON array of CSS selectors:

```sh
export REVERIE_SECRET_SELECTORS='["#account-pin", "[data-private]"]'
```

The default is `[]`. Set this before starting a worker; restart the worker after changing its environment configuration. This setting is trusted configuration, not a selector escape hatch for specs or model requests. Invalid JSON, an invalid selector, unstable geometry, or a failed privacy check withholds the image. Capture failure cannot establish a visual pass.

Inaccessible or unsupported frames are covered in full. A closed shadow root covers the whole screenshot. Filters and uncertain geometry can cause broader masking. If a tracked target disappears, is hidden or replaced, or the page navigates, other editable fields are covered conservatively. Active animations can prevent a capture.

## Limits and existing evidence

Registering a new sensitive value clears cached images and pending review-frame references so earlier images are not reused in a later model review. **Existing saved frames and clips are not rewritten or recalled.** They may contain information captured before it was classified as sensitive; review those artifacts separately before sharing or exporting them.

Automatic value matching covers form and editable content. Use trusted selectors for other sensitive display regions, such as custom rendered text or graphics. Image masking is separate from structured observations and text-log handling.

Capture checks are not atomic with compositor changes. A transient change during capture may escape detection. Use synthetic test data and inspect exported evidence; screenshot masking is not a complete guarantee of secrecy.

Standalone Agent callers must serialize secret registration with model operations. Registration can begin between a final privacy check and image handoff; already prepared or in-flight images cannot be recalled. The registration checks reject captures and cached observations while registration is visibly in progress, but do not provide atomic concurrent model egress.
