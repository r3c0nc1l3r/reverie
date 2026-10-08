import type { Meta, StoryObj } from "@storybook/react-vite";
import { FrameCompare } from "../components/FrameCompare";
import { CheckpointInbox } from "../concepts/CheckpointInbox";
import { FindingsTriage } from "../concepts/FindingsTriage";
import { MissionControl } from "../concepts/MissionControl";
import { RunReview } from "../concepts/RunReview";
import { liveRunId, pastRunId } from "../data/fieldops";
import { RunView } from "../concepts/RunView";
import { SuiteMatrix } from "../concepts/SuiteMatrix";
import { crop, demoRun, frames, mixedRun } from "../data/sample";

const meta: Meta = { title: "Concepts", parameters: { layout: "fullscreen" } };
export default meta;
type S = StoryObj;

/**
 * History first. The left rail lists the current run and past runs stored in the project's `.reverie/runs/`. The spec
 * outline is the page: each step with its verdict and the agent's notes. Individual actions stay in the drawer.
 */
export const ReviewLive: S = { name: "1 · Run review — live run", render: () => <RunReview initialRun={liveRunId} /> };
export const ReviewPast: S = { name: "1 · Run review — past run", render: () => <RunReview initialRun={pastRunId} /> };
export const ReviewDrawer: S = {
  name: "1 · Run review — actions drawer open",
  render: () => <RunReview initialRun={pastRunId} initialStep={2} drawerOpen />,
};

/** Every live session at a glance: what it is doing, how long since the last action, and whether it needs you. */
export const MissionControlView: S = { name: "2 · Mission control", render: () => <MissionControl /> };

/** One queue for all checkpoints across sessions, with context, the suggested command, fact chips, and a secret lint. */
export const InboxSignIn: S = { name: "3 · Checkpoint inbox — sign-in", render: () => <CheckpointInbox initial={0} /> };
export const InboxDatabase: S = { name: "3 · Checkpoint inbox — database proof", render: () => <CheckpointInbox initial={1} /> };
export const InboxMail: S = { name: "3 · Checkpoint inbox — mail proof", render: () => <CheckpointInbox initial={2} /> };

/** Steps are the spine. Actions, checks, findings, and the visual review sit inside their step. Raw events stay one click away. */
export const RunPassing: S = { name: "4 · Run view — passing run", render: () => <RunView run={demoRun} initialStep={2} /> };
export const RunMixed: S = { name: "4 · Run view — finding and checkpoint", render: () => <RunView run={mixedRun} initialStep={3} /> };

/** Before (target ringed) and after for each action, side by side or as a swipe. */
export const CompareSplit: S = {
  name: "5 · Frame compare — split",
  render: () => <div style={{ padding: 24, maxWidth: 1100 }}><FrameCompare frame={{ before: frames.checkboxesTarget, after: frames.checkboxesDone, crop }} label="Step 2 · clicked checkbox 1" /></div>,
};
export const CompareSwipe: S = {
  name: "5 · Frame compare — swipe",
  render: () => <div style={{ padding: 24, maxWidth: 900 }}><FrameCompare mode="swipe" frame={{ before: frames.loadingTarget, after: frames.hello, crop }} label="Step 3 · clicked Start" /></div>,
};

/** Tests by run history. The newest run is outlined; the reason for each non-pass is one column away. */
export const Matrix: S = { name: "6 · Suite matrix", render: () => <SuiteMatrix /> };

/** Findings get a state: open, by design, withdrawn, fixed. Withdrawn and by-design findings stop blocking a pass. */
export const Findings: S = { name: "7 · Findings triage", render: () => <FindingsTriage /> };
