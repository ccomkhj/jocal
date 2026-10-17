/**
 * jocal's read budget for Pi. Loaded only by `jocal pi`, it replaces
 * Pi's built-in `read` (50 KB / 2,000 lines) with one that returns a whole text file up to the cap jocal sizes to
 * the window, JOCAL_READ_CAP_TOKENS, estimated as chars/4.
 * Only node built-ins and a plain JSON Schema, so it loads without Pi's packages (the suite runs it under node).
 */

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// A positive whole number of tokens, or 0 when unset or invalid: then every read is refused, never uncapped.
const CAP_SETTING = process.env.JOCAL_READ_CAP_TOKENS ?? "";
const CAP_TOKENS = /^[1-9]\d*$/.test(CAP_SETTING) ? Number(CAP_SETTING) : 0;
const CAP_CHARS = CAP_TOKENS * 4;

const count = (n: number) => n.toLocaleString("en-US");
const shellQuote = (s: string) => (/^[\w./:=,@%+-]+$/.test(s) ? s : `'${s.replaceAll("'", `'\\''`)}'`);

// Thrown, so Pi marks the result failed: nothing is dropped without the model seeing why.
function overCap(what: string, path: string): never {
	throw new Error(
		`${what}, over the read cap of ~${count(CAP_TOKENS)} tokens for this window. To answer from the whole file, run: ` +
			`jocal summarise ${shellQuote(path)} "<question>". To look at part of it, read with offset/limit.`,
	);
}

type Params = { path: string; offset?: number; limit?: number };

// Lines `offset`.. (1-indexed), at most `limit` of them and never more than the cap: a slice cut short says so.
function slice(path: string, text: string, offset = 1, limit = Infinity) {
	const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
	const start = Math.max(0, offset - 1);
	if (start >= lines.length) throw new Error(`Offset ${offset} is beyond end of file (${lines.length} lines total)`);
	const end = Math.min(start + limit, lines.length);
	if (lines[start].length > CAP_CHARS) overCap(`line ${start + 1} of ${path} is ${count(lines[start].length)} chars`, path);
	let out = "", i = start;
	for (; i < end && out.length + lines[i].length <= CAP_CHARS; i++) out += lines[i];
	if (i < end) out += `\n\n[Showing lines ${start + 1}-${i} of ${lines.length} (read cap ~${count(CAP_TOKENS)} tokens). Use offset=${i + 1} to continue.]`;
	else if (end < lines.length) out += `\n\n[${lines.length - end} more lines in file. Use offset=${end + 1} to continue.]`;
	return { content: [{ type: "text", text: out }], details: undefined };
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "read",
		label: "read",
		description:
			`Read the contents of a text file, the whole file up to ~${count(CAP_TOKENS)} tokens. A larger file is ` +
			"refused with a `jocal summarise` command to run instead; use offset/limit (lines) to read part of it.",
		promptSnippet: "Read file contents",   // the built-in read's prompt lines
		promptGuidelines: ["Use read to examine files instead of cat or sed."],
		parameters: {
			type: "object",
			properties: {
				path: { type: "string", description: "Path to the file to read (relative or absolute)" },
				offset: { type: "number", description: "Line number to start reading from (1-indexed)" },
				limit: { type: "number", description: "Maximum number of lines to read" },
			},
			required: ["path"],
		},
		async execute(_id: string, { path, offset, limit }: Params, _signal: unknown, _onUpdate: unknown, ctx: { cwd: string }) {
			if (!CAP_TOKENS) {
				throw new Error(
					`read is off: JOCAL_READ_CAP_TOKENS is ${CAP_SETTING ? `'${CAP_SETTING}'` : "unset"}, not a token count. ` +
						"This read extension takes its cap from `jocal pi`, which sets it; start Pi with `jocal pi`.",
				);
			}
			const text = await readFile(resolve(ctx.cwd, path), "utf-8");
			if (offset !== undefined || limit !== undefined) return slice(path, text, offset, limit);
			if (text.length > CAP_CHARS) {
				overCap(`${path} is ${count(text.length)} chars (~${count(Math.round(text.length / 4))} tokens)`, path);
			}
			return { content: [{ type: "text", text }], details: undefined };
		},
	});
}
