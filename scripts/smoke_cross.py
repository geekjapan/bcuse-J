"""One live task across a real Chromium page and cua-J's AppKit test app, with a scripted chooser (no paid calls).

Needs CuaDriver.app permissions. Exit 0 only if both apps' own state shows the work was done.
Usage: uv run python scripts/smoke_cross.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_use import BrowserProfile, BrowserSession

from bcuse.agent import Agent
from bcuse.browser import BrowserSurface
from bcuse.desktop import DesktopSurface, open_driver
from bcuse.policy import LLMPolicy

sys.path.insert(0, str(Path(__file__).parent.parent / 'tests'))
from scripted import ScriptedLLM

# Build it in a cua-J checkout next to this repository, or point CUA_APPKIT_APP at the .app bundle.
APP = Path(
	os.getenv('CUA_APPKIT_APP')
	or Path(__file__).resolve().parents[2]
	/ 'cua-J/libs/cua-driver/rust/test-apps/harness-appkit/CuaTestHarness.AppKit.app'
)
PAGE = (
	b'<!doctype html><title>Ticket</title><p>Ticket code: <b id=code>TK-4471</b></p>'
	b'<button onclick="document.title=\'copied\'">Mark copied</button>'
)


def serve() -> ThreadingHTTPServer:
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
	return server


PLAN = [
	('click', 'Mark copied', None),
	('switch_to_desktop', None, None),
	('input', '"Note"', 'TK-4471'),
	('click', '"Save note"', None),
	('click', '"I agree"', None),
	('DONE', None, None),
]


async def main() -> int:
	state_file = Path(tempfile.mkdtemp()) / 'state.json'
	app = await asyncio.create_subprocess_exec(
		str(APP / 'Contents/MacOS/CuaTestHarness.AppKit'),
		env={**os.environ, 'CUA_APPKIT_TASK_STATE': str(state_file)},
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)

	def app_state() -> dict:
		return json.loads(state_file.read_text() or '{}') if state_file.exists() else {}

	server = serve()
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	try:
		for _ in range(100):
			if app_state().get('pid') == app.pid:
				break
			await asyncio.sleep(0.1)
		await session.start()
		await (await session.get_current_page()).goto(f'http://127.0.0.1:{server.server_address[1]}/')
		async with open_driver() as driver:
			desktop = await DesktopSurface.for_window(driver, app.pid)
			task = 'Mark the ticket as copied, then save its code as the note in the desktop app and agree.'

			async def verify() -> bool:
				title = await (await session.get_current_page()).evaluate('() => document.title')
				state = app_state()
				print(json.dumps({'browser_title': title, 'app_state': state}), flush=True)
				return title == 'copied' and state.get('note_saved') == 'TK-4471' and state.get('agreed') is True

			result = await Agent(
				task, LLMPolicy(ScriptedLLM(list(PLAN))), [BrowserSurface(session, task), desktop]
			).run(max_steps=10, outcome_verifier=verify)
		print(
			json.dumps(
				{'status': result.status, 'verified': result.verified, 'steps': [s.__dict__ for s in result.steps]}
			)
		)
		return 0 if result.status == 'model_done' and result.verified else 1
	finally:
		await session.kill()
		server.shutdown()
		app.terminate()


if __name__ == '__main__':
	raise SystemExit(asyncio.run(main()))
