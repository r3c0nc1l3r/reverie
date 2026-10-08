import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta = { title: "Current UI", parameters: { layout: "padded" } };
export default meta;

const Shot = ({ src, alt }: { src: string; alt: string }) => (
  <div className="p-6">
    <img
      src={`${import.meta.env.BASE_URL}${src}`}
      alt={alt}
      className="w-full max-w-[1400px] rounded-lg border border-border"
    />
  </div>
);

/** The dashboard as it ships today (127.0.0.1:7788), for comparison. */
export const Dashboard: StoryObj = { render: () => <Shot src="current-dashboard.png" alt="Current reverie dashboard" /> };
/** The replay deck as it ships today. */
export const Replay: StoryObj = { render: () => <Shot src="current-replay.png" alt="Current reverie replay" /> };
