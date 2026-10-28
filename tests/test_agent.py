import json

import httpx
import pytest
from browser_use.decision import AzureMicrosoftDecisionClient
from scripted import Oracle, ScriptedLLM, azure_transport

from bcuse.agent import Agent
from bcuse.model import ActionError, Observation, Target
from bcuse.policy import DecisionPolicy, LLMPolicy, RetryTransport

ENDPOINT = 'https://example.cognitiveservices.azure.com'


class FakeSurface:
	"""An app with labelled buttons and one text field; state changes only through execute()."""

	def __init__(self, name, buttons=('Save', 'Cancel'), *, refuse=False, drift=False):
		self.name = name
		self.buttons = buttons
		self.refuse = refuse
		self.drift = drift
		self.observed = 0
		self.attempts = 0
		self.executed: list[tuple] = []
		self.field = ''

	async def observe(self):
		self.observed += 1
		targets = {
			'click': {str(i): Target(i, f'Button "{label}"') for i, label in enumerate(self.buttons, 1)},
			'input': {'9': Target(9, f'TextField "Note", value "{self.field}"')},
		}
		state = [self.executed, self.field, self.observed if self.drift else 0]
		return Observation(
			surface=self.name,
			targets=targets,
			operations={'wait': 'Wait one second'},
			context={'window': self.name},
			text=f'{self.name} window',
			fingerprint=json.dumps(state),
		)

	async def execute(self, operation, target, text):
		self.attempts += 1
		if self.refuse:
			raise ActionError('refused')
		self.executed.append((operation, target.ref if target else None, text))
		if operation == 'input':
			self.field = text


def decision(plan, text=None, failures=None):
	oracle = Oracle(plan)
	client = AzureMicrosoftDecisionClient(
		ENDPOINT, api_key='test', transport=RetryTransport(azure_transport(oracle, failures))
	)
	return DecisionPolicy(client, ScriptedLLM(text=text) if text else None), oracle


async def test_decision_moves_across_surfaces_and_verifies_independently():
	browser, desktop = FakeSurface('browser'), FakeSurface('desktop', ('Confirm', 'Quit'))
	policy, oracle = decision(
		[('input', None, None), ('switch_to_desktop', None, None), ('click', 'Confirm', None), ('DONE', None, None)],
		text='Ada',
	)
	result = await Agent('Write Ada, then confirm on the desktop', policy, [browser, desktop]).run(
		outcome_verifier=lambda: _true(desktop.executed == [('click', 1, None)] and browser.field == 'Ada')
	)
	assert (result.status, result.verified) == ('model_done', True)
	assert [(s.surface, s.operation, s.key) for s in result.steps] == [
		('browser', 'input', '9'),
		('browser', 'switch_to_desktop', None),
		('desktop', 'click', '1'),
		('desktop', 'DONE', None),
	]
	assert browser.executed == [('input', 9, 'Ada')]
	first, desktop_request = oracle.requests[0], oracle.requests[2]
	assert 'switch_to_desktop' in first['questions']['operation']['criteria']
	assert desktop_request['state']['surface'] == 'desktop'
	assert 'switch_to_browser' in desktop_request['questions']['operation']['criteria']


async def _true(value):
	return value


async def test_changed_state_after_choice_executes_nothing():
	surface = FakeSurface('browser', drift=True)
	policy, _ = decision([('click', 'Save', None)])
	result = await Agent('Save', policy, [surface]).run()
	assert result.status == 'stale_state' and surface.executed == [] and result.steps == []


async def test_refused_action_stops_without_retry():
	surface = FakeSurface('desktop', refuse=True)
	policy, oracle = decision([('click', 'Save', None), ('click', 'Save', None)])
	result = await Agent('Save', policy, [surface]).run()
	assert result.status == 'action_error' and surface.attempts == 1 and len(oracle.requests) == 1


async def test_input_is_not_offered_without_a_text_model():
	policy, oracle = decision([('BLOCKED', None, None)])
	result = await Agent('Type a note', policy, [FakeSurface('desktop')]).run()
	assert result.status == 'blocked'
	assert 'input' not in oracle.requests[0]['questions']['operation']['criteria']
	assert 'input_target' not in oracle.requests[0]['questions']


async def test_unobserved_target_answer_is_rejected_before_execution():
	surface = FakeSurface('browser')

	def handle(request):
		body = json.loads(request.content)
		criteria = body['questions']['click_target']['criteria']
		probabilities = {key: 1 / len(criteria) for key in criteria}
		bogus = {'type': 'choice', 'choice': '99', 'confidence': 0.9, 'probabilities': probabilities}
		operation = {'type': 'choice', 'choice': 'click', 'confidence': 0.9, 'probabilities': {}}
		ops = body['questions']['operation']['criteria']
		operation['probabilities'] = {k: (0.9 if k == 'click' else 0.1 / (len(ops) - 1)) for k in ops}
		return httpx.Response(200, json={'model': 'm', 'answers': {'operation': operation, 'click_target': bogus}})

	client = AzureMicrosoftDecisionClient(ENDPOINT, api_key='test', transport=httpx.MockTransport(handle))
	with pytest.raises(ValueError):
		await Agent('Save', DecisionPolicy(client), [surface]).run()
	assert surface.executed == []


async def test_overloaded_decision_is_retried_but_rate_limit_is_not():
	policy, oracle = decision([('BLOCKED', None, None)], failures=[503, 529])
	assert (await Agent('x', policy, [FakeSurface('browser')]).run()).status == 'blocked'
	policy, oracle = decision([('BLOCKED', None, None)], failures=[429])
	with pytest.raises(RuntimeError, match='rate limit'):
		await Agent('x', policy, [FakeSurface('browser')]).run()
	assert oracle.requests == []


async def test_llm_policy_types_its_own_text_and_needs_a_target():
	surface = FakeSurface('desktop')
	llm = ScriptedLLM([('input', None, 'hello'), ('click', 'Save', None), ('DONE', None, None)])
	result = await Agent('Write hello and save', LLMPolicy(llm), [surface]).run()
	assert result.status == 'model_done'
	assert surface.executed == [('input', 9, 'hello'), ('click', 1, None)]
	with pytest.raises(ValueError, match='No observed click target'):
		await Agent('Save', LLMPolicy(_NoTarget()), [FakeSurface('desktop')]).run()


class _NoTarget(ScriptedLLM):
	async def ainvoke(self, messages, output_format=None, **kwargs):
		from browser_use.llm.views import ChatInvokeCompletion

		return ChatInvokeCompletion(completion=output_format(operation='click', target=None), usage=None)


async def test_request_fits_28kb_with_huge_window_text():
	surface = FakeSurface('desktop')
	original = surface.observe

	async def huge():
		observation = await original()
		return Observation(**{**observation.__dict__, 'text': 'é' * 100_000})

	surface.observe = huge
	policy, oracle = decision([('BLOCKED', None, None)])
	await Agent('x', policy, [surface]).run()
	assert len(json.dumps(oracle.requests[0], ensure_ascii=False).encode()) <= 28000
	assert oracle.requests[0]['state']['text'].startswith('é')
