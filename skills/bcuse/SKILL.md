---
name: bcuse
description: Run one task that spans a web page and a native macOS app window with bcuse-J, choosing each action with a Decision model (Azure Microsoft Decision 1 or OpenAI Decisions) or an LLM. Use when a single task must act in both a browser and a desktop app. For web-only tasks use browser-use or jev-ultrafast; for desktop-only tasks use Cua Driver directly.
---

# bcuse

bcuse runs one bounded loop over a browser page, a desktop window, or both. Each step observes the active
surface, lets the policy pick one observed target, observes again, and acts once. Source and design:
https://github.com/geekjapan/bcuse-J

## Check prerequisites

1. `uv` is installed.
2. Google Chrome or Chromium is installed, for browser tasks.
3. For desktop tasks, `cua-driver` is installed and `cua-driver permissions status` shows Accessibility and
   Screen Recording as granted. If not, ask the user to run `cua-driver permissions grant`. Do not grant
   permissions yourself.
4. Credentials for the chosen policy are in the environment or an ignored `.env` file. Never write keys into
   commands, files you commit, or chat.

| Policy | Required variables |
| --- | --- |
| `azure` | `AZURE_ENDPOINT`, `AZURE_API_KEY` or `AZURE_ENTRA_TOKEN`, optional `AZURE_DEPLOYMENT_NAME` |
| `openai` | `OPENAI_API_KEY`, optional `OPENAI_DECISION_MODEL` |
| `llm`, `generative` | `LLM_MODEL`, `LLM_API_KEY`, optional `LLM_BASE_URL` (OpenAI-compatible) |

Decision policies type into fields only when a text helper is set: `TEXT_MODEL`, `TEXT_MODEL_API_KEY`, optional
`TEXT_MODEL_BASE_URL`. Without it, they cannot fill text fields.

## Run

```bash
uvx --env-file .env --from git+https://github.com/geekjapan/bcuse-J bcuse \
  --policy azure \
  --url 'https://example.com/order' \
  --desktop-pid "$(pgrep -x 'Orders' | head -1)" --desktop-title 'Orders' \
  --task 'Copy the order number from the page into the Orders window and save.'
```

- Pass `--url` for the browser, `--desktop-pid` for one desktop window, or both.
- Find the pid with `pgrep -x '<App name>'`. Add `--desktop-title` when the app has several windows.
- Add `--headless` to hide the browser.
- Choose `--policy`:
  - `azure` or `openai` for fast finite choices from observed targets.
  - `llm` to let a chat model choose from the same targets.
  - `generative` for browser-use's full agent (navigation, extraction, tabs) with desktop actions as tools.
- The loop policies cannot navigate. Start `--url` on the page where the work happens, or use `generative`.

## Read the result

The command prints the run result. It exits 0 only when the model declared DONE.

| Status | Meaning | Next step |
| --- | --- | --- |
| `model_done` | The model claims the task is done | Check the real page or app before reporting success |
| `blocked` | The model found no useful operation | Report it, or rephrase the task |
| `max_steps` | Step budget ran out | Raise `--max-steps` only if progress was visible |
| `stale_state` | The screen changed between choice and action; nothing executed | Run again |
| `action_error` | An action failed and may have partly happened | Inspect the page or app before running again |

Never report DONE as success without checking the outcome yourself.

## Limits

- Do not use bcuse to enter passwords, tokens, or payment data. Secret detection on macOS desktop fields relies
  partly on labels.
- One desktop window per run. No desktop scroll, menu, or keyboard shortcut operations.
- Live Decision and LLM runs cost money. Ask the user before running them repeatedly.
