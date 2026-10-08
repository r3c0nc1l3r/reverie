import { useState } from "react";
import { AppHeader, FrameImg, severityClasses } from "../components/kit";
import { crop, findings } from "../data/sample";
import type { Finding, FindingState } from "../data/types";
import { Card, CardContent } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { cn } from "../lib/utils";

const stateLabel: Record<FindingState, string> = { open: "Open", "by-design": "By design", withdrawn: "Withdrawn", fixed: "Fixed" };
const stateHelp: Record<FindingState, string> = {
  open: "Needs a decision or a fix.",
  "by-design": "The app works as intended. Kept so the pilot does not raise it again.",
  withdrawn: "The finding was wrong (a harness mistake). A playbook lesson prevents a repeat.",
  fixed: "A commit fixed it and a rerun confirmed it.",
};

function FindingCard({ f, onPick, picked }: { f: Finding; onPick: () => void; picked: boolean }) {
  const severity = severityClasses[f.severity];
  return (
    <button
      onClick={onPick}
      className={cn(
        "w-full text-left border-l-4 transition-all",
        severity.bg,
        severity.border,
        picked ? "ring-2 ring-primary" : ""
      )}
    >
      <Card className="bg-card border-0">
        <CardContent className="p-4 space-y-2">
          <div className="flex items-start gap-2">
            <Badge variant="outline" className={cn("border-transparent text-xs flex-shrink-0", severity.badge)}>
              {f.severity}
            </Badge>
            <span className="font-mono text-xs text-muted-foreground">{f.id}</span>
            <span className="text-xs text-muted-foreground">{f.test} · step {f.step}</span>
          </div>
          <div className={`text-sm font-medium ${f.state === "withdrawn" || f.state === "fixed" ? "line-through text-muted-foreground" : ""}`}>
            {f.what}
          </div>
          {f.note && <div className="text-xs text-muted-foreground">{f.note}</div>}
          <div className="text-xs text-muted-foreground pt-2 border-t border-border">
            {f.source === "ui-review" ? "visual review" : "pilot"}
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

export function FindingsTriage() {
  const [picked, setPicked] = useState(findings[0].id);
  const f = findings.find((x) => x.id === picked)!;
  const cols: FindingState[] = ["open", "by-design", "withdrawn", "fixed"];

  return (
    <div className="flex flex-col h-screen bg-background">
      <AppHeader sub="Findings">
        <div className="text-sm text-muted-foreground">
          {findings.filter((x) => x.state === "open").length} open across {new Set(findings.map((x) => x.test)).size} tests
        </div>
        <Button variant="outline" className="ml-auto">Export to report</Button>
      </AppHeader>

      <div className="flex-1 overflow-hidden grid grid-cols-[minmax(0,1fr)_420px] gap-6 p-6">
        {/* Board */}
        <div className="overflow-hidden flex flex-col">
          <div className="grid grid-cols-4 gap-3 min-w-0 flex-1">
            {cols.map((c) => (
              <div key={c} className="flex flex-col gap-3 min-w-0">
                <div>
                  <h3 className={`font-semibold text-sm ${
                    c === "open" ? "text-verdict-app-fail" :
                    c === "by-design" ? "text-foreground" :
                    c === "withdrawn" ? "text-verdict-harness" :
                    "text-verdict-pass"
                  }`}>{stateLabel[c]}</h3>
                  <p className="text-xs text-muted-foreground">{findings.filter((x) => x.state === c).length}</p>
                  <p className="text-xs text-muted-foreground mt-2">{stateHelp[c]}</p>
                </div>
                <div className="space-y-3 flex-1 overflow-y-auto min-w-0">
                  {findings.filter((x) => x.state === c).map((x) => (
                    <FindingCard key={x.id} f={x} picked={x.id === picked} onPick={() => setPicked(x.id)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Detail Panel */}
        <div className="border-l border-border pl-6 overflow-y-auto space-y-4">
          <div className="sticky top-0 bg-background pb-4 space-y-4">
            <div>
              <Badge variant="outline" className={cn("border-transparent", severityClasses[f.severity].badge)}>
                {f.severity}
              </Badge>
            </div>
            <div>
              <h2 className="text-lg font-semibold">{f.what}</h2>
              <div className="font-mono text-xs text-muted-foreground mt-2">
                {f.id} · {f.test} step {f.step} · {f.source === "ui-review" ? "visual review" : "pilot"}
              </div>
            </div>
          </div>

          {f.frame && (
            <div className="my-4">
              <FrameImg src={f.frame} crop={crop} alt="Frame where the finding was recorded" style={{ borderRadius: 8 }} />
            </div>
          )}

          {(f.expected || f.actual) && (
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="font-semibold text-muted-foreground">Expected</dt>
                <dd className="text-foreground">{f.expected ?? "—"}</dd>
              </div>
              <div>
                <dt className="font-semibold text-muted-foreground">Actual</dt>
                <dd className="text-foreground">{f.actual ?? "—"}</dd>
              </div>
            </dl>
          )}

          {f.note && <p className="text-sm text-muted-foreground">{f.note}</p>}

          <div className="space-y-3">
            <span className="text-xs text-muted-foreground">Mark as</span>
            <div className="flex flex-wrap gap-2">
              {cols.map((c) => (
                <Button
                  key={c}
                  variant={c === f.state ? "default" : "outline"}
                  size="sm"
                >
                  {stateLabel[c]}
                </Button>
              ))}
            </div>
          </div>

          <p className="text-xs text-muted-foreground border-t border-border pt-4 mt-4">
            Changing the state updates the step verdict: a withdrawn or by-design finding no longer blocks a pass.
          </p>
        </div>
      </div>
    </div>
  );
}
