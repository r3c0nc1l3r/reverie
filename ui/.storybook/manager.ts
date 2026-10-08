import { addons } from "storybook/manager-api";
import { create } from "storybook/theming";

addons.setConfig({
  theme: create({
    base: "dark",
    brandTitle: "Reverie · UI concepts",
    brandTarget: "_self",
    colorPrimary: "#9cc4ff",
    colorSecondary: "#7ee7c7",
    appBg: "#0b0d14",
    appContentBg: "#0b0d14",
    appBorderColor: "#242a39",
    barBg: "#11141d",
    textColor: "#e7e9f0",
    fontBase: '"Inter", system-ui, sans-serif',
  }),
});
