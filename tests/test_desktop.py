import copy
import json
from pathlib import Path

import pytest

from bcuse.desktop import DesktopSurface, DriverError
from bcuse.model import ActionError

FIXTURES = Path(__file__).parent / 'fixtures'


def load(name: str) -> dict:
	return json.loads((FIXTURES / name).read_text())


def reissue_tokens(state: dict, snapshot: str) -> dict:
	state = copy.deepcopy(state)
	state['snapshot_id'] = snapshot
	for element in state['elements']:
		element['element_token'] = f'{snapshot}:{element["element_index"]}'
	return state


class FakeDriver:
	def __init__(self, state: dict, windows: list[dict] | None = None, refuse: bool = False) -> None:
		self.state = state
		self.windows = windows or []
		self.refuse = refuse
		self.calls: list[tuple[str, dict]] = []

	async def call(self, name: str, arguments: dict) -> dict:
		self.calls.append((name, arguments))
		if name == 'list_windows':
			return {'windows': self.windows}
		if name == 'get_window_state':
			return self.state
		if self.refuse:
			raise DriverError(f'{name} refused (background_blocked)', 'background_blocked', refused=True)
		return {'status': 'ok'}

	def actions(self) -> list[tuple[str, dict]]:
		return [c for c in self.calls if c[0] in ('click', 'set_value')]


def surface_for(driver: FakeDriver) -> DesktopSurface:
	return DesktopSurface(driver, 20535, 71364)  # type: ignore[arg-type]


def key_of(observation, operation: str, label: str) -> str:
	return next(k for k, t in observation.targets[operation].items() if f'"{label}"' in t.description)


async def test_targets_from_real_fixture():
	observation = await surface_for(FakeDriver(load('appkit-window-state-initial-v1.json'))).observe()
	clicks, inputs = observation.targets['click'], observation.targets['input']
	for label in ('Increment', 'Reset', 'Save note'):
		assert clicks[key_of(observation, 'click', label)].ref == int(key_of(observation, 'click', label))
	assert clicks['1'].description == 'Button "Increment"'
	assert key_of(observation, 'input', 'Note') == '21'
	assert 'select' not in observation.targets
	# AXStaticText 'alpha' (index 7) is neither clickable nor typeable; an unlabelled AXPress button is still offered.
	assert '7' not in clicks and '7' not in inputs
	assert '10' in clicks and 'Button' in clicks['10'].description
	assert '12' in clicks and 'at (962.0, 440.0)' in clicks['12'].description
	assert observation.operations == {'wait': 'Wait one second'}
	assert observation.context == {'app': 'CuaTestHarness.AppKit', 'window': 'CuaTestHarness AppKit'}
	assert 'Button Increment' in observation.text
	# The Apple menu (index 29, under the AXMenuBar at 28) is reached through invoke_menu, not clicks.
	assert '28' not in clicks and '29' not in clicks


async def test_fingerprint_ignores_reissued_tokens_but_not_changes():
	initial = load('appkit-window-state-initial-v1.json')
	first = await surface_for(FakeDriver(initial)).observe()
	again = await surface_for(FakeDriver(reissue_tokens(initial, 's00000099'))).observe()
	assert first.fingerprint == again.fingerprint
	changed = reissue_tokens(initial, 's00000100')
	next(e for e in changed['elements'] if e['element_index'] == 21)['value'] = 'typed'
	assert (await surface_for(FakeDriver(changed)).observe()).fingerprint != first.fingerprint
	after = await surface_for(FakeDriver(load('appkit-window-state-after-actions-v1.json'))).observe()
	assert after.fingerprint != first.fingerprint


async def test_execute_uses_fresh_token_and_background_delivery():
	initial = load('appkit-window-state-initial-v1.json')
	driver = FakeDriver(initial)
	surface = surface_for(driver)
	await surface.observe()
	driver.state = reissue_tokens(initial, 's00000099')
	observation = await surface.observe()
	await surface.execute('click', observation.targets['click']['1'], None)
	await surface.execute('input', observation.targets['input']['21'], 'hello')
	assert driver.actions() == [
		('click', {'pid': 20535, 'window_id': 71364, 'element_token': 's00000099:1', 'delivery_mode': 'background'}),
		('set_value', {'pid': 20535, 'window_id': 71364, 'element_token': 's00000099:21', 'value': 'hello'}),
	]


async def test_refused_click_raises_once_without_retry():
	driver = FakeDriver(load('appkit-window-state-initial-v1.json'), refuse=True)
	surface = surface_for(driver)
	observation = await surface.observe()
	with pytest.raises(ActionError, match='background_blocked'):
		await surface.execute('click', observation.targets['click']['1'], None)
	assert [c[0] for c in driver.calls].count('click') == 1
	assert all(c[1].get('delivery_mode') in (None, 'background') for c in driver.calls)


async def test_unknown_operation_is_rejected():
	with pytest.raises(ValueError):
		await surface_for(FakeDriver(load('appkit-window-state-initial-v1.json'))).execute('scroll', None, None)


async def test_secret_fields_are_never_offered():
	state = load('appkit-window-state-initial-v1.json')
	state['elements'] += [
		{
			'element_index': 200,
			'element_token': 't:200',
			'role': 'AXTextField',
			'subrole': 'AXSecureTextField',
			'label': 'Pin',
			'value': 'hunter2',
			'actions': ['AXConfirm'],
		},
		{
			'element_index': 201,
			'element_token': 't:201',
			'role': 'AXTextField',
			'label': 'Account Password',
			'value': 'hunter2',
			'actions': [],
		},
		{
			'element_index': 202,
			'element_token': 't:202',
			'role': 'AXTextField',
			'label': 'Search',
			'enabled': False,
			'actions': [],
		},
		{
			'element_index': 203,
			'element_token': 't:203',
			'role': 'AXButton',
			'label': 'Discard',
			'actions': ['AXPress'],
		},
	]
	observation = await surface_for(FakeDriver(state)).observe()
	assert not {'200', '201', '202'} & set(observation.targets['input'])
	assert 'hunter2' not in observation.text
	# Secret words gate typing, not clicking: "Discard" contains "card" but is an ordinary button.
	assert '203' in observation.targets['click']


async def test_descriptions_fit_the_decision_budget():
	from bcuse.policy import build_request

	state = load('appkit-window-state-initial-v1.json')
	state['elements'] += [
		{
			'element_index': 1000 + i,
			'element_token': f't:{i}',
			'role': 'AXButton',
			'label': f'項目 {i} ' + 'あ' * 150,
			'actions': ['AXPress'],
		}
		for i in range(400)
	]
	observation = await surface_for(FakeDriver(state)).observe()
	assert sum(len(t.description.encode()) for table in observation.targets.values() for t in table.values()) <= 12000
	request = build_request('タスク' * 1300, observation, {}, [], can_type=True, model='decision-1')
	assert len(request.model_dump_json().encode()) <= 28000


async def test_for_window_picks_match_and_rejects_ambiguity():
	windows = [
		{'window_id': 1, 'title': 'Editor', 'is_on_screen': True},
		{'window_id': 2, 'title': 'Settings', 'is_on_screen': True},
		{'window_id': 3, 'title': 'Hidden', 'is_on_screen': False},
	]
	driver = FakeDriver({}, windows)
	assert (await DesktopSurface.for_window(driver, 7, 'Settings')).window_id == 2  # type: ignore[arg-type]
	with pytest.raises(ValueError):
		await DesktopSurface.for_window(driver, 7)  # type: ignore[arg-type]
	with pytest.raises(ValueError):
		await DesktopSurface.for_window(driver, 7, 'Missing')  # type: ignore[arg-type]
	assert (await DesktopSurface.for_window(FakeDriver({}, windows[2:] + windows[:1]), 7)).window_id == 1  # type: ignore[arg-type]


async def test_older_driver_without_full_output_is_read_once_more():
	class OldDriver(FakeDriver):
		async def call(self, name, arguments):
			if name == 'get_window_state' and 'full_output' in arguments:
				self.calls.append((name, arguments))
				raise DriverError('get_window_state failed', detail='unknown argument full_output')
			return await super().call(name, arguments)

	driver = OldDriver(load('appkit-window-state-initial-v1.json'))
	surface = surface_for(driver)
	assert '1' in (await surface.observe()).targets['click']
	await surface.observe()
	reads = [args for name, args in driver.calls if name == 'get_window_state']
	assert ['full_output' in args for args in reads] == [True, False, False]


async def test_other_observe_errors_are_not_retried():
	class BrokenDriver(FakeDriver):
		async def call(self, name, arguments):
			self.calls.append((name, arguments))
			raise DriverError('get_window_state failed', detail='window gone')

	driver = BrokenDriver({})
	with pytest.raises(DriverError):
		await surface_for(driver).observe()
	assert len(driver.calls) == 1
