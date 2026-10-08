import type { Preview } from "@storybook/react-vite";
import { themes } from "storybook/theming";
import { TooltipProvider } from "../src/components/ui/tooltip";
import "../src/index.css";

const preview: Preview = {
  decorators: [
    (Story) => (
      <div className="dark">
        <TooltipProvider>
          <Story />
        </TooltipProvider>
      </div>
    ),
  ],
  parameters: {
    layout: "fullscreen",
    backgrounds: { disable: true },
    docs: { theme: themes.dark },
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    a11y: { test: "todo" },
    options: { storySort: { order: ["Overview", "Foundations", "Concepts", "Current UI"] } },
  },
};

export default preview;
