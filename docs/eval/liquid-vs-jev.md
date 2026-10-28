# Experimental Liquid decision engine

Evaluated 2026-10-27. **Jev 1.13 remains the default.** Liquid d1-ultra is an opt-in option for supervised visual tests.

## Access and setup

Both families use OpenRouter's Decisions API: `POST https://openrouter.ai/api/alpha/decisions`. The existing `OPENROUTER_API_KEY` works for both. OpenRouter accepts the same typed questions and returns typed answers. Image inputs are media parts inside `state`; Liquid's direct-API image envelope is different.

```sh
REVERIE_LIQUID_MODEL=liquid/d1-ultra REVERIE_DECISION_IMAGES=on \
  reverie --session visual-trial start --url https://example.com --engine liquid
reverie --session visual-trial goal "Complete the approved smoke flow and verify the visible result"
reverie --session visual-trial suggest --engine liquid
# Review the proposal before accepting it.
reverie --session visual-trial accept
```

Liquid requires fresh screenshots by default. Jev uses text by default; `REVERIE_DECISION_IMAGES=on` enables images for Jev. `off` provides a text-only comparison. Restart the session after changing settings. Images and page data go to the provider. Image normalization does not redact sensitive content.

## Small synthetic comparison

The browser sample tested a visible text fallback and a delayed icon. Jev 1.13 and d1-ultra passed all six final runs across text and image modes. All 40 typed answer heads validated. Median HTTP times were 200 ms for Jev text, 213 ms for Ultra text, 257 ms for Jev images, and 278 ms for Ultra images. Browser execution adds observation and settling time.

A separate pair of screenshots kept the DOM unchanged while switching an icon between broken and loaded. Ultra chose correctly in both cases; Jev 1.13 and cheaper d1 each chose correctly once. A later Jev 1.14 replay also chose both correctly and matched six saved text decisions. No actions were executed during those replays. These small samples do not establish general accuracy, calibration, or a latency improvement.

## Context and limits

| OpenRouter model | Advertised context | Input price per million tokens | Image input |
|---|---:|---:|---|
| `typesafe/jev-1.13`, `typesafe/jev-1.14` | 262K | $0.042 | Yes |
| `liquid/d1` | 64K | $0.020 | Yes |
| `liquid/d1-ultra` | 32K | $0.042 | Yes |

Output is free on these routes. Prices and availability were checked on the evaluation date. See the [Ultra endpoint record](https://openrouter.ai/api/v1/models/liquid/d1-ultra/endpoints), [Jev endpoint record](https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints), and [multimodal API guide](https://openrouter.ai/docs/guides/community/multimodal-decisions). Jev's usable context depends on request configuration; its maximum was not stress-tested.

The saved smoke observations fit Ultra. A synthetic observation with 250 controls, 16K page text and a screenshot was accepted. Adding long field values produced an HTTP 422 input-limit rejection. The provider reported a 32,768-token limit including images, or 250,000 text bytes. Page text and action counts are capped; field values and some option strings are not. There is no automatic context compaction or model fallback. A rejected request executes no action.

Liquid's direct API also documents d1.1. Its context improvement was not established, and it was absent from the checked OpenRouter routes. It was not evaluated here. [Liquid hosted models](https://docs.liquid.ai/lfm/models/d1)

## Recommendation

Keep Jev as the default. Trial Ultra with reviewed synthetic observations if its visual decisions help a specific test. Use the pilot for scenario design and narration, and the observed-action executor for grounded actions. A typed decision engine does not replace those roles. This comparison did not test a large application, long-context decision quality, or a representative visual regression corpus.
