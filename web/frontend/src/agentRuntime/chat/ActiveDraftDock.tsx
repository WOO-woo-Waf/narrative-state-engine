import type { DialogueAction } from "../../types/action";
import { ActionDraftBlock } from "../drafts/ActionDraftBlock";
import type { RuntimeSelection } from "../types";

export function ActiveDraftDock({
  action,
  onConfirmAndExecute,
  onContinue,
  onCancel,
  selection,
  onOpenPlotPlanPicker
}: {
  action: DialogueAction;
  onConfirmAndExecute: (action: DialogueAction) => void;
  onContinue?: (action: DialogueAction) => void;
  onCancel: (action: DialogueAction) => void;
  selection?: RuntimeSelection;
  onOpenPlotPlanPicker?: () => void;
}) {
  return (
    <ActionDraftBlock
      action={action}
      onConfirmAndExecute={onConfirmAndExecute}
      onContinue={onContinue}
      onCancel={onCancel}
      selection={selection}
      onOpenPlotPlanPicker={onOpenPlotPlanPicker}
    />
  );
}
