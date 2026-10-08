import { useState } from "react";
import { FrameCompare } from "../components/FrameCompare";
import { ActorTag, AppHeader, FrameImg, Kbd, VerdictPill, verdictLabel, verdictText, verdictBg } from "../components/kit";
import type { Action, Run, Verdict } from "../data/types";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardContent } from "../components/ui/card";
import { Alert, AlertDescription } from "../components/ui/alert";
import { ScrollArea } from "../components/ui/scroll-area";
import { cn } from "../lib/utils";
import { LuArrowDown, LuArrowUp, LuCheck, LuRotateCw, LuScanEye, LuSquarePlay, LuX } from "react-icons/lu";

const kindVerb: Record<Action["kind"], string> = {
  click: "clicked", type: "typed", select: "selected", goto: "opened", wait: "waited", check: "checked", say: "said",
};

function Breakdown({ run }: { run: Run }) {
  const counts = run.steps.reduce<Record<string, number>>((a, s) => ({ ...a, [s.verdict]: (a[s.verdict] ?? 0) + 1 }), {});
  const order: Verdict[] = ["pass", "app-fail", "harness", "blocked", "not-run", "waiting", "running", "pending"];
  return (
    <div className="flex gap-4 text-sm">
      {order.filter((v) => counts[v]).map((v) => (
        <span key={v} className={verdictText[v]}><b>{counts[v]}</b> {verdictLabel[v].toLowerCase()}</span>
      ))}
    </div>
  );
}

export function RunView({ run, initialStep = 1 }: { run: Run; initialStep?: number }) {
  const [open, setOpen] = useState<number>(initialStep);
  const firstFramed = (n: number) => run.steps[n - 1]?.actions.findIndex((a) => a.frame) ?? -1;
  const [sel, setSel] = useState<{ step: number; i: number }>({ step: initialStep, i: Math.max(0, firstFramed(initialStep)) });
  const action = run.steps[sel.step - 1]?.actions[sel.i];

  return (
    <div className="flex flex-col h-screen bg-background">
      <AppHeader>
        <div className="flex items-center gap-4 flex-1">
          <Badge variant="outline" className="font-mono text-xs">{run.test}</Badge>
          <h1 className="text-xl font-bold">{run.title}</h1>
          <VerdictPill v={run.verdict} />
        </div>
        <span className="text-sm text-muted-foreground font-mono">{run.session} · {run.started} · {run.duration}</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm"><LuSquarePlay size={14} aria-hidden /> Replay</Button>
          <Button size="sm"><LuRotateCw size={14} aria-hidden /> Rerun</Button>
        </div>
      </AppHeader>

      <div className="px-6 py-3 border-b border-border bg-card">
        <div className="flex items-center gap-6">
          <Breakdown run={run} />
          <div className="flex-1" />
          <span className="text-xs text-muted-foreground">Showing steps and actions · </span>
          <Button variant="ghost" size="sm" className="text-xs">Show all 110 raw events</Button>
        </div>
      </div>

      <div className="grid flex-1 grid-cols-[minmax(460px,1fr)_minmax(0,1.25fr)] gap-6 px-6 py-6 overflow-hidden">
        {/* Left pane: steps */}
        <ScrollArea className="min-w-0 border border-border rounded-lg">
          <ol className="space-y-0">
            {run.steps.map((s) => (
              <li key={s.n} className="border-b border-border last:border-b-0">
                <button
                  onClick={() => setOpen(open === s.n ? 0 : s.n)}
                  aria-expanded={open === s.n}
                  className={`w-full text-left px-4 py-3 hover:bg-muted transition-colors ${open === s.n ? "bg-muted" : ""}`}
                >
                  <div className="flex items-center gap-3">
                    <div className={cn("flex items-center justify-center w-6 h-6 rounded-full flex-none text-xs font-semibold text-background", verdictBg[s.verdict])}>
                      {s.n}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm">
                        {s.admin && <Badge variant="secondary" className="text-xs mr-2 inline-block">admin</Badge>}
                        <span className="truncate">{s.title}</span>
                      </div>
                    </div>
                    <VerdictPill v={s.verdict} compact />
                    {s.seconds && <span className="text-xs text-muted-foreground font-mono">{s.seconds}s</span>}
                  </div>
                </button>

                {open === s.n && (
                  <div className="px-4 py-3 bg-muted space-y-3 border-t border-border">
                    {s.note && <p className="text-sm text-foreground">{s.note}</p>}

                    {s.findings.map((f) => (
                      <Alert
                        key={f.id}
                        variant={f.severity === "high" || f.severity === "medium" ? "destructive" : "default"}
                        className="py-2"
                      >
                        <AlertDescription className="text-xs space-y-1">
                          <div className="font-semibold">{f.what}</div>
                          {f.expected && (
                            <div className="text-muted-foreground">
                              Expected: {f.expected} · Actual: {f.actual}
                            </div>
                          )}
                          <div className="flex gap-2 pt-1">
                            <Button variant="ghost" size="sm" className="text-xs h-6">By design</Button>
                            <Button variant="ghost" size="sm" className="text-xs h-6">Withdraw</Button>
                          </div>
                        </AlertDescription>
                      </Alert>
                    ))}

                    {s.actions.length > 0 && (
                      <ul className="space-y-1">
                        {s.actions.map((a, i) => (
                          <li
                            key={i}
                            onClick={() => a.frame && setSel({ step: s.n, i })}
                            className={`text-xs px-2 py-2 rounded transition-colors cursor-pointer flex items-center gap-2 ${
                              sel.step === s.n && sel.i === i ? "bg-card" : "hover:bg-card/50"
                            }`}
                          >
                            <span className="text-muted-foreground font-mono flex-none">{a.t.slice(3)}</span>
                            {a.kind === "check" ? (
                              <span className={cn("inline-flex items-center gap-1 font-semibold", a.ok ? "text-verdict-pass" : "text-verdict-app-fail")}>
                                {a.ok ? <LuCheck size={14} aria-hidden /> : <LuX size={14} aria-hidden />}
                                {a.ok ? "Pass" : "Fail"}
                              </span>
                            ) : (
                              <ActorTag a={a.actor} />
                            )}
                            <span className="flex-1 min-w-0 truncate text-foreground">
                              {a.kind !== "check" && <span className="text-muted-foreground">{kindVerb[a.kind]} </span>}
                              {a.label}
                              {a.text && <span className="text-primary"> "{a.text}"</span>}
                            </span>
                            {a.frame && <FrameImg src={a.frame.after} crop={a.frame.crop} alt="" className="w-11 h-11 rounded flex-none" />}
                          </li>
                        ))}
                      </ul>
                    )}

                    {s.admin && s.actions.length === 0 && (
                      <p className="text-xs text-muted-foreground">Orchestrator step: no browser actions.</p>
                    )}

                    {s.uiReview && (
                      <div className={cn("text-xs p-2 rounded space-y-1", s.uiReview.ok ? "bg-verdict-pass/15" : "bg-verdict-app-fail/15")}>
                        <span className={cn("inline-flex items-center gap-1 font-medium", s.uiReview.ok ? "text-verdict-pass" : "text-verdict-app-fail")}>
                          <LuScanEye size={14} aria-hidden />
                          {s.uiReview.ok ? "Visual review: no problems" : "Visual review flagged a problem"}
                        </span>
                        <div className="text-muted-foreground">{s.uiReview.summary}</div>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </ScrollArea>

        {/* Right pane: frame compare */}
        <div className="flex min-w-0 flex-col overflow-hidden">
          {action?.frame ? (
            <>
              <FrameCompare
                key={`${sel.step}-${sel.i}`}
                frame={action.frame}
                label={`Step ${sel.step} · ${kindVerb[action.kind]} ${action.label}`}
              />
              <div className="text-xs text-muted-foreground pt-2 flex items-center gap-1">
                <Kbd><LuArrowUp size={12} aria-label="Up" /></Kbd><Kbd><LuArrowDown size={12} aria-label="Down" /></Kbd><span>previous or next action ·</span>
                <Kbd>B</Kbd><span>before/after ·</span>
                <Kbd>N</Kbd><span>narration</span>
              </div>
            </>
          ) : (
            <Card className="flex items-center justify-center flex-1">
              <CardContent className="text-sm text-muted-foreground">
                Pick an action with a frame.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
