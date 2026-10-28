"""browser-use actions that let a generative Agent drive one desktop window.

The LLM must call desktop_state first; desktop_click/desktop_input act only when the window still matches what
that call showed, and only on keys of that observation.
"""

from browser_use import Tools
from browser_use.agent.views import ActionResult

from bcuse.desktop import DesktopSurface
from bcuse.model import ActionError

STATE_LIMIT = 8000
STALE = 'Desktop changed since desktop_state; call desktop_state again.'


def desktop_tools(surface: DesktopSurface, tools: Tools | None = None) -> Tools:
	tools = tools or Tools()
	seen: list[str] = []  # fingerprint of the last desktop_state, cleared after every action

	@tools.registry.action('Read the desktop window: clickable and typeable elements by key, plus its text.')
	async def desktop_state() -> ActionResult:
		observation = await surface.observe()
		seen[:] = [observation.fingerprint]
		lines = [
			f'[{key}] {target.description} ({operation})'
			for operation, table in observation.targets.items()
			for key, target in table.items()
		]
		content = '\n'.join([*lines, f'context: {dict(observation.context)}', observation.text])
		return ActionResult(extracted_content=content[:STATE_LIMIT])

	async def act(operation: str, key: str, text: str | None) -> ActionResult:
		observation = await surface.observe()
		if seen != [observation.fingerprint]:
			return ActionResult(error=STALE)
		target = observation.targets.get(operation, {}).get(key)
		if target is None:
			return ActionResult(error=f'No desktop {operation} target with key {key!r}; call desktop_state.')
		seen.clear()
		try:
			await surface.execute(operation, target, text)
		except ActionError as error:
			return ActionResult(error=str(error))
		return ActionResult(
			extracted_content=f'Desktop {operation} on [{key}] done; call desktop_state to see the result.'
		)

	@tools.registry.action('Click the desktop element with this key from desktop_state.')
	async def desktop_click(key: str) -> ActionResult:
		return await act('click', key, None)

	@tools.registry.action('Type text into the desktop input element with this key from desktop_state.')
	async def desktop_input(key: str, text: str) -> ActionResult:
		return await act('input', key, text)

	return tools
