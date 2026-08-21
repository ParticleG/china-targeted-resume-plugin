import { describe, expect, test } from "bun:test";
import {
  RESUME_HELP_TOPICS,
  isResumeHelpRequest,
  resolveResumeHelpTopic,
  resumeHelpCompletions,
  resumeHelpError,
  resumeHelpText,
} from "../../src/plugin/commands/help.ts";

describe("resume help topic contract", () => {
  test("resolves exact topics and bounded command aliases", () => {
    expect(resolveResumeHelpTopic("")).toBe("overview");
    expect(resolveResumeHelpTopic("--help")).toBe("overview");
    expect(resolveResumeHelpTopic("/resume-status")).toBe("status");
    expect(resolveResumeHelpTopic("analyse")).toBe("analyze");
    expect(resolveResumeHelpTopic("privacy extra")).toBeUndefined();
    expect(resolveResumeHelpTopic("unknown")).toBeUndefined();
  });

  test("recognizes only explicit inline help flags", () => {
    expect(isResumeHelpRequest("help")).toBe(true);
    expect(isResumeHelpRequest("-h")).toBe(true);
    expect(isResumeHelpRequest("--help")).toBe(true);
    expect(isResumeHelpRequest("help extra")).toBe(false);
    expect(isResumeHelpRequest("/tmp/--help")).toBe(false);
  });

  test("keeps every topic deterministic, bounded, and free of private paths", () => {
    for (const topic of RESUME_HELP_TOPICS) {
      const text = resumeHelpText(topic);
      expect(text.length).toBeGreaterThan(40);
      expect(text.length).toBeLessThan(4_000);
      expect(text).not.toContain("/home/particleg");
      expect(text).not.toContain("source body sentinel");
    }
  });

  test("returns prefix completions and an actionable unknown-topic error", () => {
    expect(resumeHelpCompletions("tr")).toEqual([
      {
        value: "troubleshooting",
        label: "troubleshooting",
        description: "Common safe failures and prerequisites",
      },
    ]);
    expect(resumeHelpCompletions("two words")).toBeNull();
    expect(resumeHelpError("wat")).toContain("/resume-help");
    expect(resumeHelpError("wat")).toContain("privacy");
  });
});
