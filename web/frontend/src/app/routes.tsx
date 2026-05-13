import { Shell } from "./Shell";
import { DialogueWorkbenchApp } from "./DialogueWorkbenchApp";

export function Routes() {
  const path = window.location.pathname;
  if (path.includes("/workbench-dialogue") || path.includes("/workbench-v3")) return <DialogueWorkbenchApp />;
  return <Shell />;
}
