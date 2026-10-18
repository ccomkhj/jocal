/**
 * jocal's web search for Pi. Loaded only by `jocal pi` when WEB_SEARCH is on, it adds a `web_search` tool that posts
 * the query to DuckDuckGo's HTML endpoint, JOCAL_WEB_SEARCH_URL, and returns the results' titles, links and snippets.
 * The query is the one thing that leaves the Mac; the page is read here, and only the results reach the model.
 * Only node built-ins and a plain JSON Schema, so it loads without Pi's packages (the suite runs it under node).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// A URL, or undefined when unparsable.
const parse = (url: string, base?: string) => {
	try {
		return new URL(url, base);
	} catch {
		return undefined;
	}
};

// An http(s) URL, or undefined when unset or invalid: then every search is refused.
const URL_SETTING = process.env.JOCAL_WEB_SEARCH_URL ?? "";
const ENDPOINT = /^https?:\/\//.test(URL_SETTING) ? parse(URL_SETTING) : undefined;
const MAX_RESULTS = 8;
const TIMEOUT_MS = 20_000;
// DuckDuckGo serves its bot check, not results, to a client that doesn't look like a browser.
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15";

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
function entity(e: string) {
	if (e[0] !== "#") return ENTITIES[e.toLowerCase()];
	const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
	return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : undefined;
}

// HTML as one line of plain text: tags dropped, entities decoded, whitespace collapsed.
const text = (html: string) =>
	html
		.replace(/<[^>]*>/g, "")
		.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) => entity(e) ?? m)
		.replace(/\s+/g, " ")
		.trim();

// A result's link, out of DuckDuckGo's redirect (//duckduckgo.com/l/?uddg=<url>) when it has one; undefined for an
// ad (duckduckgo.com/y.js) or a link that isn't a URL.
function link(href: string) {
	const url = parse(text(href), "https://duckduckgo.com");
	if (!url) return undefined;
	if (url.hostname.endsWith("duckduckgo.com")) {
		return url.pathname === "/l/" ? (url.searchParams.get("uddg") ?? undefined) : undefined;
	}
	return url.href;
}

type Result = { title: string; url: string; snippet: string };

// The results in DuckDuckGo's HTML page: each is a `result` block with a `result__a` title link and a
// `result__snippet`. Ads (`result--ad`) are left out.
function results(html: string): Result[] {
	const out: Result[] = [];
	for (const block of html.split(/<div class="result(?=[\s"])/).slice(1)) {
		if (/^[^>]*result--ad/.test(block)) continue;
		const a = block.match(/<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/) ??
			block.match(/<a[^>]*href="([^"]*)"[^>]*class="result__a"[^>]*>([\s\S]*?)<\/a>/);
		if (!a) continue;
		const url = link(a[1]);
		if (!url) continue;
		const snippet = block.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/(?:a|div|td)>/);
		out.push({ title: text(a[2]), url, snippet: snippet ? text(snippet[1]) : "" });
		if (out.length === MAX_RESULTS) break;
	}
	return out;
}

// The results for `query` from the engine at `endpoint`. A failure is thrown, so Pi marks the result failed and the
// model sees why.
async function search(endpoint: URL, query: string, signal?: AbortSignal) {
	const host = endpoint.host;
	const timeout = AbortSignal.timeout(TIMEOUT_MS);
	let res: Response;
	try {
		res = await fetch(endpoint, {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT },
			body: new URLSearchParams({ q: query }),
			signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
		});
	} catch (e) {
		if (signal?.aborted) throw e;
		const cause = (e as Error).cause as { code?: string; message?: string } | undefined;
		const why = timeout.aborted ? `no answer in ${TIMEOUT_MS / 1000} s` : (cause?.code ?? cause?.message ?? (e as Error).message);
		throw new Error(`web_search could not reach ${host} (${why}). Answer without it, and say so.`);
	}
	const html = await res.text();
	if (res.status === 202 || /anomaly-modal|class="anomaly/.test(html)) {
		throw new Error(`${host} took this search for a bot and sent its check instead of results. Wait a minute before searching again.`);
	}
	if (!res.ok) throw new Error(`${host} answered HTTP ${res.status} to the search.`);
	return results(html);
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "web_search",
		label: "web search",
		description:
			"Search the web. Returns up to 8 results, each a title, its URL and a short snippet. " +
			"The query leaves this Mac for a search engine, so never put secrets or private code in it.",
		promptSnippet: "Search the web",
		promptGuidelines: [
			"web_search is the one tool that reaches the internet: use it for facts that may be newer than your training or are not in these files.",
		],
		annotations: { readOnlyHint: true, openWorldHint: true },
		executionMode: "sequential",   // one search at a time: a burst of them trips the engine's bot check
		parameters: {
			type: "object",
			properties: { query: { type: "string", description: "What to search for, as you would type it into a search engine" } },
			required: ["query"],
		},
		async execute(_id: string, { query }: { query: string }, signal?: AbortSignal) {
			if (!ENDPOINT) {
				throw new Error(
					`web_search is off: JOCAL_WEB_SEARCH_URL is ${URL_SETTING ? `'${URL_SETTING}'` : "unset"}, not a URL. ` +
						"This extension takes its search engine from `jocal pi`, which sets it when WEB_SEARCH is on.",
				);
			}
			const q = (query ?? "").trim();
			if (!q) throw new Error("web_search needs a query.");
			const found = await search(ENDPOINT, q, signal);
			if (found.length === 0) return { content: [{ type: "text", text: `No results for "${q}".` }], details: undefined };
			const lines = found.map((r, i) => `${i + 1}. ${r.title}\n   ${r.url}${r.snippet ? `\n   ${r.snippet}` : ""}`);
			return { content: [{ type: "text", text: `Results for "${q}" (${ENDPOINT.host}):\n\n${lines.join("\n\n")}` }], details: undefined };
		},
	});
}
