// Sample run history for "FieldOps", a field-service demo app: work orders, a dispatch board, the technician job
// flow, customer sign-off, and invoicing. The shapes mirror `.reverie/runs/<session>-<stamp>/` (run.json for the
// history list, trail.jsonl for steps, notes, and actions). Thumbnails reuse the DEMO-01 frames in public/frames.
import { crop, frames } from "./sample";
import type { Action, Actor, Finding, Frame, Note, Run, RunSummary, Step, Verdict } from "./types";

export const project = { name: "fieldops", dir: "~/work/fieldops/.reverie/runs" };

export interface Spec {
  id: string;
  title: string;
  steps: string[];
}

export const specs: Record<string, Spec> = {
  "FS-01": {
    id: "FS-01",
    title: "Create and dispatch a work order",
    steps: [
      "Sign in as the dispatcher and open Work orders.",
      "Create a work order for Harbor Dental: HVAC not cooling, priority High.",
      "Check that the new order shows as Unassigned with the correct customer and site.",
      "Assign the order to technician Maya Chen for tomorrow at 09:00.",
      "Check that the dispatch board shows the job in Maya's lane and the order status is Dispatched.",
    ],
  },
  "FS-02": {
    id: "FS-02",
    title: "Technician completes a job with parts and sign-off",
    steps: [
      "Sign in as technician Maya Chen and open today's jobs.",
      "Start job WO-1042 and check in on site.",
      "Add the parts used: 2 capacitors 45/5 uF, 1 contactor 30 A, 3 m of copper line.",
      "Record the labor time and the resolution note.",
      "Capture the customer signature and the sign-off name.",
      "Complete the job. Check that the status is Completed and the parts total is $186.40.",
    ],
  },
  "FS-03": {
    id: "FS-03",
    title: "Reschedule from the dispatch board",
    steps: [
      "Open the dispatch board for Tuesday.",
      "Drag WO-1038 from Jon Park at 10:00 to Maya Chen at 14:00.",
      "Check that the confirmation shows the new technician and time.",
      "Open WO-1038 and check that the schedule history records the move.",
    ],
  },
  "FS-04": {
    id: "FS-04",
    title: "Invoice a completed job and mark it paid",
    steps: [
      "Open the completed job WO-1042 as the billing clerk.",
      "Create an invoice from the job. Check that the line items match the labor and parts.",
      "Send the invoice to the customer's email address.",
      "Record a full card payment of $412.90. Check that the invoice status changes to Paid.",
      "Check that the invoice list shows Paid and the balance is $0.00.",
    ],
  },
  "FS-05": {
    id: "FS-05",
    title: "Validation errors on the work order form",
    steps: [
      "Open New work order and save with every field empty.",
      "Check that each required field shows its error: customer, site, problem, and priority.",
      "Enter a due date in the past. Check that the date field shows an error.",
      "Correct the fields and save. Check that no errors remain.",
    ],
  },
};

// The run history, newest first. The live run is pinned at the top of the rail.
export const history: RunSummary[] = [
  { id: "tech-maya-20260928-101204", spec: "FS-02", title: specs["FS-02"].title, session: "tech-maya", day: "Today", started: "10:12", duration: "6m 12s",
    verdict: "running", steps: ["pass", "pass", "running", "pending", "pending", "pending"], live: true },
  { id: "billing-20260928-093015", spec: "FS-04", title: specs["FS-04"].title, session: "billing", day: "Today", started: "09:30", duration: "4m 51s",
    verdict: "app-fail", steps: ["pass", "pass", "pass", "app-fail", "pass"] },
  { id: "dispatch-20260928-090207", spec: "FS-01", title: specs["FS-01"].title, session: "dispatch", day: "Today", started: "09:02", duration: "3m 40s",
    verdict: "pass", steps: ["pass", "pass", "pass", "pass", "pass"] },
  { id: "dispatch-20260928-084122", spec: "FS-05", title: specs["FS-05"].title, session: "dispatch", day: "Today", started: "08:41", duration: "2m 05s",
    verdict: "pass", steps: ["pass", "pass", "pass", "pass"] },
  { id: "dispatch-20260927-162010", spec: "FS-03", title: specs["FS-03"].title, session: "dispatch", day: "Yesterday", started: "16:20", duration: "2m 58s",
    verdict: "pass", steps: ["pass", "pass", "pass", "pass"] },
  { id: "dispatch-20260927-150233", spec: "FS-05", title: specs["FS-05"].title, session: "dispatch", day: "Yesterday", started: "15:02", duration: "1m 47s",
    verdict: "harness", steps: ["pass", "harness", "not-run", "not-run"] },
  { id: "tech-maya-20260927-141002", spec: "FS-02", title: specs["FS-02"].title, session: "tech-maya", day: "Yesterday", started: "14:10", duration: "1m 12s",
    verdict: "blocked", steps: ["pass", "blocked", "not-run", "not-run", "not-run", "not-run"] },
  { id: "dispatch-20260927-113041", spec: "FS-01", title: specs["FS-01"].title, session: "dispatch", day: "Yesterday", started: "11:30", duration: "3m 55s",
    verdict: "pass", steps: ["pass", "pass", "pass", "pass", "pass"] },
  { id: "dispatch-20260926-171500", spec: "FS-03", title: specs["FS-03"].title, session: "dispatch", day: "Sep 26", started: "17:15", duration: "3m 02s",
    verdict: "pass", steps: ["pass", "pass", "pass", "pass"] },
  { id: "billing-20260926-165512", spec: "FS-04", title: specs["FS-04"].title, session: "billing", day: "Sep 26", started: "16:55", duration: "0m 08s",
    verdict: "not-run", steps: ["not-run", "not-run", "not-run", "not-run", "not-run"] },
];

export const liveRunId = history[0].id;
export const pastRunId = history[1].id;

// ---------------------------------------------------------------------------------------------------------------
// Step details: notes (narration), actions, findings, and the visual review.

const pairs: Frame[] = [
  { before: frames.home, after: frames.dropdown, crop },
  { before: frames.dropdownTarget, after: frames.dropdownDone, crop },
  { before: frames.checkboxesTarget, after: frames.checkboxesDone, crop },
  { before: frames.loadingTarget, after: frames.loading, crop },
  { after: frames.hello, crop },
  { after: frames.loadingStart, crop },
  { after: frames.checkboxes, crop },
];

function clock(start: string, plus: number) {
  const [h, m, s] = start.split(":").map(Number);
  const t = h * 3600 + m * 60 + (s ?? 0) + plus;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(t / 3600) % 24)}:${pad(Math.floor(t / 60) % 60)}:${pad(t % 60)}`;
}

type Tpl = [Action["kind"], string, string?];

// Targets the agent works through, per spec. The generator cycles them to make realistic volume.
const targets: Record<string, Tpl[]> = {
  "FS-01": [["goto", "/work-orders"], ["click", "New work order"], ["type", "Customer", "Harbor Dental"], ["select", "Site", "Main St clinic"],
    ["type", "Problem", "HVAC not cooling"], ["select", "Priority", "High"], ["click", "Save"], ["check", "text contains 'Unassigned'"],
    ["click", "Assign"], ["select", "Technician", "Maya Chen"], ["type", "Start", "09:00"], ["click", "Confirm assignment"]],
  "FS-02": [["goto", "/jobs/today"], ["click", "WO-1042"], ["click", "Start job"], ["click", "Check in"], ["click", "Add part"],
    ["type", "Part search", "capacitor 45/5"], ["click", "Capacitor 45/5 uF"], ["type", "Quantity", "2"], ["click", "Add part"],
    ["type", "Part search", "contactor 30"], ["click", "Contactor 30 A"], ["type", "Quantity", "1"], ["click", "Add part"],
    ["type", "Part search", "copper line"], ["click", "Copper line 3/8 in"], ["type", "Quantity", "3"], ["check", "parts list has 3 rows"],
    ["wait", "Wait for the parts total"], ["check", "text contains '$186.40'"]],
  "FS-03": [["goto", "/dispatch?day=tue"], ["click", "WO-1038 card"], ["click", "Maya Chen 14:00 slot"], ["click", "Move job"],
    ["check", "text contains 'Moved to Maya Chen'"], ["goto", "/work-orders/1038"], ["click", "Schedule history"]],
  "FS-04": [["goto", "/jobs/WO-1042"], ["click", "Create invoice"], ["check", "row 'Labor 1.5 h'"], ["check", "row 'Capacitor 45/5 uF x2'"],
    ["click", "Edit line"], ["type", "Description", "Labor, HVAC repair"], ["click", "Save line"], ["click", "Send"],
    ["type", "To", "billing@harbordental.example"], ["click", "Send invoice"], ["click", "Record payment"], ["select", "Method", "Card"],
    ["type", "Amount", "412.90"], ["click", "Save payment"], ["wait", "Wait for the invoice to update"], ["check", "status is 'Paid'"]],
  "FS-05": [["goto", "/work-orders/new"], ["click", "Save"], ["check", "error under Customer"], ["check", "error under Site"],
    ["type", "Due date", "2026-09-01"], ["click", "Save"], ["check", "error under Due date"], ["type", "Customer", "Harbor Dental"]],
};

function secs(t: string) {
  const [h, m, x] = t.split(":").map(Number);
  return h * 3600 + m * 60 + (x ?? 0);
}

function makeActions(spec: string, start: string, count: number, offset: number, failAt?: number, gap = 3): Action[] {
  const list = targets[spec];
  return Array.from({ length: count }, (_, i) => {
    const [kind, label, text] = list[(i + offset) % list.length];
    const actor: Actor = kind === "click" || kind === "type" || kind === "select" || kind === "wait" ? "laya" : "pilot";
    const frame = kind === "check" ? undefined : pairs[(i + offset) % pairs.length];
    return { t: clock(start, 3 + Math.floor(i * gap)), actor, kind, label, text, ok: kind === "check" ? i !== failAt : undefined, frame };
  });
}

const note = (t: string, text: string, actor: Actor = "pilot"): Note => ({ t, actor, text });

// Written notes for the two featured runs. Other runs get short generic notes.
const writtenNotes: Record<string, Record<number, Note[]>> = {
  [liveRunId]: {
    1: [note("10:12:09", "Signed in as Maya Chen. Today's jobs list shows three jobs; WO-1042 is first."),
      note("10:12:40", "Step 1 passes. The job list matches the fixture.")],
    2: [note("10:13:02", "Opened WO-1042 for Harbor Dental. Status is Scheduled."),
      note("10:13:31", "Started the job and checked in. The status changed to On site and the check-in time is 10:13."),
      note("10:13:44", "Step 2 passes.")],
    3: [note("10:14:05", "Adding parts. The part search needs at least three characters, so I type the part name first."),
      note("10:15:20", "Two capacitors and one contactor are on the job. The running total is $148.90."),
      note("10:17:48", "Adding 3 m of copper line now. Then I check the total against $186.40.")],
  },
  [pastRunId]: {
    1: [note("09:30:21", "Signed in as the billing clerk. WO-1042 shows Completed with a signature on file."),
      note("09:30:49", "Step 1 passes.")],
    2: [note("09:31:10", "Created the invoice. It has four lines: labor 1.5 h and three parts."),
      note("09:32:02", "The labor line text was generic, so I edited it to 'Labor, HVAC repair'. The totals did not change."),
      note("09:32:40", "Line items match the job. Subtotal $381.20, tax $31.70, total $412.90. Step 2 passes.")],
    3: [note("09:33:05", "Sent the invoice to billing@harbordental.example. The status changed to Sent."),
      note("09:33:18", "Step 3 passes.")],
    4: [note("09:33:40", "Recorded a card payment of $412.90. The payment row shows and the balance is $0.00."),
      note("09:33:55", "The status badge still shows Sent. I waited 10 seconds and it did not change."),
      note("09:34:20", "After a page reload the status shows Paid. The badge does not update after a payment. I recorded this as an app finding.")],
    5: [note("09:34:48", "The invoice list shows WO-1042 as Paid with a balance of $0.00. Step 5 passes."),
      note("09:35:06", "Run complete: four steps pass and one app finding is open.")],
  },
};

const pastFinding: Finding = {
  id: "F-21", severity: "medium", state: "open", source: "pilot", test: "FS-04", step: 4,
  what: "Invoice status stays Sent after a full payment until the page reloads",
  expected: "Status changes to Paid when the payment saves", actual: "Status shows Sent; Paid appears only after a reload",
  frame: frames.checkboxesDone,
};

// Action counts per step. The high-volume steps show why actions live in a scrollable drawer.
const actionCount = (spec: string, n: number) => {
  if (spec === "FS-02" && n === 3) return 64;
  if (spec === "FS-04" && n === 2) return 62;
  if (spec === "FS-04" && n === 4) return 24;
  return 8 + ((n * 7) % 11);
};

const genericNote: Partial<Record<Verdict, string>> = {
  pass: "Step passes. The screen matches what the spec expects.",
  "app-fail": "The app did not do what the step expects. I recorded a finding.",
  harness: "My check used the wrong field label, so the result proves nothing. The app may be fine.",
  blocked: "The parts catalog fixture is empty, so the step cannot run.",
  "not-run": "Not run: the billing credential is not set in .env.",
};

/** Build the full run for a history entry: steps with notes, actions, findings, and the visual review. */
export function runFor(summary: RunSummary): Run {
  const spec = specs[summary.spec];
  let at = `${summary.started}:04`;
  const steps: Step[] = spec.steps.map((title, i) => {
    const n = i + 1;
    const verdict = summary.steps[i];
    const done = verdict !== "pending" && verdict !== "not-run";
    const count = done ? actionCount(summary.spec, n) : 0;
    const written = writtenNotes[summary.id]?.[n];
    // With written notes, the step spans its notes; otherwise it spans three seconds per action.
    const started = written ? clock(written[0].t, -8) : at;
    const span = written ? secs(written[written.length - 1].t) - secs(started) + 6 : 12 + count * 3;
    const seconds = done ? span : undefined;
    const isFinding = summary.id === pastRunId && n === 4;
    const notes = written ?? (genericNote[verdict] ? [note(clock(started, 20), genericNote[verdict]!)] : []);
    const gap = count ? Math.max(1, (span - 6) / count) : 3;
    const actions = done ? makeActions(summary.spec, started, count, written ? (summary.spec === "FS-02" ? 4 : 0) : n * 3, isFinding ? count - 1 : undefined, gap) : [];
    if (seconds) at = clock(started, seconds + 6);
    return {
      n, title, verdict, started: done ? started : undefined, seconds: verdict === "running" ? undefined : seconds, notes, actions,
      findings: isFinding ? [pastFinding] : [],
      uiReview: verdict === "pass" || verdict === "app-fail"
        ? isFinding
          ? { ok: false, summary: "The status badge reads Sent while the balance reads $0.00." }
          : { ok: true, summary: "Layout and text render cleanly. No overlap or clipped labels." }
        : undefined,
    };
  });
  return { id: summary.id, test: summary.spec, title: summary.title, session: summary.session, started: summary.started,
    duration: summary.duration, verdict: summary.verdict, steps };
}
