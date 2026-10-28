# bcuse-J

Read README.md before editing. The loop is: observe active surface -> policy picks one observed target -> observe again -> execute once.

- `bcuse/model.py` is the contract between surfaces and policies. Change it first, then every surface and policy.
- Both policies consume the request from `policy.build_request`. Do not give the LLM policy a different menu than the Decision policy.
- Targets must come from an observation. Never let a model emit selectors, coordinates, element tokens, or code.
- Never retry a browser or desktop mutation. Desktop actions use background delivery only.
- `bcuse/browser.py` calls private DecisionAgent helpers at the pinned browser-use commit. When you bump the pin, run tests/test_browser.py first.
- Tests must not call paid APIs, launch cua-driver, or inject host input. Use scripted models (`tests/scripted.py`) and recorded desktop fixtures.
- Keep credentials in the ignored `.env`. Do not create CLAUDE.md.

Checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.
