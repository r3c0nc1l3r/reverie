import { useState } from "react";
import type { Frame } from "../data/types";
import { FrameImg } from "./kit";
import { ToggleGroup, ToggleGroupItem } from "./ui/toggle-group";

export type CompareMode = "after" | "split" | "swipe";

/**
 * FrameCompare displays before and after frames with multiple view modes.
 */
export function FrameCompare({ frame, mode: initial = "split", label }: { frame: Frame; mode?: CompareMode; label?: string }) {
  const [mode, setMode] = useState<CompareMode>(frame.before ? initial : "after");
  const [pos, setPos] = useState(50);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-4">
        {label && <span className="text-sm text-muted-foreground">{label}</span>}
        <div className="flex-1" />
        <ToggleGroup
          type="single"
          value={mode}
          onValueChange={(value) => {
            if (value && (value === "after" || value === "split" || value === "swipe")) {
              if (value !== "after" && !frame.before) return;
              setMode(value);
            }
          }}
        >
          <ToggleGroupItem value="after" aria-label="After view">
            After
          </ToggleGroupItem>
          <ToggleGroupItem value="split" aria-label="Before | After" disabled={!frame.before}>
            Before | After
          </ToggleGroupItem>
          <ToggleGroupItem value="swipe" aria-label="Swipe" disabled={!frame.before}>
            Swipe
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      {mode === "after" && <FrameImg src={frame.after} crop={frame.crop} alt="Frame after the action" />}

      {mode === "split" && frame.before && (
        <div className="grid grid-cols-2 gap-4">
          <figure className="space-y-2">
            <FrameImg src={frame.before} crop={frame.crop} alt="Frame before the action, target ringed" />
            <figcaption className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded-full bg-verdict-blocked px-2 py-1 text-background">Before</span> target ringed
            </figcaption>
          </figure>
          <figure className="space-y-2">
            <FrameImg src={frame.after} crop={frame.crop} alt="Frame after the action" />
            <figcaption className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded-full bg-verdict-pass px-2 py-1 text-background">After</span>
            </figcaption>
          </figure>
        </div>
      )}

      {mode === "swipe" && frame.before && (
        <div className="relative w-full">
          <FrameImg src={frame.after} crop={frame.crop} alt="Frame after the action" />
          <div
            className="absolute inset-0"
            style={{
              clipPath: `inset(0 ${100 - pos}% 0 0)`,
              pointerEvents: "none",
            }}
          >
            <FrameImg src={frame.before} crop={frame.crop} alt="Frame before the action" />
          </div>
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-primary shadow-lg pointer-events-none"
            style={{ left: `${pos}%` }}
          />
          <input
            type="range"
            className="absolute inset-0 opacity-0 cursor-ew-resize m-0"
            min={0}
            max={100}
            value={pos}
            onChange={(e) => setPos(Number(e.target.value))}
            aria-label="Swipe between before and after"
          />
          <span className="absolute top-2 left-2 rounded-full bg-verdict-blocked px-2 py-1 text-xs font-bold uppercase text-background">
            Before
          </span>
          <span className="absolute top-2 right-2 rounded-full bg-verdict-pass px-2 py-1 text-xs font-bold uppercase text-background">
            After
          </span>
        </div>
      )}
    </div>
  );
}
