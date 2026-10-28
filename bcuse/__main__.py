"""Run one task on a browser page, a desktop window, or both.

bcuse --task '...' [--url URL] [--desktop-pid PID] --policy azure|openai|llm|generative
"""

import argparse
import asyncio
import os
from contextlib import AsyncExitStack

from browser_use import Agent as GenerativeAgent
from browser_use import BrowserProfile, BrowserSession, ChatOpenAI
from browser_use.decision import AzureMicrosoftDecisionClient, OpenAIDecisionClient

from bcuse.agent import Agent
from bcuse.browser import BrowserSurface
from bcuse.desktop import DesktopSurface, open_driver
from bcuse.policy import DecisionPolicy, LLMPolicy, RetryTransport
from bcuse.tools import desktop_tools


def chat(model_var: str, prefix: str) -> ChatOpenAI:
	"""An OpenAI-compatible chat model from <model_var>, <prefix>_API_KEY and optional <prefix>_BASE_URL."""
	model = os.getenv(model_var)
	if not model:
		raise SystemExit(f'Set {model_var} (and {prefix}_API_KEY, optional {prefix}_BASE_URL).')
	api_key, base_url = os.getenv(f'{prefix}_API_KEY') or None, os.getenv(f'{prefix}_BASE_URL') or None
	if base_url and not api_key:
		# Without this, the OpenAI SDK would send OPENAI_API_KEY to a third-party endpoint.
		raise SystemExit(f'Set {prefix}_API_KEY for {prefix}_BASE_URL.')
	return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)


def policy(name: str):
	if name == 'llm':
		return LLMPolicy(chat('LLM_MODEL', 'LLM'))
	text = chat('TEXT_MODEL', 'TEXT_MODEL') if os.getenv('TEXT_MODEL') else None
	if name == 'azure':
		return DecisionPolicy(AzureMicrosoftDecisionClient(transport=RetryTransport()), text)
	return DecisionPolicy(OpenAIDecisionClient(transport=RetryTransport()), text)


async def main(args: argparse.Namespace) -> int:
	if not args.url and args.desktop_pid is None:
		raise SystemExit('Pass --url, --desktop-pid, or both.')
	async with AsyncExitStack() as stack:
		session = desktop = None
		if args.url:
			session = BrowserSession(browser_profile=BrowserProfile(headless=args.headless, user_data_dir=None))
			await session.start()
			stack.push_async_callback(session.kill)
			await (await session.get_current_page()).goto(args.url)
		if args.desktop_pid is not None:
			driver = await stack.enter_async_context(open_driver())
			desktop = await DesktopSurface.for_window(driver, args.desktop_pid, args.desktop_title)
		if args.policy == 'generative':
			tools = desktop_tools(desktop) if desktop else None
			history = await GenerativeAgent(
				args.task, llm=chat('LLM_MODEL', 'LLM'), browser_session=session, tools=tools
			).run(max_steps=args.max_steps)
			print({'done': history.is_done(), 'successful': history.is_successful(), 'result': history.final_result()})
			return 0 if history.is_done() else 1
		surfaces = [s for s in (BrowserSurface(session, args.task) if session else None, desktop) if s]
		result = await Agent(args.task, policy(args.policy), surfaces).run(max_steps=args.max_steps)
		print(result)
		# DONE is the model's claim; check the real page or app before trusting it.
		return 0 if result.status == 'model_done' else 1


def cli() -> None:
	parser = argparse.ArgumentParser(prog='bcuse')
	parser.add_argument('--task', required=True)
	parser.add_argument('--url')
	parser.add_argument('--desktop-pid', type=int)
	parser.add_argument('--desktop-title')
	parser.add_argument('--policy', choices=['azure', 'openai', 'llm', 'generative'], default='azure')
	parser.add_argument('--max-steps', type=int, default=20)
	parser.add_argument('--headless', action='store_true')
	raise SystemExit(asyncio.run(main(parser.parse_args())))


if __name__ == '__main__':
	cli()
