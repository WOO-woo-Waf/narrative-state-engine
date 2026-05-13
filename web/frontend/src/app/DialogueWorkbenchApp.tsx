import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getScenarios } from "../agentRuntime/api/scenarios";
import { AgentShell } from "../agentRuntime/shell/AgentShell";
import { mergeScenarioMetadata } from "../agentRuntime/scenarios/metadata";
import { getRegisteredScenarios } from "../agentRuntime/scenarios/registry";
import { registerMockImageScenario } from "../scenarios/mockImage/MockImageScenarioProvider";
import { registerNovelScenario } from "../scenarios/novel/NovelScenarioProvider";

registerNovelScenario();
registerMockImageScenario();

export function DialogueWorkbenchApp() {
  const scenariosQuery = useQuery({ queryKey: ["agent-runtime", "scenarios"], queryFn: getScenarios });
  const scenarios = useMemo(() => getRegisteredScenarios(), []);
  const mergedScenarios = useMemo(() => mergeScenarioMetadata(scenarios, scenariosQuery.data?.scenarios), [scenarios, scenariosQuery.data?.scenarios]);
  return <AgentShell scenarios={mergedScenarios} defaultScenarioType="novel_state_machine" />;
}
