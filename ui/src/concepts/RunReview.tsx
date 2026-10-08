import { useMemo, useState } from "react";
import {
  LuBug, LuChevronDown, LuCopy, LuFolderClock, LuPanelRightClose, LuPanelRightOpen, LuPause, LuRotateCw, LuScanEye,
  LuSearch, LuSquarePlay, LuVolume2, LuVolumeX, LuX,
} from "react-icons/lu";
import { FrameCompare } from "../components/FrameCompare";
import { actionIcon } from "../components/icons";
import {
  ActorTag, AppHeader, ago, FrameImg, VerdictIcon, VerdictPill, VerdictStrip, actorName, severityClasses, verdictLabel,
  verdictText,
} from "../components/kit";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { ScrollArea } from "../components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "../components/ui/tooltip";
import { history as defaultHistory, project, runFor } from "../data/fieldops";
import type { Action, Frame, Note, Run, RunSummary, Step, Verdict } from "../data/types";
import { cn } from "../lib/utils";

const verb: Record<Action["kind"], string> = {
  click: "Clicked", type: "Typed in", select: "Selected in", goto: "Opened", wait: "Waited", check: "Checked", say: "Said",
};

const judged = (v: Verdict) => v !== "pending" && v !== "running" && v !== "waiting";

// ---------------------------------------------------------------------------------------------------------------
// History rail

function HistoryItem({ r, active, onPick }: { r: RunSummary; active: boolean; onPick: () => void }) {
  const done = r.steps.filter(judged).length;
  return (
    <button
      type="button"
      onClick={onPick}
      aria-current={active ? "true" : undefined}
      className={cn(
        "w-full rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        r.live ? "border-verdict-running/40 bg-verdict-running/10" : "border-transparent",
        active ? "bg-muted ring-1 ring-primary/60" : "hover:bg-muted/60",
      )}
    >
      <div className="flex items-center gap-2 text-xs">
        <VerdictIcon v={r.verdict} />
        <span className="font-mono font-medium text-foreground">{r.spec}</span>
        {r.live && (
          <span className="inline-flex items-center gap-1 font-semibold text-verdict-running">
            <span className="h-1.5 w-1.5 rounded-full bg-verdict-running motion-safe:animate-pulse" aria-hidden />
            Live
          </span>
        )}
        <span className="ml-auto font-mono text-muted-foreground">{r.started}</span>
      </div>
      <div className="mt-1 line-clamp-2 text-sm text-foreground">{r.title}</div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex-1"><VerdictStrip verdicts={r.steps} height={4} /></div>
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{done}/{r.steps.length}</span>
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
        <span className={verdictText[r.verdict]}>{verdictLabel[r.verdict]}</span>
        <span className="font-mono">{r.duration}</span>
      </div>
    </button>
  );
}

function HistoryRail({ runs, selected, onPick }: { runs: RunSummary[]; selected: string; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const shown = runs.filter((r) => `${r.spec} ${r.title} ${r.session}`.toLowerCase().includes(q.toLowerCase()));
  const live = shown.filter((r) => r.live);
  const days = [...new Set(shown.filter((r) => !r.live).map((r) => r.day))];

  return (
    <aside className="flex min-h-0 flex-col border-r border-border bg-card" aria-label="Run history">
      <div className="space-y-3 border-b border-border p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Runs</h2>
          <span className="text-xs text-muted-foreground">{runs.length} stored</span>
        </div>
        <div className="relative">
          <LuSearch size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search spec or title" aria-label="Search runs" className="pl-8" />
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-4 p-3">
          {live.length > 0 && (
            <section className="space-y-1">
              <h3 className="px-1 text-xs font-semibold text-verdict-running">Current run</h3>
              {live.map((r) => <HistoryItem key={r.id} r={r} active={r.id === selected} onPick={() => onPick(r.id)} />)}
            </section>
          )}
          {days.map((d) => (
            <section key={d} className="space-y-1">
              <h3 className="px-1 text-xs font-semibold text-muted-foreground">{d}</h3>
              {shown.filter((r) => !r.live && r.day === d).map((r) => (
                <HistoryItem key={r.id} r={r} active={r.id === selected} onPick={() => onPick(r.id)} />
              ))}
            </section>
          ))}
          {shown.length === 0 && <p className="px-1 text-sm text-muted-foreground">No runs match "{q}".</p>}
        </div>
      </ScrollArea>
      <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-xs text-muted-foreground">
        <LuFolderClock size={14} aria-hidden className="flex-none" />
        <span className="truncate font-mono" title={project.dir}>{project.dir}</span>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Outline

function NoteLine({ n, playing, onPlay, last, live }: { n: Note; playing: boolean; onPlay: () => void; last: boolean; live: boolean }) {
  return (
    <li className={cn("relative flex gap-3 rounded-md py-1.5 pl-5 pr-1", playing && "bg-primary/10")}>
      <span aria-hidden className={cn("absolute left-[5px] top-3.5 h-2 w-2 rounded-full", live && last ? "bg-verdict-running motion-safe:animate-pulse" : "bg-border")} />
      <span className="w-16 flex-none pt-0.5 font-mono text-xs text-muted-foreground">{n.t}</span>
      <p className="flex-1 text-sm leading-relaxed text-foreground">{n.text}</p>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 flex-none text-muted-foreground hover:text-accent-foreground"
            aria-label={`${playing ? "Stop" : "Play"} ${actorName[n.actor]} note at ${n.t}`}
            aria-pressed={playing}
            onClick={onPlay}
          >
            {playing ? <LuPause size={14} aria-hidden /> : <LuVolume2 size={14} aria-hidden />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{playing ? "Stop narration" : "Play narration"}</TooltipContent>
      </Tooltip>
    </li>
  );
}

function StepRow({ s, current, selected, open, onToggle, onActions, playing, onPlay, onFrame }: {
  s: Step; current: boolean; selected: boolean; open: boolean; onToggle: () => void; onActions: () => void;
  playing: string | null; onPlay: (key: string) => void; onFrame: (frame: Frame, label: string) => void;
}) {
  const pending = s.verdict === "pending" || s.verdict === "not-run";
  const notes = s.notes ?? [];
  return (
    <li>
      <Collapsible open={open} onOpenChange={onToggle}>
        <div
          className={cn(
            "rounded-xl border bg-card transition-colors",
            current ? "border-verdict-running/60 bg-verdict-running/5" : selected ? "border-primary/50" : "border-border",
            pending && "opacity-70",
          )}
        >
          <div className="flex items-center gap-3 p-4">
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="flex min-w-0 flex-1 items-start gap-4 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full text-sm font-semibold",
                    current ? "bg-verdict-running/15 text-verdict-running" : pending ? "bg-muted text-muted-foreground" : "bg-muted text-foreground",
                  )}
                >
                  {s.n}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-base font-medium leading-snug text-foreground">{s.title}</span>
                  <span className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                    {current ? (
                      <span className="font-semibold text-verdict-running">The agent is on this step</span>
                    ) : pending ? (
                      <span>{s.verdict === "not-run" ? "Not run" : "Not started"}</span>
                    ) : (
                      <span>{notes.length} {notes.length === 1 ? "note" : "notes"}</span>
                    )}
                    {s.started && <span className="font-mono">{s.started}</span>}
                    {s.seconds !== undefined && <span className="font-mono">{ago(s.seconds)}</span>}
                    {s.findings.length > 0 && (
                      <span className="inline-flex items-center gap-1 text-verdict-app-fail">
                        <LuBug size={12} aria-hidden /> {s.findings.length} finding
                      </span>
                    )}
                  </span>
                </span>
                <VerdictPill v={s.verdict} />
                <LuChevronDown
                  size={16}
                  aria-hidden
                  className={cn("mt-1.5 flex-none text-muted-foreground transition-transform", open && "rotate-180")}
                />
              </button>
            </CollapsibleTrigger>
          </div>

          <CollapsibleContent>
            <div className="space-y-4 border-t border-border px-4 pb-4 pt-3 sm:pl-16">
              {notes.length > 0 ? (
                <ol className="relative space-y-0.5 before:absolute before:bottom-3 before:left-[8px] before:top-3 before:w-px before:bg-border" aria-label={`Notes for step ${s.n}`}>
                  {notes.map((n, i) => {
                    const key = `${s.n}-${i}`;
                    return (
                      <NoteLine key={key} n={n} last={i === notes.length - 1} live={current} playing={playing === key} onPlay={() => onPlay(key)} />
                    );
                  })}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">No notes yet.</p>
              )}

              {s.findings.map((f) => (
                <div key={f.id} className={cn("rounded-lg border-l-4 p-3", severityClasses[f.severity].border, "bg-verdict-app-fail/10")}>
                  <div className="flex items-center gap-2 text-xs">
                    <LuBug size={14} aria-hidden className="text-verdict-app-fail" />
                    <span className="font-semibold text-verdict-app-fail">App finding</span>
                    <Badge variant="outline" className={cn("border-transparent", severityClasses[f.severity].badge)}>{f.severity}</Badge>
                    <span className="font-mono text-muted-foreground">{f.id}</span>
                    <span className="text-muted-foreground">{f.state}</span>
                  </div>
                  <p className="mt-2 text-sm font-medium text-foreground">{f.what}</p>
                  {(f.expected || f.actual) && (
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                      <dt className="text-muted-foreground">Expected</dt><dd>{f.expected}</dd>
                      <dt className="text-muted-foreground">Actual</dt><dd>{f.actual}</dd>
                    </dl>
                  )}
                  {f.frame && (
                    <Button variant="outline" size="sm" className="mt-3" onClick={() => onFrame({ after: f.frame!, crop: s.actions[0]?.frame?.crop }, `${f.id} · ${f.what}`)}>
                      <LuScanEye size={14} aria-hidden /> View frame
                    </Button>
                  )}
                </div>
              ))}

              <div className="flex flex-wrap items-center gap-3">
                {s.uiReview && (
                  <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs", s.uiReview.ok ? "bg-verdict-pass/15 text-verdict-pass" : "bg-verdict-app-fail/15 text-verdict-app-fail")}>
                    <LuScanEye size={14} aria-hidden />
                    <span className="font-medium">{s.uiReview.ok ? "Visual review: no problems" : "Visual review: problem found"}</span>
                    <span className="text-muted-foreground">{s.uiReview.summary}</span>
                  </span>
                )}
                <div className="flex-1" />
                {s.actions.length > 0 && (
                  <Button variant="outline" size="sm" onClick={onActions} aria-label={`Show ${s.actions.length} actions for step ${s.n}`}>
                    <LuPanelRightOpen size={14} aria-hidden /> {s.actions.length} actions
                  </Button>
                )}
              </div>
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </li>
  );
}

function RunSummaryHeader({ run, live }: { run: Run; live: boolean }) {
  const verdicts = run.steps.map((s) => s.verdict);
  const done = verdicts.filter(judged).length;
  const current = run.steps.find((s) => s.verdict === "running");
  const counts = verdicts.reduce<Partial<Record<Verdict, number>>>((a, v) => ({ ...a, [v]: (a[v] ?? 0) + 1 }), {});
  const order: Verdict[] = ["pass", "app-fail", "harness", "blocked", "not-run"];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant="outline" className="font-mono">{run.test}</Badge>
        <h1 className="text-2xl font-semibold tracking-tight">{run.title}</h1>
        <VerdictPill v={run.verdict} />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
        <span>Session <span className="font-mono text-foreground">{run.session}</span></span>
        <span>Started <span className="font-mono text-foreground">{run.started}</span></span>
        <span>{live ? "Running for" : "Took"} <span className="font-mono text-foreground">{run.duration}</span></span>
        <span className="inline-flex items-center gap-1">
          <span className="font-mono">.reverie/runs/{run.id}</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7" aria-label="Copy the run folder path">
                <LuCopy size={14} aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Copy the run folder path</TooltipContent>
          </Tooltip>
        </span>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-foreground">
            <b className="tabular-nums">{done}</b> of {run.steps.length} steps judged
            {current && <span className="text-verdict-running"> · step {current.n} in progress</span>}
          </span>
          <span className="flex gap-4">
            {order.filter((v) => counts[v]).map((v) => (
              <span key={v} className={verdictText[v]}><b className="tabular-nums">{counts[v]}</b> {verdictLabel[v].toLowerCase()}</span>
            ))}
          </span>
        </div>
        <VerdictStrip verdicts={verdicts} height={8} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Actions drawer

function ActionsDrawer({ step, onClose, onOpen }: { step: Step; onClose: () => void; onOpen: (i: number) => void }) {
  return (
    <aside className="flex min-h-0 w-[400px] flex-col border-l border-border bg-card" aria-label={`Actions for step ${step.n}`}>
      <div className="flex items-start gap-2 border-b border-border p-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Actions · step {step.n}</h2>
          <p className="truncate text-xs text-muted-foreground" title={step.title}>{step.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">{step.actions.length} actions. Select one to see its before and after frames.</p>
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose} aria-label="Close the actions drawer">
          <LuPanelRightClose size={16} aria-hidden />
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <ol className="divide-y divide-border">
          {step.actions.map((a, i) => {
            const I = actionIcon[a.kind];
            return (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => onOpen(i)}
                  className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                >
                  <span className="w-14 flex-none font-mono text-xs text-muted-foreground">{a.t}</span>
                  <ActorTag a={a.actor} iconOnly />
                  <I size={14} aria-hidden className="flex-none text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">
                    <span className="text-muted-foreground">{verb[a.kind]} </span>
                    <span className="text-foreground">{a.label}</span>
                    {a.text && <span className="text-primary"> "{a.text}"</span>}
                  </span>
                  {a.kind === "check" ? (
                    <VerdictIcon v={a.ok ? "pass" : "app-fail"} />
                  ) : a.frame ? (
                    <FrameImg src={a.frame.after} crop={a.frame.crop} alt="" className="w-14 flex-none rounded-sm border border-border" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ol>
      </ScrollArea>
    </aside>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Page

export function RunReview({ runs = defaultHistory, initialRun, initialStep, drawerOpen = false }: {
  runs?: RunSummary[]; initialRun?: string; initialStep?: number; drawerOpen?: boolean;
}) {
  const [runId, setRunId] = useState(initialRun ?? runs[0].id);
  const summary = runs.find((r) => r.id === runId) ?? runs[0];
  const run = useMemo(() => runFor(summary), [summary]);
  const focus = (r: Run) => r.steps.find((s) => s.verdict === "running")?.n ?? r.steps.find((s) => s.findings.length)?.n ?? 1;

  const [stepN, setStepN] = useState(initialStep ?? focus(run));
  const [open, setOpen] = useState<Set<number>>(() => new Set([initialStep ?? focus(run)]));
  const [drawer, setDrawer] = useState(drawerOpen);
  const [narration, setNarration] = useState(true);
  const [playing, setPlaying] = useState<string | null>(null);
  const [view, setView] = useState<{ frame: Frame; label: string; sub?: string } | null>(null);

  const step = run.steps.find((s) => s.n === stepN) ?? run.steps[0];

  const pickRun = (id: string) => {
    const next = runFor(runs.find((r) => r.id === id)!);
    const n = focus(next);
    setRunId(id); setStepN(n); setOpen(new Set([n])); setPlaying(null);
  };
  const toggle = (n: number) => {
    setStepN(n);
    setOpen((o) => { const x = new Set(o); if (x.has(n)) x.delete(n); else x.add(n); return x; });
  };
  const openAction = (i: number) => {
    const a = step.actions[i];
    if (!a.frame) return;
    setView({ frame: a.frame, label: `Step ${step.n} · ${verb[a.kind].toLowerCase()} ${a.label}`, sub: `${a.t} · ${actorName[a.actor]}` });
  };

  return (
    <div className="flex h-screen flex-col bg-background">
      <AppHeader sub="Run review">
        <Badge variant="outline" className="font-mono">{project.name}</Badge>
        <div className="flex-1" />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="sm" aria-pressed={narration} onClick={() => { setNarration(!narration); setPlaying(null); }}>
              {narration ? <LuVolume2 size={16} aria-hidden /> : <LuVolumeX size={16} aria-hidden />}
              Narration {narration ? "on" : "off"}
            </Button>
          </TooltipTrigger>
          <TooltipContent>Speak new notes aloud while the agent works</TooltipContent>
        </Tooltip>
        <Button variant="outline" size="sm" aria-pressed={drawer} onClick={() => setDrawer(!drawer)}>
          {drawer ? <LuPanelRightClose size={16} aria-hidden /> : <LuPanelRightOpen size={16} aria-hidden />}
          Actions
        </Button>
        {!summary.live && (
          <Button variant="outline" size="sm"><LuSquarePlay size={16} aria-hidden /> Replay</Button>
        )}
        <Button size="sm"><LuRotateCw size={16} aria-hidden /> Rerun</Button>
      </AppHeader>

      <div className={cn("grid min-h-0 flex-1", drawer ? "grid-cols-[300px_minmax(0,1fr)_400px]" : "grid-cols-[300px_minmax(0,1fr)]")}>
        <HistoryRail runs={runs} selected={runId} onPick={pickRun} />

        <main className="min-h-0 min-w-0">
          <ScrollArea className="h-full">
            <div className="mx-auto max-w-4xl space-y-6 px-8 py-6">
              <RunSummaryHeader run={run} live={!!summary.live} />
              <section aria-label="Spec outline" className="space-y-3">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Spec outline</h2>
                <ol className="space-y-3">
                  {run.steps.map((s) => (
                    <StepRow
                      key={`${run.id}-${s.n}`}
                      s={s}
                      current={s.verdict === "running"}
                      selected={drawer && s.n === step.n}
                      open={open.has(s.n)}
                      onToggle={() => toggle(s.n)}
                      onActions={() => { setStepN(s.n); setDrawer(true); }}
                      playing={playing?.startsWith(`${run.id}:`) ? playing.slice(run.id.length + 1) : null}
                      onPlay={(key) => setPlaying((p) => (p === `${run.id}:${key}` ? null : `${run.id}:${key}`))}
                      onFrame={(frame, label) => setView({ frame, label })}
                    />
                  ))}
                </ol>
              </section>
            </div>
          </ScrollArea>
        </main>

        {drawer && <ActionsDrawer step={step} onClose={() => setDrawer(false)} onOpen={openAction} />}
      </div>

      <Dialog open={!!view} onOpenChange={(o) => !o && setView(null)}>
        <DialogContent className="sm:max-w-5xl" showCloseButton={false}>
          {view && (
            <>
              <DialogHeader className="flex-row items-start justify-between gap-4">
                <div className="space-y-1">
                  <DialogTitle>{view.label}</DialogTitle>
                  <DialogDescription>{view.sub ?? "Frame recorded with the finding"}</DialogDescription>
                </div>
                <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setView(null)} aria-label="Close">
                  <LuX size={16} aria-hidden />
                </Button>
              </DialogHeader>
              <FrameCompare frame={view.frame} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
