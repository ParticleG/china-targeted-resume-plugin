import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { registerResumeCommands } from "./commands/index.ts";
import { ResumePluginRuntime } from "./runtime.ts";
import { registerResumeTools } from "./tools/index.ts";

/** Pure registration boundary used by OMP and import-only tests. */
export function registerChinaTargetedResumeExtension(pi: ExtensionAPI): ResumePluginRuntime {
  const runtime = new ResumePluginRuntime();
  registerResumeCommands(pi, runtime);
  registerResumeTools(pi, runtime);
  return runtime;
}

export default function extension(pi: ExtensionAPI): void {
  registerChinaTargetedResumeExtension(pi);
}
