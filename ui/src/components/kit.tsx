import type { CSSProperties, ReactNode } from "react";
import type { Actor, Frame as FrameT, Verdict } from "../data/types";
import { Badge } from "./ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";
import { Kbd as ShadKbd } from "./ui/kbd";
import { Card, CardContent, CardHeader } from "./ui/card";
import { Separator } from "./ui/separator";
import { actorIcon, verdictIcon } from "./icons";
import { cn } from "../lib/utils";

export const verdictLabel: Record<Verdict, string> = {
  pass: "Pass",
  "app-fail": "App finding",
  harness: "Harness slip",
  blocked: "Blocked",
  "not-run": "Not run",
  running: "Running",
  waiting: "Needs you",
  pending: "Pending",
};

// Static color lookups for verdict badges and UI elements
export const verdictBg: Record<Verdict, string> = {
  pass: "bg-verdict-pass",
  "app-fail": "bg-verdict-app-fail",
  harness: "bg-verdict-harness",
  blocked: "bg-verdict-blocked",
  "not-run": "bg-verdict-not-run",
  running: "bg-verdict-running",
  waiting: "bg-verdict-waiting",
  pending: "bg-muted",
};

export const verdictText: Record<Verdict, string> = {
  pass: "text-verdict-pass",
  "app-fail": "text-verdict-app-fail",
  harness: "text-verdict-harness",
  blocked: "text-verdict-blocked",
  "not-run": "text-muted-foreground",
  running: "text-verdict-running",
  waiting: "text-verdict-waiting",
  pending: "text-muted-foreground",
};

// Soft fills and edges use only theme tokens, at 15% for fills. Keep these maps static: Tailwind cannot see
// class names built with template strings.
export const verdictSoftBg: Record<Verdict, string> = {
  pass: "bg-verdict-pass/15",
  "app-fail": "bg-verdict-app-fail/15",
  harness: "bg-verdict-harness/15",
  blocked: "bg-verdict-blocked/15",
  "not-run": "bg-verdict-not-run/15",
  running: "bg-verdict-running/15",
  waiting: "bg-verdict-waiting/15",
  pending: "bg-muted",
};

export const verdictBorder: Record<Verdict, string> = {
  pass: "border-l-verdict-pass",
  "app-fail": "border-l-verdict-app-fail",
  harness: "border-l-verdict-harness",
  blocked: "border-l-verdict-blocked",
  "not-run": "border-l-verdict-not-run",
  running: "border-l-verdict-running",
  waiting: "border-l-verdict-waiting",
  pending: "border-l-border",
};

export const severityClasses: Record<"high" | "medium" | "low", { bg: string; border: string; text: string; badge: string }> = {
  high: { bg: "bg-verdict-app-fail/15", border: "border-l-verdict-app-fail", text: "text-verdict-app-fail", badge: "bg-verdict-app-fail/15 text-verdict-app-fail" },
  medium: { bg: "bg-verdict-blocked/15", border: "border-l-verdict-blocked", text: "text-verdict-blocked", badge: "bg-verdict-blocked/15 text-verdict-blocked" },
  low: { bg: "bg-verdict-running/15", border: "border-l-verdict-running", text: "text-verdict-running", badge: "bg-verdict-running/15 text-verdict-running" },
};

export const actorSoftBg: Record<Actor, string> = {
  laya: "bg-actor-laya/15 text-actor-laya",
  pilot: "bg-actor-pilot/15 text-actor-pilot",
  orchestrator: "bg-actor-orchestrator/15 text-actor-orchestrator",
  person: "bg-actor-person/15 text-actor-person",
};

export const verdictHelp: Record<Verdict, string> = {
  pass: "Every check passed and no medium or high finding is open.",
  "app-fail": "The application did the wrong thing. This is a real defect.",
  harness: "The test or the tooling went wrong. The app may be fine.",
  blocked: "The environment, a fixture, or a decision prevented the test.",
  "not-run": "Skipped on purpose (for example, a missing credential).",
  running: "The pilot is working on it now.",
  waiting: "The pilot needs the orchestrator (sign-in, data proof, or a decision).",
  pending: "Not started.",
};

/**
 * VerdictIcon draws the Lucide icon for a verdict in the verdict color. The running icon spins only when motion is allowed.
 */
export function VerdictIcon({ v, size = 14, className }: { v: Verdict; size?: number; className?: string }) {
  const I = verdictIcon[v];
  return (
    <I size={size} aria-hidden className={cn("flex-none", verdictText[v], v === "running" && "motion-safe:animate-spin", className)} />
  );
}


/**
 * VerdictPill displays a verdict status with icon and label, wrapped in a tooltip.
 */
export function VerdictPill({ v, compact }: { v: Verdict; compact?: boolean }) {
  const content = (
    <div
      className={cn("inline-flex items-center gap-1.5 rounded-full py-1 text-sm font-semibold whitespace-nowrap", compact ? "px-1.5" : "px-3", verdictSoftBg[v], verdictText[v])}
      aria-label={compact ? verdictLabel[v] : undefined}
    >
      <VerdictIcon v={v} />
      {!compact && verdictLabel[v]}
    </div>
  );

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent>{verdictHelp[v]}</TooltipContent>
    </Tooltip>
  );
}

/**
 * VerdictDot is a small colored circle indicating verdict status, with pulse animation for running/waiting.
 */
export function VerdictDot({ v, size = 10 }: { v: Verdict; size?: number }) {
  const baseClasses = "inline-block rounded-full flex-none";
  const colorClass = {
    pass: "bg-verdict-pass",
    "app-fail": "bg-verdict-app-fail",
    harness: "bg-verdict-harness",
    blocked: "bg-verdict-blocked",
    "not-run": "bg-verdict-not-run",
    running: "bg-verdict-running motion-safe:animate-pulse",
    waiting: "bg-verdict-waiting motion-safe:animate-pulse",
    pending: "border-2 border-border",
  }[v];

  return (
    <span
      className={`${baseClasses} ${colorClass}`}
      style={{ width: size, height: size }}
      title={verdictLabel[v]}
    />
  );
}

/**
 * VerdictStrip displays a flex row of verdict segments, one per step.
 */
export function VerdictStrip({ verdicts, height = 6 }: { verdicts: Verdict[]; height?: number }) {
  return (
    <div
      className="flex gap-0.5 w-full"
      style={{ height }}
      role="img"
      aria-label={verdicts.map((v, i) => `step ${i + 1} ${verdictLabel[v]}`).join(", ")}
    >
      {verdicts.map((v, i) => (
        <span
          key={i}
          className={`flex-1 rounded-sm ${
            {
              pass: "bg-verdict-pass",
              "app-fail": "bg-verdict-app-fail",
              harness: "bg-verdict-harness",
              blocked: "bg-verdict-blocked",
              "not-run": "bg-verdict-not-run",
              running: "bg-verdict-running",
              waiting: "bg-verdict-waiting",
              pending: "bg-muted",
            }[v]
          }`}
        />
      ))}
    </div>
  );
}

export const actorName: Record<Actor, string> = { laya: "Laya", pilot: "Pilot", orchestrator: "You", person: "Person" };

/**
 * ActorTag names who acted: actor color text on a 15% actor background, with the actor icon.
 * Use `iconOnly` in dense lists; the name stays available to screen readers.
 */
export function ActorTag({ a, iconOnly }: { a: Actor; iconOnly?: boolean }) {
  const I = actorIcon[a];
  return (
    <Badge
      variant="outline"
      className={cn("gap-1 border-transparent text-xs font-semibold", iconOnly && "px-1.5", actorSoftBg[a])}
      title={actorName[a]}
    >
      <I size={12} aria-hidden />
      {iconOnly ? <span className="sr-only">{actorName[a]}</span> : actorName[a]}
    </Badge>
  );
}

/**
 * Kbd re-exports shadcn Kbd component for keyboard key display.
 */
export { ShadKbd as Kbd };

/**
 * ago formats seconds into human-readable elapsed time.
 */
export function ago(s: number) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60 ? `${s % 60}s` : ""}`.trim();
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/**
 * FrameImg displays a browser frame, optionally cropped to the region with content.
 */
export function FrameImg({ src, crop, alt, style, className }: {
  src: string; crop?: FrameT["crop"]; alt: string; style?: CSSProperties; className?: string;
}) {
  if (!crop) return <img className={`rounded-lg ${className ?? ""}`} src={src} alt={alt} style={style} />;
  const scale = 100 / crop.w;
  return (
    <div
      className={`relative overflow-hidden rounded-lg bg-white ${className ?? ""}`}
      style={{ aspectRatio: `${(crop.w * 16) / (crop.h * 9)}`, ...style }}
    >
      <img className="absolute left-0 top-0 block max-w-none"
        src={src}
        alt={alt}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: `${scale * 100}%`,
          transform: `translate(${-crop.x}%, ${-crop.y}%)`,
          transformOrigin: "0 0",
        }}
      />
    </div>
  );
}

/**
 * Panel displays a card with optional header and content area.
 */
export function Panel({ title, right, children, className }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <Card className={className}>
      {(title || right) && (
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          {title && <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>}
          {right}
        </CardHeader>
      )}
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/**
 * Brand displays the Reverie logo and name.
 */
export function Brand() {
  return (
    <div className="flex items-center gap-2">
      <img src={`${import.meta.env.BASE_URL}logo.svg`} alt="" width={22} height={22} />
      <span
        className="brand text-lg font-semibold"
        style={{
          background: "linear-gradient(90deg, #f6d6ff 0%, #9cc4ff 50%, #7ee7c7 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        Reverie
      </span>
    </div>
  );
}

/**
 * AppHeader is a sticky top bar with Brand, separator, sub, and children laid out left to right.
 */
export function AppHeader({ sub, children }: { sub?: string; children?: ReactNode }) {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-card">
      <div className="flex items-center gap-3 px-6 py-3">
        <Brand />
        {sub && (
          <>
            <Separator orientation="vertical" className="h-6" />
            <span className="text-sm text-muted-foreground whitespace-nowrap">{sub}</span>
          </>
        )}
        {children}
      </div>
    </header>
  );
}
