// Loads jocal's Pi read extension the way Pi does (its default export gets the ExtensionAPI), then runs the
// registered `read` once. Usage: node read_tool.mjs <extension> <cwd> '<params json>'
// Prints {"name", "text"} for a result, or {"name", "error"} when execute throws (Pi's failed tool result).
const [extension, cwd, params] = process.argv.slice(2);
const tools = [];
const pi = { registerTool: (tool) => tools.push(tool) };
await (await import(extension)).default(pi);
const tool = tools.find((t) => t.name === "read");
let out;
try {
  const result = await tool.execute("call-1", JSON.parse(params), undefined, undefined, { cwd });
  out = { name: tool.name, text: result.content.map((c) => c.text).join("") };
} catch (e) {
  out = { name: tool.name, error: e.message };
}
console.log(JSON.stringify(out));
