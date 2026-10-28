# bcuse-J

One agent loop for a browser page and a native desktop window. A finite-choice
Decision model (Azure Microsoft Decision 1 or OpenAI Decisions) or an LLM chooses
each action from the same table of observed targets.

## Choose the right tool

| What the task operates | Use |
| --- | --- |
| Web pages only | [browser-use](https://github.com/geekjapan/browser-use) `Agent` (LLM) or `DecisionAgent` (Decision), or [jev-ultrafast](https://github.com/geekjapan/jev-ultrafast) for the fastest Decision loop |
| Native app windows only | [cua-J](https://github.com/geekjapan/cua-J) and Cua Driver |
| A web page and a native window in one task | bcuse-J |

bcuse-J adds value only in the last row. It depends on the geekjapan browser-use
fork (pinned commit `76e5847`) and the installed `cua-driver` binary. It copies
neither project.

## Policies

| `--policy` | Who chooses | Text for input fields |
| --- | --- | --- |
| `azure` | Microsoft Decision 1 | Optional text helper (`TEXT_MODEL`) |
| `openai` | OpenAI Decisions | Optional text helper (`TEXT_MODEL`) |
| `llm` | Any OpenAI-compatible chat model, choosing from the same menu | The same model, in the same reply |
| `generative` | browser-use's standard `Agent`, with desktop actions added as tools | The same model |

The first three share one loop and one set of guards, so you can compare them
on the same task by changing one flag. `generative` keeps browser-use's full
feature set (navigation, extraction, tabs). Its desktop actions have the same
freshness check.

## Install

bcuse has two parts. You can install either one, or both.

- **The module** gives you the `bcuse` command and the `bcuse` Python package. Install it to run tasks yourself
  or to call bcuse from your own code.
- **The agent skill** teaches a coding agent (Claude Code, Codex, Cursor, and others) when and how to run bcuse.
  The skill runs the module through `uvx`, so it needs the same prerequisites and credentials.

### Step 1. Install the prerequisites

| Requirement | Needed for | How to install |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Everything | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.12 or later | Everything | `uv python install 3.12` |
| Google Chrome or Chromium | Browser tasks | Install Chrome normally |
| Cua Driver (macOS) | Desktop tasks | `/bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"` |
| Node.js | The agent skill only | Needed for `npx` |

For desktop tasks, give CuaDriver.app the macOS Accessibility and Screen Recording permissions once:

```bash
cua-driver permissions grant    # opens the macOS permission dialogs
cua-driver permissions status   # both should show "granted"
```

### Step 2. Install the module

Pick the row that matches what you want to do.

| You want to | Install command | Then |
| --- | --- | --- |
| Try bcuse without installing it | Nothing to install | `uvx --from git+https://github.com/geekjapan/bcuse-J bcuse --help` |
| Get a `bcuse` command on your PATH | `uv tool install git+https://github.com/geekjapan/bcuse-J` | `bcuse --help` |
| Use bcuse as a library in your project | `uv add git+https://github.com/geekjapan/bcuse-J` | `from bcuse.agent import Agent` |
| Change bcuse itself | `git clone https://github.com/geekjapan/bcuse-J && cd bcuse-J && uv sync` | `uv run pytest` |

### Step 3. Set your credentials

Copy the template and fill in only the policies you use:

```bash
curl -fsSL https://raw.githubusercontent.com/geekjapan/bcuse-J/main/.env.example -o .env
```

| Policy | Variables |
| --- | --- |
| `azure` | `AZURE_ENDPOINT`, and `AZURE_API_KEY` or `AZURE_ENTRA_TOKEN` |
| `openai` | `OPENAI_API_KEY` |
| `llm`, `generative` | `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL` for a non-OpenAI endpoint |
| Text for `azure` and `openai` | `TEXT_MODEL`, `TEXT_MODEL_API_KEY`, and optionally `TEXT_MODEL_BASE_URL` |

Without the text variables, the Decision policies cannot type into fields. Keep `.env` out of version control.
Load it with `--env-file .env` for `uvx` and `uv run`. For an installed `bcuse` command, export the variables
first, for example with `set -a; source .env; set +a`.

### Step 4. Install the agent skill

```bash
npx skills add geekjapan/bcuse-J
```

The command asks which agents to install for, and whether to install for this project or for your user. To skip
the questions, name them. For example, this installs for Claude Code at the user level, in
`~/.claude/skills/bcuse/SKILL.md`:

```bash
npx skills add geekjapan/bcuse-J -g -a claude-code -y
```

| Task | Command |
| --- | --- |
| See the skill before installing | `npx skills add geekjapan/bcuse-J --list` |
| Update it | `npx skills update bcuse` |
| Remove it | `npx skills remove bcuse` |

The skill tells the agent to check the prerequisites, read credentials only from the environment, and check the
real outcome before it reports success. It does not install Cua Driver, grant permissions, or create `.env`.
Complete steps 1 and 3 first.

## Run

These examples use the `bcuse` command from step 2. With `uvx`, replace `bcuse` with
`uvx --env-file .env --from git+https://github.com/geekjapan/bcuse-J bcuse`.

```bash
# Browser only, Azure Decision 1
bcuse --policy azure \
  --url https://example.com/form --task 'Enter Ada as name and save.'

# A browser page and a desktop window in one task, LLM chooser
bcuse --policy llm \
  --url https://example.com/order --desktop-pid "$(pgrep -x Orders | head -1)" --desktop-title 'Orders' \
  --task 'Copy the order number from the page into the Orders window and save.'
```

The exit code is 0 only when the model declared DONE. That is the model's claim.
Check the real page or app before you trust it.

## Use the library

```python
from bcuse.agent import Agent
from bcuse.browser import BrowserSurface
from bcuse.desktop import DesktopSurface, open_driver
from bcuse.policy import DecisionPolicy, LLMPolicy

async with open_driver() as driver:
	desktop = await DesktopSurface.for_window(driver, pid, 'Orders')
	agent = Agent(task, DecisionPolicy(decision_client, text_llm), [BrowserSurface(session, task), desktop])
	result = await agent.run(max_steps=20, outcome_verifier=check_the_real_outcome)
```

`result.status` is `model_done`, `blocked`, `max_steps`, `stale_state`, or
`action_error`. `result.verified` is set only by your `outcome_verifier`.

## How each step stays bounded

1. Observe the active surface. The browser surface uses browser-use's DOM
   targets. The desktop surface reads one window's accessibility tree through
   `cua-driver mcp`.
2. Offer only observed targets per operation (`click`, `input`, `select`), plus
   `scroll_*`, `wait`, `switch_to_<surface>`, `DONE`, and `BLOCKED`. The model
   never sends selectors, coordinates, tokens, or code.
3. Observe again. If the observation fingerprint changed, stop with
   `stale_state` and execute nothing.
4. Execute once. A failed action stops with `action_error` and is never retried.
   Desktop actions use background delivery only and never fall back to the
   foreground.

Fields recognized as password, token, or payment fields are not offered for
input, and their values are not shown to the model. Menu bar items are not
offered as desktop click targets. A Decision request stays under 28 KB, and page
or window text is truncated to fit. A Decision request is retried only on
HTTP 503 or 529, because a prediction has no side effects. A 429 stops at once.

## Limits

- One desktop window per run. No desktop scroll, menu, or keyboard shortcut operations.
- Desktop input uses `set_value` only. Some apps need typed keystrokes to fire their change handlers.
- The desktop fingerprint includes element frames, so moving the window between choice and action returns
  `stale_state`. A change that does not appear in the accessibility tree does not change the fingerprint.
- browser-use offers no targets on `data:` URLs. Serve test pages over HTTP.
- The loop policies cannot navigate. Start the browser on the right page, or use `generative`.
- The fingerprint check narrows the race between observation and action. It does not remove it.
- Browser actions run through browser-use's `Tools`, which have their own fallbacks. If typing into the chosen
  field fails, browser-use clicks that field and types into the focused element. If a checkbox click does not
  change its state, it clicks once more through JavaScript. It also logs typed text at INFO level. The upstream
  `DecisionAgent` shares this behaviour (`browser_use/browser/watchdogs/default_action_watchdog.py`).
- Desktop secret detection uses the role, the `AXSecureTextField` subrole when Cua Driver reports it, and words
  in the label. Cua Driver 0.30 does not appear to report element subroles. A macOS password field whose
  label has none of those words may then be offered for input. Do not run tasks near secret entry.

## Verify

```bash
uv run ruff check . && uv run pytest
```

The tests run offline and need no keys. They drive a real headless Chromium
through all three loop policies and the `generative` mode, using scripted models
over the real Azure and OpenAI wire formats. The desktop tests replay recorded
Cua Driver payloads from cua-J and never inject host input.
Two live scripts need CuaDriver.app permissions and make no paid calls. They act only inside cua-J's
isolated AppKit test app and a local page.

- `scripts/probe_desktop.py` checks the desktop surface against the real driver. It checks observation,
  fingerprints, click, `set_value`, and that the driver refuses a stale element token.
- `scripts/smoke_cross.py` runs one task across a real Chromium page and the test app with a scripted
  chooser. It checks the outcome in both apps' own state.

They expect the test app built in a [cua-J](https://github.com/geekjapan/cua-J) checkout next to this
repository (`libs/cua-driver/tests/fixtures/build/macos.sh --only appkit`), or `CUA_APPKIT_APP` set to the
`.app` bundle.

Both passed on macOS 27.0.1 with cua-driver 0.30.4. Runs against live Decision or LLM endpoints are not covered.

## License

MIT. See [LICENSE](LICENSE). The recorded desktop fixtures come from cua-J and keep their notices in
[tests/fixtures/README.md](tests/fixtures/README.md).
