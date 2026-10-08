import type { Checkpoint, Finding, MatrixRow, Run, Session } from "./types";

// Frames from the real DEMO-01 run against the-internet.herokuapp.com (public practice site).
const f = (name: string) => `${import.meta.env.BASE_URL}frames/${name}.jpg`;
export const frames = {
  home: f("step-001-target-0001"),
  dropdown: f("step-001-0002"),
  dropdownTarget: f("step-002-target-0003"),
  dropdownDone: f("step-002-0004"),
  checkboxes: f("nav-0005"),
  checkboxesTarget: f("step-003-target-0006"),
  checkboxesDone: f("step-003-0007"),
  loadingStart: f("nav-0008"),
  loadingTarget: f("step-004-target-0009"),
  loading: f("step-004-0010"),
  hello: f("step-006-0012"),
};
export const crop = { x: 22, y: 0, w: 46, h: 34 };

export const demoRun: Run = {
  id: "demo-20260927-103356",
  test: "DEMO-01",
  title: "Form controls and a loading page",
  session: "demo",
  started: "10:33:58",
  duration: "53 s",
  verdict: "pass",
  steps: [
    {
      n: 1,
      title: "Open /dropdown. Select 'Option 2' and check it is the selected value.",
      verdict: "pass",
      started: "10:33:59",
      seconds: 17,
      note: "Dropdown shows Option 2 selected.",
      uiReview: { ok: true, summary: "Dropdown renders cleanly; Option 2 is visible as the selection." },
      findings: [],
      actions: [
        { t: "10:34:02", actor: "pilot", kind: "goto", label: "the-internet.herokuapp.com/dropdown", frame: { after: frames.dropdown, crop } },
        { t: "10:34:08", actor: "pilot", kind: "select", label: "Dropdown List", text: "Option 2", frame: { before: frames.dropdownTarget, after: frames.dropdownDone, crop } },
        { t: "10:34:12", actor: "pilot", kind: "check", label: "text contains 'Option 2'", ok: true },
      ],
    },
    {
      n: 2,
      title: "Open /checkboxes. Make sure both checkboxes are checked.",
      verdict: "pass",
      started: "10:34:16",
      seconds: 14,
      note: "Checkbox 1 clicked from unchecked to checked; checkbox 2 was already checked.",
      uiReview: { ok: true, summary: "Both checkboxes are checked in the final state." },
      findings: [],
      actions: [
        { t: "10:34:17", actor: "pilot", kind: "goto", label: "the-internet.herokuapp.com/checkboxes", frame: { after: frames.checkboxes, crop } },
        { t: "10:34:22", actor: "laya", kind: "click", label: "checkbox 1", frame: { before: frames.checkboxesTarget, after: frames.checkboxesDone, crop } },
        { t: "10:34:26", actor: "pilot", kind: "check", label: "text contains 'checkbox 1'", ok: true },
      ],
    },
    {
      n: 3,
      title: "Open /dynamic_loading/1. Click Start and check 'Hello World!' appears.",
      verdict: "pass",
      started: "10:34:30",
      seconds: 18,
      note: "Waited for the loading bar; 'Hello World!' is visible.",
      uiReview: { ok: true, summary: "Start click, loading bar, and result all rendered without defects." },
      findings: [],
      actions: [
        { t: "10:34:31", actor: "pilot", kind: "goto", label: "the-internet.herokuapp.com/dynamic_loading/1", frame: { after: frames.loadingStart, crop } },
        { t: "10:34:36", actor: "laya", kind: "click", label: "Start", frame: { before: frames.loadingTarget, after: frames.loading, crop } },
        { t: "10:34:41", actor: "laya", kind: "wait", label: "Wait for the page to update", frame: { after: frames.hello, crop } },
        { t: "10:34:48", actor: "pilot", kind: "check", label: "text contains 'Hello World!'", ok: true },
      ],
    },
  ],
};

// A richer run that shows the verdict split: app finding, harness slip, and a checkpoint.
// The app and its data are the fictional FieldOps demo (examples/fieldops); the frames still come from DEMO-01.
export const mixedRun: Run = {
  id: "manager-20260924-090212",
  test: "FS-06",
  title: "Remove a technician login",
  session: "fieldops-manager",
  started: "09:02:12",
  duration: "7 m 41 s",
  verdict: "app-fail",
  steps: [
    {
      n: 1, title: "As the manager, open TEAM and remove the new technician login.", verdict: "pass", seconds: 64,
      note: "Remove login confirmed; the list shows the technician as Removed.", findings: [],
      uiReview: { ok: true, summary: "List reloads with the Removed state." },
      actions: [
        { t: "09:02:20", actor: "pilot", kind: "goto", label: "SETTINGS › TEAM", frame: { after: frames.checkboxes, crop } },
        { t: "09:02:41", actor: "laya", kind: "click", label: "Remove login", frame: { before: frames.checkboxesTarget, after: frames.checkboxesDone, crop } },
        { t: "09:02:44", actor: "pilot", kind: "check", label: "text contains 'Removed'", ok: true },
      ],
    },
    {
      n: 2, title: "Read the technician row: expect it marked removed; sign-in must fail.", verdict: "pass", admin: true, seconds: 212,
      note: "Orchestrator: active flag cleared; sign-in shows 'Wrong username or password'.", findings: [], actions: [],
    },
    {
      n: 3, title: "Open a removed technician's profile by URL; expect 'Technician not found.'", verdict: "app-fail", seconds: 41,
      note: "Message shows, but Edit profile and Reset password still render below it.",
      uiReview: { ok: false, summary: "Dead controls under the not-found message." },
      findings: [
        { id: "F-12", severity: "medium", state: "open", source: "ui-review", test: "FS-06", step: 3,
          what: "Edit profile and Reset password render under 'Technician not found.'",
          expected: "No actions when no technician record loads", actual: "Two live buttons", frame: frames.dropdownTarget },
      ],
      actions: [
        { t: "09:07:10", actor: "pilot", kind: "goto", label: "/team/16", frame: { after: frames.dropdown, crop } },
        { t: "09:07:14", actor: "pilot", kind: "check", label: "text contains 'Technician not found.'", ok: true },
        { t: "09:07:15", actor: "pilot", kind: "check", label: "text lacks 'Edit profile'", ok: false },
      ],
    },
    {
      n: 4, title: "Sign in as a technician.", verdict: "waiting", admin: true, seconds: 96,
      note: "Waiting for the orchestrator to sign the session in.", findings: [], actions: [],
    },
    { n: 5, title: "As a technician, confirm Remove login appears nowhere.", verdict: "pending", findings: [], actions: [] },
  ],
};

export const sessions: Session[] = [
  { name: "fieldops-manager", role: "manager", host: "localhost:8765", state: "waiting", test: "FS-06", step: 4, steps: 5,
    stepTitle: "Sign in as a technician", lastAction: "Raised checkpoint: sign-in", idleSeconds: 96,
    frame: frames.checkboxesDone, verdicts: ["pass", "pass", "app-fail", "waiting", "pending"],
    said: "Removal works; the not-found page still shows two buttons. I need a technician sign-in next." },
  { name: "fieldops-billing", role: "manager", host: "localhost:8765", state: "waiting", test: "FS-04", step: 4, steps: 6,
    stepTitle: "Read the invoice totals (database proof)", lastAction: "Raised checkpoint: database", idleSeconds: 41,
    frame: frames.dropdownDone, verdicts: ["pass", "pass", "pass", "waiting", "pending", "pending"],
    said: "The invoice was created once and the second click was refused. I need the invoice row to confirm the totals." },
  { name: "fieldops-dispatcher", role: "dispatcher", host: "localhost:8765", state: "acting", test: "FS-07", step: 2, steps: 6,
    stepTitle: "Cancel the work order with a reason", lastAction: "click Cancel work order", idleSeconds: 2,
    frame: frames.loadingTarget, verdicts: ["pass", "running", "pending", "pending", "pending", "pending"],
    said: "The dialog's Back button backed out cleanly. Now cancelling for real with the reason." },
  { name: "fieldops-tech", role: "technician", host: "localhost:8765", state: "thinking", test: "FS-08", step: 3, steps: 4,
    stepTitle: "Compare the menu on the live site", lastAction: "hover MY JOBS", idleSeconds: 9,
    frame: frames.dropdown, verdicts: ["pass", "not-run", "running", "pending"],
    said: "MY JOBS opens a hover menu. I am recording the submenu items next." },
  { name: "demo", role: "anonymous", host: "the-internet", state: "idle", test: "DEMO-01", step: 3, steps: 3,
    stepTitle: "Done", lastAction: "mark pass", idleSeconds: 1420,
    frame: frames.hello, verdicts: ["pass", "pass", "pass"], said: "All three steps pass." },
];

export const checkpoints: Checkpoint[] = [
  { id: "94e01f", session: "fieldops-manager", test: "FS-06", step: 4, kind: "sign-in", title: "Sign the session in as a technician",
    asked: "09:08:51", waitingSeconds: 96, context: "Step 4 of 5. The manager steps passed; the technician check needs a technician session.",
    command: "reverie --session fieldops-manager secret --env FIELDOPS_PASSWORD", frame: frames.checkboxesDone,
    suggestions: ["Signed in as tom.tech at /jobs.", "Sign-in failed: wrong password."] },
  { id: "3fe755", session: "fieldops-billing", test: "FS-04", step: 4, kind: "database", title: "Read the invoice: totals and part lines",
    asked: "09:10:02", waitingSeconds: 41, context: "Expect one invoice for WO-1008 with a parts subtotal of $65.50.",
    command: "./query.sh \"select number, parts_cents, total_cents from invoices order by id desc limit 1\"", frame: frames.dropdownDone,
    suggestions: ["INV-5002 | 4050 | 23050: the parts subtotal is $40.50, not $65.50."] },
  { id: "b71c20", session: "fieldops-tech", test: "FS-08", step: 4, kind: "mail", title: "Find the visit notice for the rescheduled job",
    asked: "09:11:20", waitingSeconds: 12, context: "Step 4 of 4 expects one visit notice to facilities@harborview.example.",
    frame: frames.dropdown, suggestions: ["Subject 'Your visit is scheduled', to facilities@harborview.example, 09:11:02."] },
];

export const findings: Finding[] = [
  { id: "F-12", severity: "medium", state: "open", source: "ui-review", test: "FS-06", step: 3,
    what: "Action buttons render under 'Technician not found.'", expected: "No actions", actual: "Edit profile, Reset password",
    frame: frames.dropdownTarget },
  { id: "F-11", severity: "high", state: "fixed", source: "pilot", test: "FS-07", step: 1,
    what: "Cancel view shows a server error (template error on the work order page)", note: "Fixed and redeployed at 08:52.",
    frame: frames.loadingStart },
  { id: "F-10", severity: "medium", state: "by-design", source: "pilot", test: "FS-03", step: 2,
    what: "A rescheduled job stays in the Unassigned queue until the board reloads", note: "The board refreshes on the next day change.",
    frame: frames.checkboxes },
  { id: "F-09", severity: "high", state: "withdrawn", source: "pilot", test: "FS-05", step: 4,
    what: "Work order list returns no rows", note: "The pilot never pressed Filter. Playbook lesson added.",
    frame: frames.home },
  { id: "F-08", severity: "low", state: "open", source: "pilot", test: "FS-01", step: 3,
    what: "A customer email longer than 50 characters shows a server error", expected: "Field error", actual: "Generic error page",
    frame: frames.dropdown },
  { id: "F-07", severity: "low", state: "open", source: "ui-review", test: "FS-09", step: 2,
    what: "No confirmation after Save; the edit form stays on screen", frame: frames.checkboxesDone },
];

export const matrix: MatrixRow[] = [
  { id: "DEMO-01", title: "Form controls and a loading page", app: "demo", runs: [
    { verdict: "pass", when: "Sep 27 10:33" }, { verdict: "harness", when: "Sep 27 10:29", note: "password field hidden from pilot" } ] },
  { id: "FS-01", title: "Create and dispatch a work order", app: "fieldops", runs: [
    { verdict: "pass", when: "Sep 24 03:02" }, { verdict: "app-fail", when: "Sep 23 16:10" }, { verdict: "app-fail", when: "Sep 23 11:02" } ] },
  { id: "FS-07", title: "Cancel a work order", app: "fieldops", runs: [
    { verdict: "pass", when: "Sep 24 08:59" }, { verdict: "app-fail", when: "Sep 24 08:46", note: "template error" },
    { verdict: "app-fail", when: "Sep 24 03:59" }, { verdict: "harness", when: "Sep 24 03:18", note: "overshoot" } ] },
  { id: "FS-06", title: "Remove a technician login", app: "fieldops", runs: [
    { verdict: "running", when: "now" }, { verdict: "pass", when: "Sep 24 04:21" } ] },
  { id: "FS-04", title: "Invoice a completed job and mark it paid", app: "fieldops", runs: [
    { verdict: "running", when: "now" }, { verdict: "pass", when: "Sep 24 07:22" }, { verdict: "pass", when: "Sep 24 03:11" } ] },
  { id: "FS-05", title: "Validation errors on the work order form", app: "fieldops", runs: [
    { verdict: "pass", when: "Sep 24 08:20", note: "finding withdrawn" } ] },
  { id: "FS-02", title: "Technician completes a job", app: "fieldops", runs: [
    { verdict: "pass", when: "Sep 24 09:31" }, { verdict: "blocked", when: "Sep 24 08:52", note: "no past-date fixture" } ] },
  { id: "FS-08", title: "Technician navigation", app: "fieldops", runs: [
    { verdict: "waiting", when: "now" }, { verdict: "not-run", when: "Sep 24 08:40", note: "credential" } ] },
  { id: "FS-03", title: "Reschedule from the dispatch board", app: "fieldops", runs: [
    { verdict: "blocked", when: "Sep 24 09:09", note: "product decision" } ] },
];
