"""Live check of bcuse's desktop surface against cua-J's isolated AppKit test app.

Needs CuaDriver.app permissions (`cua-driver permissions grant`). Clicks only inside the test app.
Usage: uv run python scripts/probe_desktop.py [--app PATH]
Exit 0 only if every check holds; the app's own state file is the oracle.
"""

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from bcuse.desktop import DesktopSurface, DriverError, open_driver
from bcuse.model import ActionError

# Build it in a cua-J checkout next to this repository, or point CUA_APPKIT_APP at the .app bundle.
APP = Path(
	os.getenv('CUA_APPKIT_APP')
	or Path(__file__).resolve().parents[2]
	/ 'cua-J/libs/cua-driver/rust/test-apps/harness-appkit/CuaTestHarness.AppKit.app'
)


def check(name: str, ok: bool, **evidence) -> bool:
	print(json.dumps({'check': name, 'ok': ok, **evidence}, ensure_ascii=False, default=str), flush=True)
	return ok


async def main(app: Path) -> int:
	state_file = Path(tempfile.mkdtemp()) / 'state.json'
	proc = await asyncio.create_subprocess_exec(
		str(app / 'Contents/MacOS/CuaTestHarness.AppKit'),
		env={**os.environ, 'CUA_APPKIT_TASK_STATE': str(state_file)},
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)

	def app_state() -> dict:
		return json.loads(state_file.read_text() or '{}') if state_file.exists() else {}

	try:
		for _ in range(100):
			if app_state().get('pid') == proc.pid:
				break
			await asyncio.sleep(0.1)
		results = []
		async with open_driver(label='bcuse-probe') as driver:
			surface = await DesktopSurface.for_window(driver, proc.pid)
			first = await surface.observe()
			first_tokens = {i: e['element_token'] for i, e in surface._latest.items()}
			clicks, inputs = first.targets.get('click', {}), first.targets.get('input', {})
			increment = next(k for k, t in clicks.items() if '"Increment"' in t.description)
			note = next(k for k, t in inputs.items() if '"Note"' in t.description)
			results.append(check('observe', bool(clicks and inputs), click=len(clicks), input=len(inputs)))
			again = await surface.observe()
			results.append(check('unchanged window keeps fingerprint', again.fingerprint == first.fingerprint))
			await surface.execute('click', again.targets['click'][increment], None)
			await asyncio.sleep(0.5)
			results.append(check('click reached the app', app_state().get('counter') == 1, state=app_state()))
			# The counter is not in the accessibility tree, so the window looks unchanged; a checkbox is.
			unchanged = await surface.observe()
			results.append(check('invisible change keeps fingerprint', unchanged.fingerprint == first.fingerprint))
			agree = next(k for k, t in unchanged.targets['click'].items() if '"I agree"' in t.description)
			await surface.execute('click', unchanged.targets['click'][agree], None)
			await asyncio.sleep(0.5)
			after = await surface.observe()
			results.append(
				check(
					'visible change changes fingerprint',
					after.fingerprint != first.fingerprint and app_state().get('agreed') is True,
					description=after.targets['click'][agree].description,
				)
			)
			await surface.execute('input', after.targets['input'][note], 'bcuse probe')
			typed = await surface.observe()
			results.append(
				check('set_value reached the field', '"bcuse probe"' in typed.targets['input'][note].description)
			)
			# Tokens from the first snapshot: the driver must refuse them and the app must not change.
			for index, element in surface._latest.items():
				element['element_token'] = first_tokens[index]
			try:
				await surface.execute('click', typed.targets['click'][increment], None)
				refused = None
			except ActionError as error:
				refused = error.__cause__.code if isinstance(error.__cause__, DriverError) else repr(error)
			await asyncio.sleep(0.5)
			results.append(
				check(
					'stale token refused',
					refused == 'stale_element_token' and app_state().get('counter') == 1,
					code=refused,
				)
			)
			return 0 if all(results) else 1
	except (DriverError, ActionError, StopIteration) as error:
		check('probe', False, error=repr(error), detail=getattr(error, 'detail', ''))
		return 1
	finally:
		proc.terminate()


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--app', type=Path, default=APP)
	raise SystemExit(asyncio.run(main(parser.parse_args().app)))
