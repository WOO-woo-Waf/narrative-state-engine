import type { ScenarioDefinition } from "../types";

export function ContextModeBar({
  scenario,
  value,
  onChange
}: {
  scenario: ScenarioDefinition;
  value: string;
  onChange: (sceneType: string) => void;
}) {
  return (
    <section className="context-mode-bar" aria-label="上下文模式">
      <span>上下文模式</span>
      <div>
        {scenario.scenes.map((scene) => (
          <button type="button" className={scene.scene_type === value ? "active" : ""} key={scene.scene_type} onClick={() => onChange(scene.scene_type)}>
            {scene.label}
          </button>
        ))}
      </div>
    </section>
  );
}

