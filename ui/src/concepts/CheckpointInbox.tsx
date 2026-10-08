import { useState } from "react";
import { ago, AppHeader, FrameImg, Kbd, VerdictStrip } from "../components/kit";
import { checkpoints, crop, sessions } from "../data/sample";
import type { Checkpoint } from "../data/types";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Textarea } from "../components/ui/textarea";
import { Checkbox } from "../components/ui/checkbox";
import { Label } from "../components/ui/label";
import { Card, CardContent } from "../components/ui/card";
import { ScrollArea } from "../components/ui/scroll-area";
import { checkpointIcon } from "../components/icons";
import { LuCheck, LuCommand, LuCopy, LuCornerDownLeft, LuSkipForward, LuTerminal, LuX } from "react-icons/lu";

const kindHelp: Record<Checkpoint["kind"], string> = {
  "sign-in": "Sign the named session in. Secrets never reach the pilot.",
  database: "Run a read-only query and report the facts the step expects.",
  mail: "Find the message in the app's Mailpit and report subject, recipient, and time.",
  question: "The pilot needs a decision.",
};

export function CheckpointInbox({ initial = 0 }: { initial?: number }) {
  const [sel, setSel] = useState(initial);
  const [note, setNote] = useState("");
  const [resume, setResume] = useState(true);
  const cp = checkpoints[sel];
  const s = sessions.find((x) => x.name === cp.session)!;

  return (
    <div className="flex flex-col h-screen bg-background">
      <AppHeader sub="Checkpoint inbox">
        <span className="text-sm text-muted-foreground">{checkpoints.length} waiting · oldest {ago(Math.max(...checkpoints.map((c) => c.waitingSeconds)))}</span>
        <div className="flex-1" />
        <span className="flex items-center gap-1 text-sm text-muted-foreground whitespace-nowrap">
          <Kbd>J</Kbd>/<Kbd>K</Kbd> move · <Kbd><LuCommand size={12} aria-label="Command" /></Kbd><Kbd><LuCornerDownLeft size={12} aria-label="Enter" /></Kbd> done · <Kbd>F</Kbd> failed · <Kbd>S</Kbd> skip
        </span>
      </AppHeader>

      <div className="flex flex-1 gap-6 px-6 py-6 overflow-hidden">
        {/* Left pane: list */}
        <ScrollArea className="w-64 border border-border rounded-lg">
          <nav className="flex flex-col" aria-label="Waiting checkpoints">
            {checkpoints.map((c, i) => (
              <button
                key={c.id}
                onClick={() => { setSel(i); setNote(""); }}
                className={`text-left px-4 py-3 border-b border-border hover:bg-muted transition-colors relative ${
                  i === sel ? "bg-muted" : ""
                }`}
              >
                {i === sel && <div className="absolute inset-y-0 left-0 w-1 bg-verdict-waiting" />}
                <div className="flex items-start gap-3">
                  {(() => { const I = checkpointIcon[c.kind]; return <I size={16} aria-hidden className="mt-0.5 flex-none text-verdict-waiting" />; })()}
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{c.title}</div>
                    <div className="text-xs text-muted-foreground truncate">{c.session} · {c.test} step {c.step}</div>
                  </div>
                  <div className={`text-xs font-mono flex-none ${c.waitingSeconds > 60 ? "text-verdict-waiting" : "text-muted-foreground"}`}>
                    {ago(c.waitingSeconds)}
                  </div>
                </div>
              </button>
            ))}
            <div className="px-4 py-3 text-xs text-muted-foreground border-t border-border">
              Resolved checkpoints move to the run's timeline.
            </div>
          </nav>
        </ScrollArea>

        {/* Right pane: detail */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-auto space-y-6">
            {/* Breadcrumbs and title */}
            <div>
              <div className="text-sm font-mono text-muted-foreground mb-2">
                {cp.session} › {cp.test} › step {cp.step} · asked {cp.asked}
              </div>
              <div className="flex items-center gap-3 mb-2">
                <Badge variant="outline" className="gap-1 uppercase text-xs">{(() => { const I = checkpointIcon[cp.kind]; return <I size={12} aria-hidden />; })()}{cp.kind}</Badge>
                <h1 className="text-2xl font-bold">{cp.title}</h1>
              </div>
              <p className="text-sm text-muted-foreground">{kindHelp[cp.kind]}</p>
            </div>

            {/* Two-column content */}
            <div className="grid grid-cols-[1fr_minmax(320px,1fr)] gap-6">
              {/* Left column: context */}
              <div className="space-y-4">
                <div>
                  <h4 className="font-semibold text-sm mb-2">What the pilot knows</h4>
                  <p className="text-sm text-foreground mb-3">{cp.context}</p>
                  <VerdictStrip verdicts={s.verdicts} height={5} />
                  {s.said && <p className="text-sm text-muted-foreground italic mt-3">"{s.said}"</p>}
                </div>

                {cp.command && (
                  <div>
                    <h4 className="font-semibold text-sm mb-2">Suggested command</h4>
                    <Card className="bg-muted">
                      <CardContent className="p-3">
                        <div className="font-mono text-xs text-foreground whitespace-pre-wrap break-words mb-2">
                          $ {cp.command}
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" variant="outline"><LuCopy size={14} aria-hidden /> Copy</Button>
                          <Button size="sm"><LuTerminal size={14} aria-hidden /> Run here</Button>
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                )}
              </div>

              {/* Right column: frame */}
              {cp.frame && (
                <figure className="flex flex-col gap-2">
                  <Card className="overflow-hidden">
                    <CardContent className="p-0">
                      <FrameImg src={cp.frame} crop={crop} alt="Last frame before the checkpoint" />
                    </CardContent>
                  </Card>
                  <figcaption className="text-xs text-muted-foreground text-center">Last frame before the checkpoint</figcaption>
                </figure>
              )}
            </div>

            {/* Resolve section */}
            <Card>
              <CardContent className="p-4 space-y-3">
                <h4 className="font-semibold text-sm">Resolve with facts</h4>

                {cp.suggestions && cp.suggestions.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {cp.suggestions.map((t) => (
                      <Button
                        key={t}
                        variant="outline"
                        size="sm"
                        className="rounded-full"
                        onClick={() => setNote(t)}
                      >
                        {t}
                      </Button>
                    ))}
                  </div>
                )}

                <Textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="IDs, status values, timestamps, message subjects. No secrets or tokens."
                  className="text-sm resize-none"
                  rows={4}
                />

                <div className="text-xs">
                  {/token=|password|\b\d{6}\b/i.test(note) ? (
                    <span className="text-destructive">
                      This note may contain a secret or a one-time code. Remove it before sending.
                    </span>
                  ) : (
                    <span className="text-muted-foreground">The note goes to the pilot and the trail as written.</span>
                  )}
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <Button size="sm" className="bg-verdict-pass text-background hover:bg-verdict-pass/85"><LuCheck size={14} aria-hidden /> Done</Button>
                  <Button size="sm" variant="destructive"><LuX size={14} aria-hidden /> Failed</Button>
                  <Button size="sm" variant="outline"><LuSkipForward size={14} aria-hidden /> Skip</Button>
                  <div className="flex-1" />
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="resume"
                      checked={resume}
                      onChange={(e) => setResume(e.target.checked)}
                    />
                    <Label htmlFor="resume" className="text-sm cursor-pointer">
                      Resume the pilot after this
                    </Label>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}
