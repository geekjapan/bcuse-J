"""Scripted stand-ins for paid models: they answer from a fixed plan, over the real wire formats."""

import json
from dataclasses import dataclass, field

import httpx
from browser_use.llm.views import ChatInvokeCompletion

Plan = list[tuple[str, str | None, str | None]]
"""(operation, substring of the wanted target description or None, text for input)"""


def pick(criteria: dict[str, str], needle: str) -> str:
	matches = [key for key, description in criteria.items() if needle in description]
	assert len(matches) == 1, f'{needle!r} matched {matches} in {criteria}'
	return matches[0]


def choice(criteria: dict[str, str], chosen: str) -> dict:
	rest = (0.1 / (len(criteria) - 1)) if len(criteria) > 1 else 0
	probabilities = {key: (0.9 if key == chosen else rest) for key in criteria}
	return {'type': 'choice', 'choice': chosen, 'confidence': 0.9, 'probabilities': probabilities}


@dataclass
class Oracle:
	plan: Plan
	requests: list[dict] = field(default_factory=list)

	def answers(self, questions: dict[str, dict[str, str]]) -> dict[str, dict]:
		"""questions: name -> criteria. Returns name -> Azure-shaped choice."""
		operation, needle, _ = self.plan.pop(0)
		answers = {'operation': choice(questions['operation'], operation)}
		head = operation + '_target'
		if head in questions:
			answers[head] = choice(questions[head], pick(questions[head], needle))
		return answers


def azure_transport(oracle: Oracle, failures: list[int] | None = None) -> httpx.MockTransport:
	failures = list(failures or [])

	def handle(request: httpx.Request) -> httpx.Response:
		if failures:
			return httpx.Response(failures.pop(0))
		body = json.loads(request.content)
		oracle.requests.append(body)
		answers = oracle.answers({name: q['criteria'] for name, q in body['questions'].items()})
		return httpx.Response(200, json={'model': body['model'], 'answers': answers})

	return httpx.MockTransport(handle)


def openai_transport(oracle: Oracle) -> httpx.MockTransport:
	def handle(request: httpx.Request) -> httpx.Response:
		body = json.loads(request.content)
		oracle.requests.append(body)
		questions = {q['name']: {c['value']: c['description'] for c in q['choices']} for q in body['questions']}
		answers = [
			{
				'name': name,
				'type': 'choice',
				'choice': a['choice'],
				'confidence': a['confidence'],
				'probabilities': [{'value': k, 'probability': p} for k, p in a['probabilities'].items()],
			}
			for name, a in oracle.answers(questions).items()
		]
		return httpx.Response(200, json={'model': body['model'], 'answers': answers})

	return httpx.MockTransport(handle)


class ScriptedLLM:
	"""A BaseChatModel that answers menu prompts from a plan and text prompts with fixed text."""

	model = 'scripted'
	provider = 'test'
	name = 'scripted'
	_verified_api_keys = True

	def __init__(self, plan: Plan | None = None, text: str = ''):
		self.plan = plan or []
		self.text = text
		self.prompts: list[dict] = []

	async def ainvoke(self, messages, output_format=None, **kwargs):
		prompt = json.loads(messages[-1].content)
		self.prompts.append(prompt)
		if 'questions' not in prompt:
			return ChatInvokeCompletion(completion=output_format(text=self.text), usage=None)
		operation, needle, text = self.plan.pop(0)
		head = prompt['questions'].get(operation + '_target')
		target = pick(head['criteria'], needle) if head else None
		return ChatInvokeCompletion(completion=output_format(operation=operation, target=target, text=text), usage=None)
