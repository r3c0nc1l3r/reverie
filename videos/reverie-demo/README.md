# Reverie demo

[Watch the MP4](https://github.com/r3c0nc1l3r/reverie/releases/download/v0.2.0/reverie-demo.mp4) · [English captions](https://github.com/r3c0nc1l3r/reverie/releases/download/v0.2.0/reverie-demo.en.srt)

This 84-second video shows testing sessions, visual checks, narration pacing, human handoff, and temporary evidence in v0.2.0. The footage is recorded from the public release build with a synthetic smoke-test application in an isolated desktop.

The pilot scene shows the recorded result of model execution that finished before capture began. The pilot confirmed the delayed icon and passed a functional text check, but stopped with `visual-unverified`: functional checks alone did not establish a visual pass. The scene is labeled “Pilot pauses for visual verification.” The video uses default-on screenshot masking. Masking is best effort, not a secrecy guarantee. The follow-along excerpt records actual narration and its subsequent guarded action continuously. See [visual-checkpoint recovery](../../docs/testing-sessions.md#visual-evidence-and-honest-verdicts) if another run needs intervention.

The release stores the H.264/AAC MP4 and captions as downloadable assets. The repository contains only the poster, transcript, and [credits](CREDITS.md).

## Transcript

Meet Reverie. AI testing, in plain sight.

A complicated app. Dozens of flows. One place to follow the investigation.

Start a testing session. Keep the plan, attempts, evidence, and people together, without mixing in yesterday's runs.

Test what users actually see. When an icon is still loading, the pilot waits for fresh visual evidence.

And when an icon never appears, keep the finding. A working text fallback doesn't make the visual defect disappear.

Want to follow along? Let narration finish, then leave a short pause before the next operation.

Recorded Reverie narration: “I am checking the visible submit action. I will finish this update before the next click.”

Need a human decision? Claim the request, take control at a safe boundary, resolve it, and hand the investigation back.

Keep smoke tests temporary. Pin evidence worth keeping, triage the findings, and give results an explicit lifetime.

See the evidence. Keep control. That's Reverie.
