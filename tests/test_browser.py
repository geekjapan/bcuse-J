"""Real headless Chromium through browser-use, with scripted models over the real Decision wire formats."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from browser_use import BrowserProfile, BrowserSession
from browser_use.decision import AzureMicrosoftDecisionClient, OpenAIDecisionClient
from scripted import Oracle, ScriptedLLM, azure_transport, openai_transport
from test_agent import FakeSurface

from bcuse.agent import Agent
from bcuse.browser import BrowserSurface
from bcuse.policy import DecisionPolicy, LLMPolicy, RetryTransport

PAGE = b"""<!doctype html><html><head><title>Order form</title></head><body>
<label for=name>Name</label><input id=name name=name>
<label for=color>Color</label>
<select id=color><option value="">Pick one</option><option value=red>Red</option><option value=blue>Blue</option></select>
<button id=save onclick="document.getElementById('saved').textContent=document.getElementById('name').value+'/'+document.getElementById('color').value">Save</button>
<p id=saved></p></body></html>"""

PLAN = [
	('input', 'Name', 'Ada'),
	('select', "label='Blue'", None),
	('click', 'Save', None),
	('switch_to_desktop', None, None),
	('click', 'Confirm', None),
	('DONE', None, None),
]


@pytest.fixture
def url():
	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			self.send_response(200)
			self.send_header('Content-Type', 'text/html')
			self.end_headers()
			self.wfile.write(PAGE)

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f'http://127.0.0.1:{server.server_address[1]}/'
	server.shutdown()


@pytest.fixture
async def session(url):
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	page = await session.get_current_page()
	await page.goto(url)
	yield session
	await session.kill()


def policies():
	azure, openai = Oracle(list(PLAN)), Oracle(list(PLAN))
	return [
		(
			DecisionPolicy(
				AzureMicrosoftDecisionClient(
					'https://example.cognitiveservices.azure.com',
					api_key='test',
					transport=RetryTransport(azure_transport(azure)),
				),
				ScriptedLLM(text='Ada'),
			),
			azure,
		),
		(
			DecisionPolicy(
				OpenAIDecisionClient(api_key='test', transport=openai_transport(openai)), ScriptedLLM(text='Ada')
			),
			openai,
		),
		(LLMPolicy(ScriptedLLM(list(PLAN))), None),
	]


@pytest.mark.parametrize('which', ['azure', 'openai', 'llm'])
async def test_one_task_across_browser_and_desktop(session, which):
	policy, oracle = policies()[['azure', 'openai', 'llm'].index(which)]
	desktop = FakeSurface('desktop', ('Confirm', 'Quit'))
	task = 'Enter Ada as name, choose Blue, save, then confirm on the desktop.'

	async def verify():
		page = await session.get_current_page()
		saved = await page.evaluate("() => document.getElementById('saved').textContent")
		return saved == 'Ada/blue' and desktop.executed == [('click', 1, None)]

	result = await Agent(task, policy, [BrowserSurface(session, task), desktop]).run(
		max_steps=10, outcome_verifier=verify
	)

	assert (result.status, result.verified) == ('model_done', True), result
	assert [s.operation for s in result.steps] == [op for op, _, _ in PLAN]
	if oracle:
		assert len(oracle.requests) == len(PLAN)
		first = oracle.requests[0]
		state = first['state'] if 'state' in first else json.loads(first['input'])
		assert state['surface'] == 'browser' and state['url'].startswith('http://127.0.0.1')


class StepLLM:
	"""A BaseChatModel that replays browser-use AgentOutput JSON, one action per step."""

	model = name = 'step-llm'
	provider = 'test'
	model_name = 'step-llm'
	_verified_api_keys = True

	def __init__(self, actions):
		self.actions = list(actions)

	async def ainvoke(self, messages, output_format=None, **kwargs):
		from browser_use.llm.views import ChatInvokeCompletion

		step = {
			'thinking': None,
			'evaluation_previous_goal': '',
			'memory': '',
			'next_goal': '',
			'action': [self.actions.pop(0)],
		}
		return ChatInvokeCompletion(completion=output_format.model_validate_json(json.dumps(step)), usage=None)


async def test_generative_agent_drives_desktop_through_tools(session):
	from browser_use import Agent as GenerativeAgent

	from bcuse.tools import desktop_tools

	desktop = FakeSurface('desktop', ('Confirm', 'Quit'))
	llm = StepLLM(
		[
			{'desktop_state': {}},
			{'desktop_click': {'key': '1'}},
			{'done': {'text': 'confirmed', 'success': True}},
		]
	)
	agent = GenerativeAgent('Confirm on the desktop', llm=llm, browser_session=session, tools=desktop_tools(desktop))
	history = await agent.run(max_steps=5)
	assert history.is_done() and desktop.executed == [('click', 1, None)]
