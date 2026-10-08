import { ago, AppHeader, FrameImg, Kbd, VerdictPill, VerdictStrip } from "../components/kit";
import { checkpoints, crop, sessions } from "../data/sample";
import type { Session } from "../data/types";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Alert } from "../components/ui/alert";
import { checkpointIcon } from "../components/icons";
import { LuInbox, LuPlus } from "react-icons/lu";

const stateLabel: Record<Session["state"], string> = {
  acting: "Acting", thinking: "Thinking", waiting: "Needs you", idle: "Idle",
};

/**
 * SessionCard displays the live view and status of a single session.
 */
function SessionCard({ s }: { s: Session }) {
  const cp = checkpoints.find((c) => c.session === s.name);
  const done = s.verdicts.filter((v) => !["pending", "running", "waiting"].includes(v)).length;
  const isWaiting = s.state === "waiting";

  return (
    <Card className={`flex flex-col overflow-hidden transition-all ${isWaiting ? "border-verdict-waiting/40 shadow-lg shadow-verdict-waiting/20" : ""}`}>
      <div className="relative bg-white">
        <FrameImg src={s.frame} crop={crop} alt={`Live view of ${s.name}`} />
        <span className="absolute bottom-2 left-2 rounded-full bg-black/50 px-2 py-1 text-xs font-semibold backdrop-blur text-foreground">
          {stateLabel[s.state]}
        </span>
        {s.state !== "idle" && (
          <span className="absolute bottom-2 right-2 rounded-full bg-black/50 px-2 py-1 text-xs text-foreground backdrop-blur">
            {ago(s.idleSeconds)} since last action
          </span>
        )}
      </div>

      <CardContent className="flex flex-col gap-3 pt-4">
        <div className="space-y-1">
          <div className="font-semibold font-mono text-base">{s.name}</div>
          <div className="text-xs text-muted-foreground">{s.role} · {s.host}</div>
        </div>

        {s.test && (
          <div className="text-sm">
            <b>{s.test}</b> <span className="text-muted-foreground">step {s.step} of {s.steps}</span>
          </div>
        )}

        <div className="text-base text-foreground">{s.stepTitle}</div>
        <VerdictStrip verdicts={s.verdicts} />

        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{done}/{s.verdicts.length} steps judged</span>
          <span>last: {s.lastAction}</span>
        </div>

        {s.said && <p className="text-sm text-muted-foreground italic border-l-2 border-border pl-3">"{s.said}"</p>}

        {cp && (
          <Alert className="mt-2 border-verdict-waiting/30 bg-verdict-waiting/10">
            <div className="flex items-center gap-2">
              <Badge className="gap-1 border-transparent text-xs uppercase font-semibold bg-verdict-waiting text-background hover:bg-verdict-waiting">
                {(() => { const I = checkpointIcon[cp.kind]; return <I size={12} aria-hidden />; })()}{cp.kind}
              </Badge>
              <div className="flex-1" />
              <Button size="sm">Handle</Button>
            </div>
            <p className="mt-2 text-sm text-foreground">{cp.title}</p>
          </Alert>
        )}

      </CardContent>
    </Card>
  );
}

/**
 * MissionControl displays the dashboard of active sessions and checkpoints.
 */
export function MissionControl() {
  const waiting = sessions.filter((s) => s.state === "waiting").length;

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader sub="Mission control">
        <div className="flex gap-6 text-sm text-muted-foreground">
          <div>
            <b className="text-foreground">{sessions.length}</b> sessions
          </div>
          <div>
            <b className="text-verdict-running">{sessions.filter((s) => s.state === "acting").length}</b> acting
          </div>
          <div>
            <b className="text-verdict-waiting">{checkpoints.length}</b> need you
          </div>
          <div>
            <b className="text-verdict-running">{sessions.filter((s) => s.state === "thinking").length}</b> thinking
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="outline"><LuPlus size={16} aria-hidden /> Start a spec</Button>
        <Button><LuInbox size={16} aria-hidden /> Inbox · {checkpoints.length}</Button>
      </AppHeader>

      {waiting > 0 && (
        <Alert className="mx-6 mt-4 w-auto border-verdict-waiting/30 bg-verdict-waiting-muted">
          <div className="flex items-center gap-3">
            <span className="inline-block w-2 h-2 rounded-full bg-verdict-waiting motion-safe:animate-pulse" />
            <b>{checkpoints.length} checkpoints are waiting.</b>
            <span className="text-muted-foreground">The oldest has waited {ago(Math.max(...checkpoints.map((c) => c.waitingSeconds)))}.</span>
            <div className="flex-1" />
            <span className="text-xs text-muted-foreground">
              Press <Kbd>G</Kbd> <Kbd>I</Kbd> for the inbox
            </span>
          </div>
        </Alert>
      )}

      <main className="flex-1 grid grid-cols-[repeat(auto-fill,minmax(330px,1fr))] gap-6 p-6">
        {sessions.map((s) => (
          <SessionCard key={s.name} s={s} />
        ))}
      </main>

      <footer className="flex gap-2 items-center flex-wrap px-6 py-5 text-xs text-muted-foreground">
        <span>Legend</span>
        {(["pass", "app-fail", "harness", "blocked", "not-run", "running", "waiting"] as const).map((v) => (
          <VerdictPill key={v} v={v} />
        ))}
      </footer>
    </div>
  );
}
