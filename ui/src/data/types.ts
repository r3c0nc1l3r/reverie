// Shapes that mirror what the reverie daemon already records in trail.jsonl.

export type Verdict = "pass" | "app-fail" | "harness" | "blocked" | "not-run" | "running" | "waiting" | "pending";
export type Actor = "laya" | "pilot" | "orchestrator" | "person";
export type Severity = "high" | "medium" | "low";
export type FindingState = "open" | "by-design" | "withdrawn" | "fixed";

export interface Frame {
  before?: string; // frame with the target ring
  after: string;
  crop?: { x: number; y: number; w: number; h: number }; // percentages of the 1920x1080 frame
}

export interface Action {
  t: string;
  actor: Actor;
  kind: "click" | "type" | "select" | "goto" | "wait" | "check" | "say";
  label: string;
  text?: string;
  ok?: boolean;
  frame?: Frame;
}

export interface Finding {
  id: string;
  severity: Severity;
  state: FindingState;
  what: string;
  expected?: string;
  actual?: string;
  source: "pilot" | "ui-review";
  test: string;
  step: number;
  frame?: string;
  note?: string;
}

/** One line the agent said while it worked on a step (its narration). */
export interface Note {
  t: string;
  actor: Actor;
  text: string;
}

export interface Step {
  n: number;
  title: string;
  verdict: Verdict;
  admin?: boolean;
  note?: string;
  started?: string;
  seconds?: number;
  actions: Action[];
  findings: Finding[];
  uiReview?: { ok: boolean; summary: string };
  notes?: Note[];
}

export interface Checkpoint {
  id: string;
  session: string;
  test: string;
  step: number;
  kind: "sign-in" | "database" | "mail" | "question";
  title: string;
  asked: string; // time
  waitingSeconds: number;
  context: string;
  command?: string;
  frame?: string;
  suggestions?: string[];
}

export interface Session {
  name: string;
  role: string;
  host: string;
  state: "acting" | "thinking" | "waiting" | "idle";
  test?: string;
  step?: number;
  steps?: number;
  stepTitle?: string;
  lastAction?: string;
  idleSeconds: number;
  frame: string;
  verdicts: Verdict[];
  said?: string;
}

export interface Run {
  id: string;
  test: string;
  title: string;
  session: string;
  started: string;
  duration: string;
  verdict: Verdict;
  steps: Step[];
}

export interface MatrixRow {
  id: string;
  title: string;
  app: string;
  runs: { verdict: Verdict; when: string; note?: string }[];
}

/** A run as the history lists it: the short summary in `.reverie/runs/<session>-<stamp>/run.json`. */
export interface RunSummary {
  id: string; // folder name under .reverie/runs/
  spec: string;
  title: string;
  session: string;
  day: string;
  started: string;
  duration: string;
  verdict: Verdict;
  steps: Verdict[];
  live?: boolean;
}
