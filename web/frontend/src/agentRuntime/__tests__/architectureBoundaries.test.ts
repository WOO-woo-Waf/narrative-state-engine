import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();
const srcRoot = join(root, "src");

describe("agent runtime architecture boundaries", () => {
  it("does not import the legacy sessions API", () => {
    const legacyImport = /from\s+["'][^"']*api\/dialogue["']/;
    const offenders = filesUnder(join(srcRoot, "agentRuntime")).filter((file) => legacyImport.test(readFileSync(file, "utf8")));
    expect(offenders.map((file) => relative(root, file))).toEqual([]);
  });

  it("keeps novel workbench components out of AgentShell and app assembly", () => {
    const files = [join(srcRoot, "agentRuntime", "shell", "AgentShell.tsx"), join(srcRoot, "app", "DialogueWorkbenchApp.tsx")];
    const forbidden = ["CandidateReviewTable", "GraphPanel", "BranchReviewPanel", "StateEnvironmentPanel"];
    const offenders = files.flatMap((file) => {
      const text = readFileSync(file, "utf8");
      return forbidden.filter((token) => text.includes(token)).map((token) => `${relative(root, file)}:${token}`);
    });
    expect(offenders).toEqual([]);
  });
});

function filesUnder(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return filesUnder(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}
