import { useState } from "react";
import { AppHeader, VerdictDot, VerdictPill, verdictLabel, verdictBg, verdictText } from "../components/kit";
import { matrix } from "../data/sample";
import type { Verdict } from "../data/types";
import { Card, CardContent } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { cn } from "../lib/utils";

const filters: { key: string; label: string; match: (v: Verdict) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  { key: "attention", label: "Needs attention", match: (v) => ["app-fail", "blocked", "waiting"].includes(v) },
  { key: "app-fail", label: "App findings", match: (v) => v === "app-fail" },
  { key: "live", label: "Live", match: (v) => v === "running" || v === "waiting" },
];

export function SuiteMatrix() {
  const [f, setF] = useState("all");
  const filter = filters.find((x) => x.key === f)!;
  const rows = matrix.filter((r) => filter.match(r.runs[0].verdict));
  const latest = matrix.map((r) => r.runs[0].verdict);
  const n = (v: Verdict) => latest.filter((x) => x === v).length;
  const apps = [...new Set(rows.map((r) => r.app))];

  return (
    <div className="flex flex-col h-screen bg-background">
      <AppHeader sub="Suite">
        <h1 className="text-xl font-semibold">FieldOps suite</h1>
        <div className="flex-1" />
        <Button variant="outline">Run all failed</Button>
        <Button>Run suite</Button>
      </AppHeader>

      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* KPI Row */}
        <div className="grid grid-cols-7 gap-4">
          {(["pass", "app-fail", "harness", "blocked", "not-run", "running", "waiting"] as Verdict[]).map((v) => (
            <Card key={v} className="bg-card">
              <CardContent className="pt-6 text-center">
                <div className={cn("text-3xl font-semibold tabular-nums", verdictText[v])}>{n(v)}</div>
                <div className="flex items-center justify-center gap-2 mt-2 text-xs text-muted-foreground">
                  <VerdictDot v={v} /> {verdictLabel[v]}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Segmented Bar */}
        <div className="w-full bg-muted rounded-lg h-2 overflow-hidden flex gap-px" aria-hidden>
          {latest.map((v, i) => (
            <div key={i} className={cn("flex-1", verdictBg[v])} />
          ))}
        </div>

        {/* Filter Buttons */}
        <div className="flex gap-2 flex-wrap">
          {filters.map((x) => (
            <Button
              key={x.key}
              variant={f === x.key ? "default" : "outline"}
              onClick={() => setF(x.key)}
              size="sm"
              className="rounded-full text-xs"
            >
              {x.label} ({matrix.filter((r) => x.match(r.runs[0].verdict)).length})
            </Button>
          ))}
        </div>

        {/* Matrix Table */}
        <div className="border border-border rounded-lg overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted">
                <TableHead>Test</TableHead>
                <TableHead>Latest</TableHead>
                <TableHead>History (newest first)</TableHead>
                <TableHead>Why</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {apps.map((app) => (
                <TooltipProvider key={app}>
                  <>
                    <TableRow className="bg-muted/40">
                      <TableCell colSpan={5} className="text-xs font-semibold text-primary uppercase tracking-wider" style={{ fontVariant: "small-caps" }}>
                        {app}
                      </TableCell>
                    </TableRow>
                    {rows.filter((r) => r.app === app).map((r) => (
                      <TableRow key={r.id} className="group hover:bg-muted/30">
                        <TableCell>
                          <div className="flex items-center gap-2 whitespace-nowrap">
                            <Badge variant="outline" className="font-mono text-xs w-fit">{r.id}</Badge>
                            <div className="text-sm">{r.title}</div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <VerdictPill v={r.runs[0].verdict} />
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            {r.runs.map((run, i) => (
                              <Tooltip key={i}>
                                <TooltipTrigger asChild>
                                  <div className={cn("w-6 h-6 rounded", verdictBg[run.verdict], i === 0 ? "ring-2 ring-offset-1 ring-offset-background ring-border" : "")} />
                                </TooltipTrigger>
                                <TooltipContent>
                                  {run.when}: {verdictLabel[run.verdict]}
                                  {run.note && ` (${run.note})`}
                                </TooltipContent>
                              </Tooltip>
                            ))}
                            {Array.from({ length: Math.max(0, 5 - r.runs.length) }).map((_, i) => (
                              <div key={`e${i}`} className="w-6 h-6 rounded border border-border bg-muted" />
                            ))}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground max-w-xs">
                          {r.runs[0].note ?? (r.runs[0].verdict === "pass" ? "" : "—")}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right opacity-50 transition-opacity group-hover:opacity-100">
                          <Button size="sm" variant="ghost">Open</Button>
                          <Button size="sm" variant="ghost">Rerun</Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </>
                </TooltipProvider>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
