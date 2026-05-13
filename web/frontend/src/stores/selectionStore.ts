import { create } from "zustand";
import type { GraphKind } from "../types/graph";

type SelectionState = {
  selectedObjectIds: string[];
  selectedCandidateIds: string[];
  selectedEvidenceIds: string[];
  selectedBranchIds: string[];
  selectedCandidateSetId: string;
  graphKind: GraphKind;
  setSelectedObjectIds: (ids: string[]) => void;
  setSelectedCandidateIds: (ids: string[]) => void;
  toggleCandidateId: (id: string) => void;
  setSelectedEvidenceIds: (ids: string[]) => void;
  setSelectedBranchIds: (ids: string[]) => void;
  setSelectedCandidateSetId: (id: string) => void;
  setGraphKind: (kind: GraphKind) => void;
  clearSelections: () => void;
};

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedObjectIds: [],
  selectedCandidateIds: [],
  selectedEvidenceIds: [],
  selectedBranchIds: [],
  selectedCandidateSetId: "",
  graphKind: "state",
  setSelectedObjectIds: (ids) => set({ selectedObjectIds: ids }),
  setSelectedCandidateIds: (ids) => set({ selectedCandidateIds: ids }),
  toggleCandidateId: (id) =>
    set((state) => ({
      selectedCandidateIds: state.selectedCandidateIds.includes(id)
        ? state.selectedCandidateIds.filter((item) => item !== id)
        : [...state.selectedCandidateIds, id]
    })),
  setSelectedEvidenceIds: (ids) => set({ selectedEvidenceIds: ids }),
  setSelectedBranchIds: (ids) => set({ selectedBranchIds: ids }),
  setSelectedCandidateSetId: (id) => set({ selectedCandidateSetId: id }),
  setGraphKind: (kind) => set({ graphKind: kind }),
  clearSelections: () =>
    set({
      selectedObjectIds: [],
      selectedCandidateIds: [],
      selectedEvidenceIds: [],
      selectedBranchIds: [],
      selectedCandidateSetId: ""
    })
}));
