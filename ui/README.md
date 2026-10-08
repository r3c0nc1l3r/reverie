# Reverie UI concepts

Design concepts for a more usable reverie dashboard, built with Tailwind v4 and shadcn/ui on Storybook (Vite + React).

```bash
cd ui
npm install
npm run storybook        # http://localhost:6006
```

Start with **Overview**. It lists the problems seen in the current dashboard and maps each concept to them. The first concept, **Run review**, is the primary view: run history from the project's `.reverie/runs/`, the spec outline with the agent's notes, and a drawer for individual actions. **Current UI** shows today's dashboard and replay for comparison.

Design rules (tokens, icons, components, voice) are in [`../DESIGN.md`](../DESIGN.md). Icons come only from Lucide through `react-icons/lu`; see `src/components/icons.tsx`. Do not use emoji.

## Setup

The UI is built on Tailwind CSS v4 and shadcn/ui components:

| Path | What |
|---|---|
| `src/index.css` | Tailwind v4 theme (`@import "tailwindcss"` + `@config "../tailwind.config.ts"`), dark first, with verdict and actor color tokens |
| `tailwind.config.ts` | Tailwind configuration with custom verdict colors (`bg-verdict-pass`, `text-verdict-app-fail`, etc.) and actor tokens |
| `src/components/ui/` | shadcn/ui components (button, badge, card, tabs, toggle-group, textarea, checkbox, label, table, separator, scroll-area, tooltip, slider, alert, progress, kbd, dialog, sheet, input, collapsible) |
| `src/components/kit.tsx` | Reverie kit: verdict pill, icon, dot, and strip; actor tag; cropped frame; AppHeader for sticky headers; static token class maps |
| `src/components/icons.tsx` | The icon for each verdict, actor, checkpoint kind, and action kind (Lucide via `react-icons/lu`) |

To add a new shadcn component:

```bash
npx shadcn@latest add <component-name>
```

After an add, check the new file: replace any `lucide-react` import with the matching `react-icons/lu` icon.

## Concepts

| Path | What |
|---|---|
| `src/concepts/` | The seven UI concepts, with Run review first |
| `src/data/` | Types that mirror `trail.jsonl` and `run.json`, and sample data. `fieldops.ts` holds the run history for the FieldOps demo app. Frames come from the DEMO-01 run against the public practice site. |
| `src/stories/` | Stories and the Overview doc |

These are concepts, not the shipped UI. The Python dashboard in `reverie/control/` is unchanged.
