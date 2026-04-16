#!/usr/bin/env node
/**
 * Self-Heal Agent — Canonical Template
 * Copy to scripts/self-heal-agent.js in your application repo.
 *
 * This is the constrained agent loop that runs inside GitHub Actions.
 * It receives a bug diagnosis and attempts a surgical fix.
 *
 * Safety: All constraints are enforced at the tool boundary.
 * The agent CANNOT bypass path safety, bash safety, or resource bounds
 * through prompt manipulation — they are code-level gates.
 */

import Anthropic from "@anthropic-ai/sdk";
import fs from "fs";
import path from "path";
import { execSync } from "child_process";

// --- Configuration ---
const MAX_TURNS = 25;
const MAX_TOKENS_PER_TURN = 4000;
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-20250514";
const REPO_ROOT = process.cwd();

// --- Path Safety ---
const FORBIDDEN_PATTERNS = [
  /^\.github\//,
  /\.env($|\.)/,
  /^package-lock\.json$/,
  /^yarn\.lock$/,
  /^node_modules\//,
  /^\.vercel\//,
  /^\.git\//,
  /^scripts\/self-heal-agent\.js$/,
];

function isPathSafe(filePath) {
  const normalized = path.normalize(filePath);
  if (normalized.startsWith("..") || path.isAbsolute(normalized)) {
    return { safe: false, reason: "Path traversal or absolute path not allowed" };
  }
  const resolved = path.resolve(REPO_ROOT, normalized);
  if (!resolved.startsWith(REPO_ROOT)) {
    return { safe: false, reason: "Path resolves outside repository root" };
  }
  for (const pattern of FORBIDDEN_PATTERNS) {
    if (pattern.test(normalized)) {
      return { safe: false, reason: `Path matches forbidden pattern: ${pattern}` };
    }
  }
  return { safe: true };
}

// --- Bash Safety ---
const ALLOWED_COMMANDS = [
  /^ls\b/, /^cat\b/, /^grep\b/, /^rg\b/, /^find\b/,
  /^head\b/, /^tail\b/, /^wc\b/,
  /^npm test/, /^npm run build/, /^npm run lint/,
  /^npx jest/, /^npx vitest/,
  /^node -e\b/,
  /^git status/, /^git log/, /^git diff/, /^git show/,
];

const DENIED_PATTERNS = [
  /\brm\b/, /\bmv\b/, /\bsudo\b/, /\bcurl\b/, /\bwget\b/,
  /\bchmod\b/, /\bchown\b/,
];

const META_EXEMPT = [/^grep\b/, /^rg\b/, /^find\b/, /^node -e\b/];
const SHELL_META = /[;&|`$(){}]/;

function isBashSafe(command) {
  const trimmed = command.trim();

  for (const pattern of DENIED_PATTERNS) {
    if (pattern.test(trimmed)) {
      return { safe: false, reason: `Command contains denied pattern: ${pattern}` };
    }
  }

  const isAllowed = ALLOWED_COMMANDS.some((p) => p.test(trimmed));
  if (!isAllowed) {
    return { safe: false, reason: "Command not in allow-list" };
  }

  const isExempt = META_EXEMPT.some((p) => p.test(trimmed));
  if (!isExempt && SHELL_META.test(trimmed)) {
    return { safe: false, reason: "Shell metacharacters not allowed for this command" };
  }

  return { safe: true };
}

// --- Tool Definitions ---
const tools = [
  {
    name: "read_file",
    description: "Read the contents of a file at the given path (relative to repo root).",
    input_schema: {
      type: "object",
      properties: { path: { type: "string", description: "Relative file path" } },
      required: ["path"],
    },
  },
  {
    name: "list_directory",
    description: "List files and directories at the given path.",
    input_schema: {
      type: "object",
      properties: { path: { type: "string", description: "Relative directory path", default: "." } },
    },
  },
  {
    name: "grep",
    description: "Search for a pattern in files. Returns matching lines with file paths.",
    input_schema: {
      type: "object",
      properties: {
        pattern: { type: "string", description: "Search pattern (regex)" },
        path: { type: "string", description: "Directory to search in", default: "." },
      },
      required: ["pattern"],
    },
  },
  {
    name: "edit_file",
    description: "Replace old_string with new_string in the file. The old_string must be unique in the file.",
    input_schema: {
      type: "object",
      properties: {
        path: { type: "string" },
        old_string: { type: "string" },
        new_string: { type: "string" },
      },
      required: ["path", "old_string", "new_string"],
    },
  },
  {
    name: "write_file",
    description: "Write content to a new file. Fails if the file already exists (use edit_file instead).",
    input_schema: {
      type: "object",
      properties: {
        path: { type: "string" },
        content: { type: "string" },
      },
      required: ["path", "content"],
    },
  },
  {
    name: "bash",
    description: "Run an allowed shell command. Only inspection and test commands are permitted.",
    input_schema: {
      type: "object",
      properties: { command: { type: "string" } },
      required: ["command"],
    },
  },
  {
    name: "finish",
    description: "Terminate the agent loop. Call this when done.",
    input_schema: {
      type: "object",
      properties: {
        applied_fix: { type: "boolean", description: "Whether a fix was applied" },
        summary: { type: "string", description: "Summary of what was done" },
      },
      required: ["applied_fix", "summary"],
    },
  },
];

// --- Tool Implementations ---
function executeTool(name, input) {
  switch (name) {
    case "read_file": {
      const check = isPathSafe(input.path);
      if (!check.safe) return { error: check.reason };
      const fullPath = path.resolve(REPO_ROOT, input.path);
      if (!fs.existsSync(fullPath)) return { error: `File not found: ${input.path}` };
      return { content: fs.readFileSync(fullPath, "utf-8") };
    }
    case "list_directory": {
      const dirPath = input.path || ".";
      const check = isPathSafe(dirPath);
      if (!check.safe) return { error: check.reason };
      const fullPath = path.resolve(REPO_ROOT, dirPath);
      if (!fs.existsSync(fullPath)) return { error: `Directory not found: ${dirPath}` };
      return { entries: fs.readdirSync(fullPath, { withFileTypes: true }).map((e) => `${e.isDirectory() ? "d" : "f"} ${e.name}`) };
    }
    case "grep": {
      const check = isPathSafe(input.path || ".");
      if (!check.safe) return { error: check.reason };
      try {
        const result = execSync(`grep -rn "${input.pattern.replace(/"/g, '\\"')}" ${input.path || "."}`, {
          cwd: REPO_ROOT,
          encoding: "utf-8",
          maxBuffer: 1024 * 1024,
          timeout: 10000,
        });
        return { matches: result.split("\n").slice(0, 50).join("\n") };
      } catch (e) {
        return { matches: "", note: "No matches found" };
      }
    }
    case "edit_file": {
      const check = isPathSafe(input.path);
      if (!check.safe) return { error: check.reason };
      const fullPath = path.resolve(REPO_ROOT, input.path);
      if (!fs.existsSync(fullPath)) return { error: `File not found: ${input.path}` };
      const content = fs.readFileSync(fullPath, "utf-8");
      const count = content.split(input.old_string).length - 1;
      if (count === 0) return { error: "old_string not found in file" };
      if (count > 1) return { error: `old_string matches ${count} times — must be unique` };
      fs.writeFileSync(fullPath, content.replace(input.old_string, input.new_string));
      return { success: true };
    }
    case "write_file": {
      const check = isPathSafe(input.path);
      if (!check.safe) return { error: check.reason };
      const fullPath = path.resolve(REPO_ROOT, input.path);
      if (fs.existsSync(fullPath)) return { error: "File already exists — use edit_file instead" };
      const dir = path.dirname(fullPath);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(fullPath, input.content);
      return { success: true };
    }
    case "bash": {
      const check = isBashSafe(input.command);
      if (!check.safe) return { error: check.reason };
      try {
        const result = execSync(input.command, {
          cwd: REPO_ROOT,
          encoding: "utf-8",
          maxBuffer: 1024 * 1024,
          timeout: 60000,
        });
        return { output: result.slice(0, 5000) };
      } catch (e) {
        return { error: e.message.slice(0, 2000) };
      }
    }
    case "finish": {
      return { done: true, applied_fix: input.applied_fix, summary: input.summary };
    }
    default:
      return { error: `Unknown tool: ${name}` };
  }
}

// --- Main Agent Loop ---
async function main() {
  const client = new Anthropic();
  const claudeMd = fs.readFileSync(process.env.CLAUDE_MD || path.join(REPO_ROOT, "CLAUDE.md"), "utf-8");
  const diagnosis = JSON.parse(process.env.DIAGNOSIS || "{}");

  const systemPrompt = `${claudeMd}

---

You are the self-healing agent for this application. A user reported a bug and the diagnostic pass produced the following assessment:

Severity: ${diagnosis.severity || "unknown"}
Confidence: ${diagnosis.confidence || "unknown"}
Root cause: ${diagnosis.root_cause || "unknown"}
Suspected files: ${JSON.stringify(diagnosis.suspected_files || [])}
Proposed fix: ${diagnosis.proposed_fix || "none"}

Your job: verify the diagnosis against the actual code, apply a surgical fix if confirmed, and call finish. If you cannot confirm the diagnosis, call finish with applied_fix: false. Do NOT produce speculative changes. Prefer minimal, targeted edits.`;

  const messages = [
    {
      role: "user",
      content: `Bug report #${process.env.BUG_ID}: ${diagnosis.description || "No description provided"}\n\nDiagnosis: ${diagnosis.narrative || "See structured fields above."}\n\nStart by reading the suspected files to verify the diagnosis.`,
    },
  ];

  for (let turn = 0; turn < MAX_TURNS; turn++) {
    const response = await client.messages.create({
      model: MODEL,
      max_tokens: MAX_TOKENS_PER_TURN,
      system: systemPrompt,
      tools,
      messages,
    });

    // Process tool calls
    const toolResults = [];
    let finished = false;

    for (const block of response.content) {
      if (block.type === "tool_use") {
        const result = executeTool(block.name, block.input);
        if (block.name === "finish") {
          console.log(`Agent finished: applied_fix=${result.applied_fix}, summary=${result.summary}`);
          finished = true;
        }
        toolResults.push({
          type: "tool_result",
          tool_use_id: block.id,
          content: JSON.stringify(result),
        });
      }
    }

    messages.push({ role: "assistant", content: response.content });

    if (finished || response.stop_reason === "end_turn") break;

    if (toolResults.length > 0) {
      messages.push({ role: "user", content: toolResults });
    }
  }
}

main().catch((e) => {
  console.error("Agent error:", e.message);
  process.exit(1);
});
