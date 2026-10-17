# jocal

**Run the [Pi coding agent](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) on a local LLM on your Mac, with one command. Prompts, files and answers stay on the machine.**

```
jocal pi
```

That starts Pi on Qwen3.5-4B served by [oMLX](https://github.com/jundot/omlx) on Apple Silicon. Nothing from your cloud setup is loaded: no API keys, no MCP servers, no global instructions, no skills. Plain `pi` keeps using your cloud model.

*jocal* is short for "Jo's local". **Status: alpha (v0.1).** Tested on a 16 GB M4 Mac with oMLX 0.7.0, Pi 1.3.0 and Claude Code 2.1.302.

## Quickstart

macOS on Apple Silicon, 16 GB RAM or more, [uv](https://docs.astral.sh/uv/) and Node.

```sh
git clone https://github.com/ccomkhj/jocal && cd jocal
./install.sh        # links jocal into ~/.local/bin
jocal doctor        # lists what's missing, with the command that installs each piece
jocal fetch         # downloads Qwen3.5-4B (~3 GB) at its pinned commit
jocal pi
```

`jocal doctor` will ask for oMLX (`uv tool install ...`), Pi (`npm install -g @earendil-works/pi-coding-agent`) and the `hf` CLI if they are missing.

## Commands

```
jocal pi [--9b] [pi args]              Pi on the local model (the 9B is opt-in)
jocal claude [--9b] [claude args]      Claude Code on the local model (experimental)
jocal summarise <file> "<question>"    answer a question about a long document or PDF (map-reduce)
jocal status                           runtime, loaded models, sessions, disk budget, version drift
jocal doctor | fetch [--9b]            check the setup / download a model
jocal up | down [--force]              start or stop oMLX by hand
```

Add `--explain` to `jocal pi` or `jocal claude` to print every env var, flag and generated file the session would use, without starting anything. Arguments after the jocal ones go to the harness unchanged (`jocal pi -p "hi"`).

## What it does

- **Starts and stops the model for you.** oMLX starts when a session needs it and stops when the last session exits (`STOP_RUNTIME=manual` keeps it up). A 4B and a 9B session share one oMLX.
- **Keeps the cloud out.** Pi gets its own agent dir (`~/.jocal/pi`), `--no-skills`, `--no-prompt-templates`, no MCP, offline and telemetry off. Claude Code gets its own config dir, a dummy token, a pinned base URL that a repo's `.claude/settings.json` can't override, and no MCP servers.
- **Marks the session.** A banner and the terminal title say `JOCAL`, the model, and "prompts stay on this Mac".
- **Reads whole files, or refuses.** Pi's `read` is replaced by one that returns a file whole up to a cap sized to the window (~20K tokens at 32K) and refuses a bigger file with the exact `jocal summarise` command, instead of silently truncating.
- **Small instructions.** The project's `AGENTS.md`/`CLAUDE.md` loads as usual (with a warning when it's over ~1K tokens, since each 1K adds 3–5 s to a cold first reply), plus one short `~/.config/jocal/LOCAL.md` you own.

Measured on a 16 GB M4 with the 4B and a 32K window: first replies in 4–6 s in Pi, ~28 tok/s, 6.3 GB peak, and 0 outbound connections with the network cut.

## Config

The first run writes `~/.config/jocal/jocal.conf` (from [`jocal.conf`](jocal.conf)) and `~/.config/jocal/LOCAL.md`. Both are yours after that and never overwritten. The config holds the models, the window (`CTX`), RAM and disk budgets, version pins, and the allowlists:

- `PI_EXTRA_TOOLS`, `CLAUDE_EXTRA_TOOLS`: tools beyond read, edit, write and bash.
- `MCP_SERVERS`: names from `MCP_FILE` (Claude Code's `mcpServers` format). Only stdio servers and `localhost` URLs are accepted; anything else stops the session before it starts.
- `PI_BIN`, `OMLX_BIN`, `CLAUDE_BIN`, `HF_BIN`: binaries not on your PATH.

To use another model, add `<key>=<folder name>` to `MODELS` (the key needs a digit, like `14b`) and `<key>=<hf repo>@<commit>` to `PIN_MODELS`, then `jocal fetch --14b` and `jocal pi --14b`.

## Check it yourself

`netcut.sb` is a macOS sandbox profile that allows only loopback, so oMLX is reachable and nothing else is. A local session works fully under it:

```sh
sandbox-exec -f netcut.sb jocal pi -p "list the files here"    # works
sandbox-exec -f netcut.sb curl -sI https://example.com         # fails: the network is cut
```

## Upgrading

`jocal status` warns when oMLX, Pi, Claude Code or a model differs from its pin in the config. Before moving a pin, check in each harness that a session under `netcut.sb` makes 0 outbound attempts, and that the first reply in a fresh session stays under 60 s cold. Then update the pin.

## Known limits

- Small models are small: in our trial, Pi on the 4B finished 4 of 7 coding tasks (Claude Code 5 of 7).
- `jocal claude`: in Claude Code, a single read close to the cap can trigger auto-compaction. The first interactive run still shows Claude Code's onboarding and folder-trust prompts.
- `jocal summarise` does one reduce step, so documents over ~150 pages can overflow it.
- If the jocal wrapper is killed with `kill -9`, the harness keeps running, and oMLX stops only when the next session ends or on `jocal down`.

## Development

```sh
tests/run                                  # hermetic suite: fake pi, omlx, claude and hf; no network or model (~45 s)
git config core.hooksPath .githooks        # run shellcheck and the suite before each commit
```

## License

[MIT](LICENSE). Models and oMLX keep their own licenses (Qwen3.5: Apache-2.0).
