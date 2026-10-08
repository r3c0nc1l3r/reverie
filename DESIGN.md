---
version: alpha
name: Reverie
description: >
  Dark-first review UI for a spec-driven browser test agent. AI agents drive and resolve the tests; people review
  the results. The spec outline and the agent's notes come first; individual clicks come second.
colors:
  background: "#0b0d14"
  foreground: "#e7e9f0"
  card: "#11141d"
  muted: "#161a25"
  muted-foreground: "#9299b5"
  border: "#242a39"
  input: "#1a1f2e"
  primary: "#9cc4ff"
  primary-foreground: "#0b0d14"
  secondary: "#7ee7c7"
  accent: "#7ee7c7"
  accent-foreground: "#0b0d14"
  ring: "#7ee7c7"
  destructive: "#ff6b6b"
  brand-1: "#f6d6ff"
  brand-2: "#9cc4ff"
  brand-3: "#7ee7c7"
  verdict-pass: "#3fcf8e"
  verdict-app-fail: "#ff6b6b"
  verdict-harness: "#c792ff"
  verdict-blocked: "#f5b64a"
  verdict-not-run: "#6f7890"
  verdict-running: "#7cb8ff"
  verdict-waiting: "#ffd166"
  actor-laya: "#7ee7c7"
  actor-pilot: "#79e2f2"
  actor-orchestrator: "#ffd166"
  actor-person: "#f6d6ff"
typography:
  body:
    fontFamily: Inter
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: 1.5
  step-title:
    fontFamily: Inter
    fontSize: 1rem
    fontWeight: 500
    lineHeight: 1.375
  h1:
    fontFamily: Inter
    fontSize: 1.5rem
    fontWeight: 600
    lineHeight: 1.33
  label:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: 600
    letterSpacing: 0.05em
  mono:
    fontFamily: JetBrains Mono
    fontSize: 0.75rem
    fontWeight: 400
  wordmark:
    fontFamily: Fraunces
    fontSize: 1.125rem
    fontWeight: 600
rounded:
  sm: 6px
  md: 8px
  lg: 10px
  xl: 12px
  full: 9999px
spacing:
  "1": 4px
  "2": 8px
  "3": 12px
  "4": 16px
  "6": 24px
  "8": 32px
components:
  verdict-pill:
    backgroundColor: "{colors.verdict-pass} at 15%"
    textColor: "{colors.verdict-pass}"
    rounded: "{rounded.full}"
  step-row:
    backgroundColor: "{colors.card}"
    borderColor: "{colors.border}"
    rounded: "{rounded.xl}"
  step-row-current:
    backgroundColor: "{colors.verdict-running} at 5%"
    borderColor: "{colors.verdict-running} at 60%"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.md}"
  focus-ring:
    color: "{colors.ring}"
    width: 2px
---

# Reverie design system

This file tells coding agents how to build and change the Reverie UI. It follows the DESIGN.md convention: exact
tokens in the YAML front matter, then written rules on when and why to use them. The code is the source of truth.
If this file and the code disagree, the code wins; then fix this file.

| Source of truth | What it holds |
|---|---|
| `ui/src/index.css` | CSS variables for the theme, verdict, and actor colors; fonts; reduced-motion rule |
| `ui/tailwind.config.ts` | Tailwind color names (`bg-verdict-pass`, `text-actor-pilot`, ...) and the radius scale |
| `ui/src/components/icons.tsx` | The one icon for each verdict, actor, checkpoint kind, and action kind |
| `ui/src/components/kit.tsx` | Reverie kit components and the static class maps for tokens |
| `ui/src/components/ui/` | shadcn/ui components |

`ui/src/styles/tokens.css` is an older token sheet. No file imports it. Do not add to it.

## Overview

### Product

Reverie is a spec-driven browser test agent. A spec is a Markdown file with numbered steps. AI agents run the
spec in a real browser: the **pilot** decides what to do, **Laya** clicks and types, and the **orchestrator**
(the agent or person who started the run) answers checkpoints such as a sign-in or a database proof. Agents also
recover when a run goes wrong. People do not unstick a run.

Reverie keeps its evidence in the tested project's `.reverie/` directory:

| Path | What it holds |
|---|---|
| `.reverie/runs/<session>-<stamp>/run.json` | The short summary the history list reads: spec id, title, verdict, steps done |
| `.reverie/runs/<session>-<stamp>/trail.jsonl` | Every event. The source of truth for steps, notes, actions, and findings |
| `.reverie/runs/<session>-<stamp>/frames/` | Screens for replay and before/after compare |
| `.reverie/specs/` | Stored specs |
| `.reverie/cache/` | Disposable caches, such as narration audio |

### Users

1. **Reviewers (people).** They open the UI to learn what happened: did the spec pass, what did the app do wrong,
   and what proof exists. They read; they seldom act.
2. **Agents.** They drive the runs and read the same evidence. The UI must never be a required step for a run to
   finish.

### Look and feel

Calm, dense, and dark. The tool runs next to a terminal and an editor, so the UI uses a near-black background, one
brand gradient (the wordmark only), and color only where it carries meaning (verdicts and actors). It is a
reading tool: large readable step titles and notes, small secondary detail.

### Principles

1. **Outline first.** The spec outline is the page. Each step shows its verdict, the agent's progress, and the
   agent's notes (its narration). Individual clicks are secondary: keep them in a collapsible, scrollable Actions
   drawer. A step can have 60 or more actions; never put them in the main column.
2. **History first.** Open on the run history from `.reverie/runs/`. Pin the current (live) run at the top with a
   live marker, then list past runs grouped by day. A person must be able to review any past run the same way as
   the live run.
3. **Honest verdicts.** Never show one "fail". Split the result so the reason is visible without opening the run:

   | Verdict | Label | Meaning |
   |---|---|---|
   | `pass` | Pass | Every check passed and no medium or high finding is open |
   | `app-fail` | App finding | The application did the wrong thing. A real defect |
   | `harness` | Harness slip | The test or the tooling went wrong. The app may be fine |
   | `blocked` | Blocked | The environment, a fixture, or a decision prevented the test |
   | `not-run` | Not run | Skipped on purpose, for example a missing credential |
   | `running` | Running | An agent works on it now |
   | `waiting` | Needs you | A checkpoint waits for the orchestrator |
   | `pending` | Pending | Not started |

4. **Agents resolve their own problems.** Do not show "stuck", "stalled", "no progress", or "nudge" states, and do
   not add controls that ask a person to unstick the pilot. A checkpoint is a normal request for facts, not an
   alarm.
5. **Evidence is one click away.** Every finding and action links to its frame. Before/after compare opens in a
   dialog; it does not replace the outline.

## Colors

The theme is dark only (the Storybook preview wraps every story in `.dark`). Use theme tokens through Tailwind
names. Do not use the Tailwind palette (`green-600`, `red-950`, `amber-500`, ...), raw hex values in components,
or `text-white` on colored fills.

### Surfaces and text

| Token | Value | Tailwind | Use |
|---|---|---|---|
| `--background` | `#0b0d14` | `bg-background` | Page |
| `--card` | `#11141d` | `bg-card` | Header, rails, drawers, step rows, cards |
| `--muted` | `#161a25` | `bg-muted` | Hover and selected rows, neutral chips |
| `--input` | `#1a1f2e` | `bg-input` | Input fields |
| `--border` | `#242a39` | `border-border` | All borders and dividers |
| `--foreground` | `#e7e9f0` | `text-foreground` | Primary text |
| `--muted-foreground` | `#9299b5` | `text-muted-foreground` | Secondary text, times, labels |

### Brand and interaction

| Token | Value | Use |
|---|---|---|
| `--primary` | `#9cc4ff` | Primary buttons, links, selected state, quoted typed text |
| `--secondary` / `--accent` | `#7ee7c7` | Ghost and outline button hover fill |
| `--ring` | `#7ee7c7` | Focus ring |
| `--destructive` | `#ff6b6b` | Destructive buttons, secret warnings |
| Brand gradient | `#f6d6ff` to `#9cc4ff` to `#7ee7c7` | The "Reverie" wordmark only |

### Verdicts

Each verdict has one color and one meaning. Solid fills (`bg-verdict-*`) are for small marks: dots, strip
segments, history cells. Text and icons use `text-verdict-*`. Soft fills use the verdict color at 15%
(`bg-verdict-*/15`); edges use `border-l-verdict-*`.

| Verdict | Token | Value | Soft fill | Text |
|---|---|---|---|---|
| Pass | `--verdict-pass` | `#3fcf8e` | `bg-verdict-pass/15` | `text-verdict-pass` |
| App finding | `--verdict-app-fail` | `#ff6b6b` | `bg-verdict-app-fail/15` | `text-verdict-app-fail` |
| Harness slip | `--verdict-harness` | `#c792ff` | `bg-verdict-harness/15` | `text-verdict-harness` |
| Blocked | `--verdict-blocked` | `#f5b64a` | `bg-verdict-blocked/15` | `text-verdict-blocked` |
| Not run | `--verdict-not-run` | `#6f7890` | `bg-verdict-not-run/15` | `text-muted-foreground` |
| Running | `--verdict-running` | `#7cb8ff` | `bg-verdict-running/15` | `text-verdict-running` |
| Needs you | `--verdict-waiting` | `#ffd166` | `bg-verdict-waiting/15` | `text-verdict-waiting` |
| Pending | none | | `bg-muted` | `text-muted-foreground` |

`index.css` also defines `--verdict-*-muted` at 10% alpha. Prefer the `/15` modifier in new code.

Finding severity reuses verdict colors: high is `verdict-app-fail`, medium is `verdict-blocked`, low is
`verdict-running` (see `severityClasses` in `kit.tsx`).

### Actors

| Actor | Name shown | Token | Value | Tag classes |
|---|---|---|---|---|
| `laya` | Laya | `--actor-laya` | `#7ee7c7` | `bg-actor-laya/15 text-actor-laya` |
| `pilot` | Pilot | `--actor-pilot` | `#79e2f2` | `bg-actor-pilot/15 text-actor-pilot` |
| `orchestrator` | You | `--actor-orchestrator` | `#ffd166` | `bg-actor-orchestrator/15 text-actor-orchestrator` |
| `person` | Person | `--actor-person` | `#f6d6ff` | `bg-actor-person/15 text-actor-person` |

### Class names must be static

Tailwind only generates classes it finds as whole strings in the source. Look up token classes in a static map
(`verdictText`, `verdictSoftBg`, `verdictBorder`, `severityClasses`, `actorSoftBg` in `kit.tsx`). Never build a class
name with a template string such as `` `bg-verdict-${v}` ``.

## Typography

| Role | Font | Size and weight | Tailwind |
|---|---|---|---|
| Page title (run title) | Inter | 24px, 600, tight tracking | `text-2xl font-semibold tracking-tight` |
| Step title | Inter | 16px, 500 | `text-base font-medium leading-snug` |
| Body, notes | Inter | 14px, 400, relaxed | `text-sm leading-relaxed` |
| Secondary detail | Inter | 12px | `text-xs text-muted-foreground` |
| Section label | Inter | 12px, 600, uppercase, wide tracking | `text-xs font-semibold uppercase tracking-wider` |
| Ids, times, paths, commands | JetBrains Mono | 12px | `font-mono text-xs` |
| Wordmark | Fraunces | 18px, 600, brand gradient | `Brand` component only |

- Fonts load from Google Fonts in `index.css`: Inter 400 to 700, JetBrains Mono 400 and 500, Fraunces 600 and 700.
- Use Fraunces for the wordmark only. Do not use it for headings.
- Use `tabular-nums` for counts and durations that change.
- Spec ids (`FS-02`), times (`10:14:05`), session names, and `.reverie/` paths are mono.

## Layout

### Spacing

Use the Tailwind 4px scale. Common values: `gap-2` (8px) inside controls, `gap-3` (12px) between rows,
`p-4` (16px) inside cards and step rows, `px-6` or `px-8` (24 or 32px) page gutters, `space-y-6` (24px) between page
sections.

### Page frame

Every screen is a full-height column: `AppHeader` on top, then the work area with `min-h-0 flex-1` so inner
panes scroll, not the page. No horizontal page scroll at 1280px and wider.

### Run review (primary layout)

```
+--------------------------------------------------------------------------------------+
| AppHeader: Reverie | Run review | project      Narration on  Actions  Replay  Rerun   |
+---------------+-----------------------------------------------+----------------------+
| History rail  | Run summary: id, title, verdict, progress      | Actions drawer       |
| 300px         | Spec outline (max-w-4xl, centered)            | 400px, collapsible   |
| search        |  1  Step title ................ Pass      v   | time actor verb      |
| Current run   |  2  Step title ................ Pass      v   | target  thumbnail    |
|  (live)       |  3  Step title ............ Running       ^   | ... 60+ rows,        |
| Today         |     10:14:05 note ....................  play  | ScrollArea           |
| Yesterday     |     Finding / visual review     [64 actions]  |                      |
| .reverie/runs |  4  Step title ............ Pending       v   |                      |
+---------------+-----------------------------------------------+----------------------+
```

- **History rail** (`aside`, 300px, `bg-card`): search input, then "Current run" (the live run, marked with a
  pulsing dot and "Live"), then past runs grouped by day. Each item shows the verdict icon, spec id, start time,
  title (two lines at most), a `VerdictStrip` of step verdicts, steps judged, the verdict label, and duration. The
  footer shows the `.reverie/runs` path.
- **Outline** (center, widest, `max-w-4xl`): the run summary (spec id badge, title, `VerdictPill`, session, start,
  duration, run folder with a copy button, "N of M steps judged", counts by verdict, a `VerdictStrip` as the
  progress bar), then one large row per spec step. The current step has a running border and "The agent is on this
  step". Open a step to see its notes as a timeline (time, text, play button for narration audio), its findings,
  its visual review result, and an "N actions" button.
- **Actions drawer** (right, 400px, closed by default): the actions of the selected step in a `ScrollArea`. Each
  row: time, actor icon, action icon, verb, target, typed text, and a thumbnail (or a pass or fail icon for a
  check). Select a row to open its before/after frames in a `Dialog` with `FrameCompare`.

### Other concept layouts

- **Mission control**: responsive card grid (`repeat(auto-fill, minmax(330px, 1fr))`), one card per session.
- **Checkpoint inbox**: 256px queue on the left, detail on the right.
- **Suite matrix**: KPI row, segmented bar, filter chips, then a table grouped by app.
- **Findings triage**: four state columns and a 420px detail panel.

## Elevation & Depth

Depth comes from surface steps and borders, not shadows: `background` (page) under `card` (panels) under `muted`
(hover and selection). Borders are 1px `border-border`. Use shadows only for overlays (`Dialog`, `Sheet`,
tooltips). The one exception is the waiting glow on a Mission control card (`shadow-verdict-waiting/20`). The
dialog overlay is `bg-black/50`.

## Shapes

| Radius | Value | Use |
|---|---|---|
| `rounded-sm` | 6px | Thumbnails, strip segments |
| `rounded-md` | 8px | Buttons, inputs, note highlight |
| `rounded-lg` | 10px (`--radius`) | Cards, history items, frames, finding blocks |
| `rounded-xl` | 12px | Step rows in the outline |
| `rounded-full` | pill | Verdict pills, badges, dots, step numbers |

Frames of the app under test keep a white background (`FrameImg`); do not tint them.

## Components

### shadcn/ui rules

- Use the components in `ui/src/components/ui/`: alert, badge, button, card, checkbox, collapsible, dialog, input,
  kbd, label, progress, scroll-area, separator, sheet, slider, table, tabs, textarea, toggle-group, tooltip.
- Add a component with `npx shadcn@latest add <name>` from `ui/`. Then replace any `lucide-react` import in the new
  file with the matching `react-icons/lu` icon.
- Style through the theme tokens. Do not fork a shadcn component to change one color; pass classes.
- `Button` variants: `default` (primary action, one per area), `outline` (secondary actions), `ghost` (icon
  buttons and low-priority actions), `destructive` (failure or removal). Sizes: `sm` in headers and rows, `icon`
  (`h-7 w-7` or `h-8 w-8`) for icon-only buttons.
- `Badge`: use `variant="outline"` with `border-transparent` plus a token class map for colored badges, so the
  default hover color does not override the token.
- `ScrollArea` for every pane that can grow (rails, drawers, outlines). It sets `overflow-hidden` on the root and
  makes content block-level so `truncate` works.
- `Dialog` for before/after frames. `Collapsible` for step rows and for the Actions drawer. `Sheet` for a drawer
  that must overlay on narrow screens. `Tooltip` for icon-only buttons and verdict help. `Input` for search.

### Reverie kit (`kit.tsx`)

| Component | Use it for |
|---|---|
| `AppHeader` | The sticky top bar of every screen: wordmark, screen name, then children |
| `Brand` | The logo and gradient wordmark. Only inside `AppHeader` |
| `VerdictPill` | A verdict with icon and label, with a help tooltip. `compact` shows the icon only |
| `VerdictIcon` | The verdict icon alone, in the verdict color (running spins when motion is allowed) |
| `VerdictDot` | A small verdict mark for legends and KPI tiles |
| `VerdictStrip` | One segment per step. Use it as the progress bar for a run |
| `ActorTag` | Who acted, with the actor icon on a 15% actor fill. `iconOnly` in dense lists |
| `FrameImg` | An app frame, optionally cropped to the content region |
| `FrameCompare` | Before (target ringed) and after, as After, Before and After, or Swipe |
| `Panel` | A titled card for grouped content |
| `Kbd` | Keycaps for shortcuts. Use Lucide icons for symbol keys (Command, Enter, arrows) |
| `ago` | Formats seconds as `42s`, `3m 18s`, `1h 4m` |

Concept screens live in `ui/src/concepts/`. Run review (`RunReview.tsx`) is the primary one.

## Iconography

Use one icon set: **Lucide, through `react-icons/lu`**. Import named icons (`import { LuCheck } from
"react-icons/lu"`). Do not use emoji or unicode pictographs (such as check marks, crosses, gears, triangles,
circles, or play arrows) as icons anywhere in the UI, including buttons and stories.

- Size: 14px inline with text and in rows, 16px in header buttons, 12px inside badges and keycaps.
- Decorative icons get `aria-hidden`. An icon-only button gets an `aria-label` and a tooltip.
- Icons take the color of their text (`currentColor`). Color them only with token classes.
- Typography marks such as the middle dot, the chevron in breadcrumbs, and the em dash are text, not icons.

| Concept | Icon | Component |
|---|---|---|
| Pass | `LuCheck` | `verdictIcon.pass` |
| App finding | `LuBug` | `verdictIcon["app-fail"]` |
| Harness slip | `LuWrench` | `verdictIcon.harness` |
| Blocked | `LuBan` | `verdictIcon.blocked` |
| Not run | `LuMinus` | `verdictIcon["not-run"]` |
| Running | `LuLoaderCircle` | `verdictIcon.running` |
| Needs you | `LuHand` | `verdictIcon.waiting` |
| Pending | `LuCircle` | `verdictIcon.pending` |
| Laya (clicks and types) | `LuMousePointer2` | `actorIcon.laya` |
| Pilot (decides) | `LuBot` | `actorIcon.pilot` |
| Orchestrator | `LuCompass` | `actorIcon.orchestrator` |
| Person | `LuUser` | `actorIcon.person` |
| Checkpoint: sign-in | `LuKeyRound` | `checkpointIcon["sign-in"]` |
| Checkpoint: database | `LuDatabase` | `checkpointIcon.database` |
| Checkpoint: mail | `LuMail` | `checkpointIcon.mail` |
| Checkpoint: question | `LuCircleHelp` | `checkpointIcon.question` |
| Action: click | `LuMousePointerClick` | `actionIcon.click` |
| Action: type | `LuTextCursorInput` | `actionIcon.type` |
| Action: select | `LuChevronsUpDown` | `actionIcon.select` |
| Action: open page | `LuGlobe` | `actionIcon.goto` |
| Action: wait | `LuHourglass` | `actionIcon.wait` |
| Action: check | `LuSquareCheck` | `actionIcon.check` |
| Action: say | `LuMessageSquareText` | `actionIcon.say` |
| Replay | `LuSquarePlay` | |
| Rerun | `LuRotateCw` | |
| Copy | `LuCopy` | |
| Play narration / stop | `LuVolume2` / `LuPause` | |
| Narration off | `LuVolumeX` | |
| Expand or collapse | `LuChevronDown` (rotates 180 degrees when open) | |
| Open or close the Actions drawer | `LuPanelRightOpen` / `LuPanelRightClose` | |
| Close a dialog | `LuX` | |
| Search | `LuSearch` | |
| Visual review | `LuScanEye` | |
| Run history folder | `LuFolderClock` | |
| Start a spec | `LuPlus` | |
| Inbox | `LuInbox` | |
| Run a command here | `LuTerminal` | |
| Done / Failed / Skip | `LuCheck` / `LuX` / `LuSkipForward` | |
| Keycaps | `LuCommand`, `LuCornerDownLeft`, `LuArrowUp`, `LuArrowDown` | |

Add a new concept icon to `icons.tsx` first, then use it from there.

## Motion

- Keep motion subtle and functional: color transitions on hover (`transition-colors`), the chevron rotation, the
  live dot pulse, and the running spinner.
- Put continuous animation behind `motion-safe:` (`motion-safe:animate-pulse`, `motion-safe:animate-spin`).
- `index.css` also shortens all animation and transition time under `prefers-reduced-motion: reduce`. Do not
  remove that rule.
- Do not animate layout (sliding panels, bouncing lists). The Actions drawer appears and disappears without a
  slide.
- Do not use `animate-ping`.

## Content and voice

Write UI text in a short, plain style that follows Simplified Technical English:

- One idea per sentence. Short sentences. Active voice. Present tense.
- Use the verdict labels exactly: Pass, App finding, Harness slip, Blocked, Not run, Running, Needs you, Pending.
- Name the actor. "The pilot needs a staff sign-in", not "Input required".
- Use sentence case for labels and buttons: "Start a spec", "Rerun", "Show 64 actions".
- Agent notes are first person and factual: "Recorded a card payment of $412.90. The balance is $0.00."
- Do not blame people and do not alarm. Never write "stuck", "stalled", "no progress", or "nudge".
- Never show secrets, passwords, one-time codes, or tokens. The checkpoint note warns when text looks like one.
- Times are 24-hour `HH:MM:SS` in mono. Durations use `ago` (`3m 18s`).

## Accessibility

- Contrast: body text (`#e7e9f0` on `#0b0d14`) and secondary text (`#9299b5`) pass WCAG AA. Verdict colors pass
  AA as text on `background` and `card` (6.6:1 or more), except `verdict-not-run` (4.2:1 on card). That is why
  "Not run" text uses `text-muted-foreground`; use `verdict-not-run` only for fills and marks. On a solid verdict or
  primary fill, use `text-background` (9:1 or more), never white.
- Never use color alone: every verdict has an icon and a label (or an `aria-label` in compact form), and strips
  have an `aria-label` that lists each step.
- Focus: every interactive element shows a visible 2px ring in `--ring` (`focus-visible:ring-2
  focus-visible:ring-ring`). Do not remove outlines without a replacement ring.
- Keyboard: every control is a `button`, link, or form field. Step rows, history items, and action rows are
  buttons. Dialogs trap focus and close with Escape. Toggle buttons set `aria-pressed`; expanders set
  `aria-expanded` (Collapsible does this).
- Landmarks: the history rail and the Actions drawer are labeled `aside` elements; the outline is `main`.
- Images: frames get alt text that says what they show; thumbnails beside a text label use `alt=""`.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Make the spec outline and the agent's notes the main content | Put a flat list of every click in the main column |
| Keep individual actions in the collapsible, scrollable Actions drawer | Let a 60-action list push the outline off screen |
| Open on run history from `.reverie/runs/`, live run pinned first | Show only the live run |
| Split results into pass, app finding, harness slip, blocked, and not run | Show a single "fail" |
| Use theme tokens: `bg-verdict-pass/15 text-verdict-pass` | Use Tailwind palette colors such as `bg-green-950` or `text-red-600` |
| Use static class maps from `kit.tsx` | Build class names with template strings |
| Use Lucide icons from `react-icons/lu` via `icons.tsx` | Use emoji or unicode pictographs, or mix icon sets |
| Put an `aria-label` and tooltip on icon-only buttons | Leave icon-only buttons unnamed |
| Use `text-background` on solid verdict fills | Use `text-white` on light fills |
| Let agents resolve problems and show what they did | Show "stuck", "stalled", "no progress", or "nudge" UI |
| Keep motion behind `motion-safe:` | Add bouncing, sliding, or pinging animation |
| Write short, plain sentences | Write marketing copy or vague status text |

## Agent Prompt Guide

When you change the Reverie UI:

1. Read this file, `ui/src/index.css`, and `ui/src/components/kit.tsx` first.
2. Reuse kit components and `icons.tsx`. Add a shadcn component only when the kit and the existing set cannot do
   the job.
3. Keep the outline-first and history-first layout for anything that shows a run.
4. Run `npx tsc -b` and `npx storybook build` in `ui/`. Take a screenshot at 1600x1000 and check for off-theme color,
   overlap, clipping, horizontal scroll, and emoji.

## Sources

- Google Labs, "Stitch's DESIGN.md format is now open-source":
  https://blog.google/innovation-and-ai/models-and-research/google-labs/stitch-design-md/
- DESIGN.md specification (front matter tokens and section order): https://github.com/google-labs-code/design.md
- VoltAgent, awesome-design-md (community collection and its section style): https://github.com/VoltAgent/awesome-design-md
- Reverie code: `ui/src/index.css`, `ui/tailwind.config.ts`, `ui/src/components/`, `reverie/control/project.py`
  (the `.reverie/` layout).
