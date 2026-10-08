// One icon set for the whole UI: Lucide, through react-icons (`react-icons/lu`).
// Map every concept to its icon here so screens stay consistent. No emoji or unicode pictographs.
import type { IconType } from "react-icons";
import {
  LuBan, LuBot, LuBug, LuCheck, LuChevronsUpDown, LuCircle, LuCircleHelp, LuCompass, LuDatabase, LuGlobe, LuHand,
  LuHourglass, LuKeyRound, LuLoaderCircle, LuMail, LuMessageSquareText, LuMinus, LuMousePointer2,
  LuMousePointerClick, LuSquareCheck, LuTextCursorInput, LuUser, LuWrench,
} from "react-icons/lu";
import type { Action, Actor, Checkpoint, Verdict } from "../data/types";

export const verdictIcon: Record<Verdict, IconType> = {
  pass: LuCheck,
  "app-fail": LuBug,
  harness: LuWrench,
  blocked: LuBan,
  "not-run": LuMinus,
  running: LuLoaderCircle,
  waiting: LuHand,
  pending: LuCircle,
};

export const actorIcon: Record<Actor, IconType> = {
  laya: LuMousePointer2,
  pilot: LuBot,
  orchestrator: LuCompass,
  person: LuUser,
};

export const checkpointIcon: Record<Checkpoint["kind"], IconType> = {
  "sign-in": LuKeyRound,
  database: LuDatabase,
  mail: LuMail,
  question: LuCircleHelp,
};

export const actionIcon: Record<Action["kind"], IconType> = {
  click: LuMousePointerClick,
  type: LuTextCursorInput,
  select: LuChevronsUpDown,
  goto: LuGlobe,
  wait: LuHourglass,
  check: LuSquareCheck,
  say: LuMessageSquareText,
};
