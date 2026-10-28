"""Browser surface over browser-use's BrowserSession and native Tools.

Target extraction and the freshness fingerprint are browser-use's DecisionAgent
helpers at the pinned fork revision; tests/test_browser.py pins their behaviour.
"""

from browser_use import BrowserSession, Tools
from browser_use.decision import DecisionAgent

from bcuse.model import ActionError, Observation, Target


class _NoPrediction:
	async def predict(self, request):
		raise AssertionError('BrowserSurface never predicts')


class BrowserSurface:
	name = 'browser'

	def __init__(self, session: BrowserSession, task: str):
		self.session = session
		self._helper = DecisionAgent(task, _NoPrediction(), session)
		# The helper offers input targets only when a text model exists; the agent filters
		# them by policy instead, so mark one as present.
		self._helper.text_llm = object()  # type: ignore[assignment]
		self.tools = Tools()
		self._actions = self.tools.registry.create_action_model(
			include_actions=['click', 'input', 'select_dropdown', 'scroll', 'wait']
		)

	async def observe(self) -> Observation:
		state = await self.session.get_browser_state_summary(include_screenshot=False, cached=False)
		if state.state_error:
			raise RuntimeError(f'Browser state unavailable; nothing executed: {state.state_error}')
		targets = {
			operation: {key: Target(ref=t.index, description=t.description, option=t.text) for key, t in found.items()}
			for operation, found in self._helper._targets(state).items()
			if found
		}
		return Observation(
			surface='browser',
			targets=targets,
			operations={
				'scroll_down': 'Scroll down one page',
				'scroll_up': 'Scroll up one page',
				'wait': 'Wait one second',
			},
			context={'url': state.url[:2000], 'title': state.title[:500]},
			text=state.dom_state.llm_representation(),
			fingerprint=self._helper._fingerprint(state),
		)

	async def execute(self, operation: str, target: Target | None, text: str | None) -> None:
		if operation == 'click':
			action = {'click': {'index': target.ref}}
		elif operation == 'input':
			action = {'input': {'index': target.ref, 'text': text, 'clear': True}}
		elif operation == 'select':
			action = {'select_dropdown': {'index': target.ref, 'text': target.option}}
		elif operation in ('scroll_down', 'scroll_up'):
			action = {'scroll': {'down': operation == 'scroll_down', 'pages': 1}}
		elif operation == 'wait':
			# Native Tools.wait subtracts one second for the preceding model call.
			action = {'wait': {'seconds': 2}}
		else:
			raise ValueError(f'Unsupported browser operation {operation!r}')
		result = await self.tools.act(self._actions.model_validate(action), self.session)
		if result.error:
			raise ActionError(f'Browser {operation} failed: {result.error}')
