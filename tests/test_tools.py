from test_desktop import FakeDriver, load

from bcuse.desktop import DesktopSurface
from bcuse.tools import STALE, desktop_tools


def setup():
	driver = FakeDriver(load('appkit-window-state-initial-v1.json'))
	tools = desktop_tools(DesktopSurface(driver, 20535, 71364))  # type: ignore[arg-type]
	return driver, tools


async def run(tools, name: str, params: dict | None = None):
	return await tools.registry.execute_action(name, params or {})


async def test_state_lists_keys():
	_, tools = setup()
	result = await run(tools, 'desktop_state')
	assert '[1] Button "Increment"' in result.extracted_content
	assert '[21] TextField "Note"' in result.extracted_content


async def test_click_without_state_is_refused():
	driver, tools = setup()
	result = await run(tools, 'desktop_click', {'key': '1'})
	assert result.error == STALE
	assert driver.actions() == []


async def test_click_after_window_changed_is_refused():
	driver, tools = setup()
	await run(tools, 'desktop_state')
	next(e for e in driver.state['elements'] if e['element_index'] == 21)['value'] = 'changed'
	result = await run(tools, 'desktop_click', {'key': '1'})
	assert result.error == STALE
	assert driver.actions() == []


async def test_click_unchanged_acts_once_then_requires_new_state():
	driver, tools = setup()
	await run(tools, 'desktop_state')
	assert (await run(tools, 'desktop_click', {'key': '1'})).error is None
	assert len(driver.actions()) == 1
	assert (await run(tools, 'desktop_click', {'key': '1'})).error == STALE
	assert len(driver.actions()) == 1


async def test_unknown_key_and_wrong_operation_refused():
	driver, tools = setup()
	await run(tools, 'desktop_state')
	assert (await run(tools, 'desktop_click', {'key': '999'})).error
	assert (await run(tools, 'desktop_input', {'key': '1', 'text': 'x'})).error  # a button, not an input
	assert driver.actions() == []


async def test_input_sets_value_and_refusal_is_error():
	driver, tools = setup()
	await run(tools, 'desktop_state')
	assert (await run(tools, 'desktop_input', {'key': '21', 'text': 'hi'})).error is None
	assert driver.actions()[0][0] == 'set_value'
	driver.refuse = True
	await run(tools, 'desktop_state')
	assert 'refused' in (await run(tools, 'desktop_click', {'key': '1'})).error
