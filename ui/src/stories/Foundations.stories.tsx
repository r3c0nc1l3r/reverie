import { Fragment } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { IconType } from "react-icons";
import { actionIcon, actorIcon, checkpointIcon, verdictIcon } from "../components/icons";
import { ActorTag, Kbd, VerdictDot, VerdictPill, verdictHelp, verdictLabel } from "../components/kit";
import type { Verdict } from "../data/types";
import { LuCommand, LuCornerDownLeft } from "react-icons/lu";

const meta: Meta = { title: "Foundations", parameters: { layout: "padded" } };
export default meta;

const all: Verdict[] = ["pass", "app-fail", "harness", "blocked", "not-run", "running", "waiting", "pending"];

/**
 * Verdicts: Today "fail" covers four different situations. The concepts split it so the reason shows without opening the run.
 */
export const Verdicts: StoryObj = {
  render: () => (
    <div className="grid grid-cols-3 gap-5 max-w-3xl auto-rows-max">
      {all.map((v) => (
        <Fragment key={v}>
          <div className="flex items-center gap-2">
            <VerdictPill v={v} />
            <VerdictDot v={v} size={12} />
          </div>
          <span className="col-span-2 self-center text-sm text-muted-foreground">
            <b className="text-foreground">{verdictLabel[v]}.</b> {verdictHelp[v]}
          </span>
        </Fragment>
      ))}
    </div>
  ),
};

/**
 * Actors: Who did it. Laya clicks, the pilot decides, you handle checkpoints.
 */
export const Actors: StoryObj = {
  render: () => (
    <div className="flex gap-3 items-center">
      <ActorTag a="laya" />
      <ActorTag a="pilot" />
      <ActorTag a="orchestrator" />
      <ActorTag a="person" />
      <span className="ml-6 text-sm text-muted-foreground">
        Shortcuts use keycaps: <Kbd>J</Kbd> <Kbd>K</Kbd> <Kbd><LuCommand size={12} aria-label="Command" /></Kbd>
        <Kbd><LuCornerDownLeft size={12} aria-label="Enter" /></Kbd>
      </span>
    </div>
  ),
};

/**
 * Theme: Core theme colors, verdict states, and actor roles displayed as color swatches.
 */
export const Theme: StoryObj = {
  render: () => {
    const coreTokens = [
      { name: "--background", var: "var(--background)" },
      { name: "--foreground", var: "var(--foreground)" },
      { name: "--card", var: "var(--card)" },
      { name: "--primary", var: "var(--primary)" },
      { name: "--secondary", var: "var(--secondary)" },
      { name: "--accent", var: "var(--accent)" },
      { name: "--muted", var: "var(--muted)" },
      { name: "--border", var: "var(--border)" },
    ];
    const verdictTokens = [
      { name: "--verdict-pass", var: "var(--verdict-pass)" },
      { name: "--verdict-app-fail", var: "var(--verdict-app-fail)" },
      { name: "--verdict-harness", var: "var(--verdict-harness)" },
      { name: "--verdict-blocked", var: "var(--verdict-blocked)" },
      { name: "--verdict-not-run", var: "var(--verdict-not-run)" },
      { name: "--verdict-running", var: "var(--verdict-running)" },
      { name: "--verdict-waiting", var: "var(--verdict-waiting)" },
    ];
    const actorTokens = [
      { name: "--actor-laya", var: "var(--actor-laya)" },
      { name: "--actor-pilot", var: "var(--actor-pilot)" },
      { name: "--actor-orchestrator", var: "var(--actor-orchestrator)" },
      { name: "--actor-person", var: "var(--actor-person)" },
    ];
    return (
      <div className="space-y-6">
        <div>
          <h3 className="text-sm font-semibold mb-3">Core</h3>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(120px,1fr))]">
            {coreTokens.map((t) => (
              <div key={t.name} className="text-center">
                <div className="border border-border rounded-lg overflow-hidden h-20 mb-2">
                  <div className="h-full" style={{ background: t.var }} />
                </div>
                <div className="font-mono text-xs text-muted-foreground truncate">{t.name}</div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold mb-3">Verdicts</h3>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(120px,1fr))]">
            {verdictTokens.map((t) => (
              <div key={t.name} className="text-center">
                <div className="border border-border rounded-lg overflow-hidden h-20 mb-2">
                  <div className="h-full" style={{ background: t.var }} />
                </div>
                <div className="font-mono text-xs text-muted-foreground truncate">{t.name}</div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold mb-3">Actors</h3>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(120px,1fr))]">
            {actorTokens.map((t) => (
              <div key={t.name} className="text-center">
                <div className="border border-border rounded-lg overflow-hidden h-20 mb-2">
                  <div className="h-full" style={{ background: t.var }} />
                </div>
                <div className="font-mono text-xs text-muted-foreground truncate">{t.name}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  },
};

/**
 * Icons: one set, Lucide through `react-icons/lu`. Each concept has one icon. No emoji or unicode pictographs.
 */
export const Icons: StoryObj = {
  render: () => {
    const groups: { title: string; items: [string, IconType][] }[] = [
      { title: "Verdicts", items: Object.entries(verdictIcon) },
      { title: "Actors", items: Object.entries(actorIcon) },
      { title: "Checkpoint kinds", items: Object.entries(checkpointIcon) },
      { title: "Action kinds", items: Object.entries(actionIcon) },
    ];
    return (
      <div className="grid max-w-4xl grid-cols-2 gap-6">
        {groups.map((g) => (
          <section key={g.title}>
            <h3 className="mb-2 text-sm font-semibold">{g.title}</h3>
            <ul className="space-y-1.5">
              {g.items.map(([name, I]) => (
                <li key={name} className="flex items-center gap-3 text-sm">
                  <I size={16} aria-hidden className="text-muted-foreground" />
                  <span className="font-mono text-xs">{name}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    );
  },
};
