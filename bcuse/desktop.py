"""Desktop surface: one native window driven through Cua Driver's MCP server.

Elements are offered as targets by their accessibility index. Execution always uses the element token from the
latest snapshot, in background delivery; a refusal is reported, never retried and never escalated to foreground.
"""

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bcuse.model import ActionError, Observation, Target

MAX_TARGETS = 250
DESCRIPTION_BUDGET = 12000
"""UTF-8 bytes of target descriptions, leaving room in the 28 KB Decision request for a 4000-character task."""
INPUT_ROLES = ('AXTextField', 'AXTextArea', 'AXComboBox', 'AXSearchField')
TOGGLE_ROLES = ('AXCheckBox', 'AXRadioButton')
# Same words as browser-use decision.py _secret_field.
SECRET_WORDS = ('password', 'secret', 'token', 'credit', 'card', 'cc-', 'otp', 'one-time', 'cvc', 'cvv')


class DriverError(RuntimeError):
	def __init__(self, message: str, code: str | None = None, refused: bool = False, detail: str = '') -> None:
		super().__init__(message)
		self.code = code
		self.refused = refused
		self.detail = detail
		"""The driver's error text. Kept out of the message, which can reach a model."""


class Driver:
	def __init__(self, session: ClientSession, label: str) -> None:
		self.session = session
		self.label = label

	async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
		result = await self.session.call_tool(name, {**arguments, 'session': self.label})
		data = result.structured_content
		fields = data if isinstance(data, dict) else {}
		refusal = fields.get('refusal')
		code = fields.get('code') or (refusal.get('code') if isinstance(refusal, dict) else None)
		code = code if isinstance(code, str) and code else None
		refused = fields.get('status') == 'refused' or bool(refusal)
		if result.is_error or refused:
			raise DriverError(
				f'{name} {"refused" if refused else "failed"}' + (f' ({code})' if code else ''),
				code,
				refused,
				' '.join(getattr(c, 'text', '') or '' for c in result.content),
			)
		if not isinstance(data, dict):
			raise DriverError(f'{name} returned no structured result')
		return data


@asynccontextmanager
async def open_driver(binary: str | None = None, label: str = 'bcuse') -> AsyncIterator[Driver]:
	params = StdioServerParameters(command=binary or os.getenv('CUA_DRIVER_BIN') or 'cua-driver', args=['mcp'])
	async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
		await session.initialize()
		# The daemon ends a session when its connection closes and refuses that label afterwards.
		yield Driver(session, f'{label}-{uuid.uuid4().hex[:12]}')


def _clip(value: object, limit: int = 160) -> str:
	text = ' '.join(str(value).split())
	return text if len(text) <= limit else text[:limit] + '…[truncated]'


def _is_secure(element: Mapping[str, Any]) -> bool:
	# macOS secure fields usually report role AXTextField with subrole AXSecureTextField.
	return 'AXSecureTextField' in (element.get('role'), element.get('subrole'))


def _is_secret(element: Mapping[str, Any]) -> bool:
	"""Fields whose value must never be typed by a model or shown to one."""
	if _is_secure(element):
		return True
	haystack = f'{element.get("role", "")} {element.get("label") or ""}'.lower()
	return any(word in haystack for word in SECRET_WORDS)


def _describe(element: Mapping[str, Any]) -> str:
	role = str(element['role']).removeprefix('AX')
	label = element.get('label')
	frame = element.get('frame')
	parts = [f'{role} "{_clip(label)}"' if label else role]
	if not label and isinstance(frame, dict):
		parts.append(f'at ({frame.get("x")}, {frame.get("y")})')
	value = element.get('value')
	if element['role'] in TOGGLE_ROLES:
		parts.append('checked' if str(value).lower() in ('1', 'true') else 'unchecked')
	elif value not in (None, '', label):
		parts.append(f'value "{_clip(value)}"')
	if element.get('selected') is True:
		parts.append('selected')
	return ', '.join(parts)


def _menu_bar(elements: Mapping[int, Mapping[str, Any]]) -> set[int]:
	"""Indexes inside the menu bar; menus belong to Cua's invoke_menu, not to click targets."""
	inside: set[int] = set()
	for index, element in elements.items():
		seen: set[int] = set()
		current: Mapping[str, Any] | None = element
		while current is not None and current['element_index'] not in seen:
			seen.add(current['element_index'])
			if current.get('role') == 'AXMenuBar':
				inside.add(index)
				break
			current = elements.get(current.get('parent_index', -1))
	return inside


def _text(elements: list[dict[str, Any]]) -> str:
	lines = []
	for element in elements:
		label, value = element.get('label'), element.get('value')
		if _is_secret(element):
			value = None
		if not label and value in (None, ''):
			continue
		line = f'{str(element["role"]).removeprefix("AX")} {_clip(label or "")}'.rstrip()
		if value not in (None, '', label):
			line += f' = {_clip(value)}'
		lines.append(line)
	return '\n'.join(lines)


class DesktopSurface:
	name = 'desktop'

	def __init__(self, driver: Driver, pid: int, window_id: int) -> None:
		self.driver = driver
		self.pid = pid
		self.window_id = window_id
		self._latest: dict[int, dict[str, Any]] = {}
		self._full_output = True

	@classmethod
	async def for_window(cls, driver: Driver, pid: int, title: str | None = None) -> 'DesktopSurface':
		windows = (await driver.call('list_windows', {'pid': pid})).get('windows', [])
		visible = [w for w in windows if w.get('is_on_screen') is not False]
		if title is not None:
			exact = [w for w in visible if w.get('title') == title]
			visible = exact or [w for w in visible if title.lower() in str(w.get('title') or '').lower()]
		if len(visible) != 1:
			raise ValueError(f'expected exactly one on-screen window for pid {pid}, found {len(visible)}')
		return cls(driver, pid, visible[0]['window_id'])

	async def observe(self) -> Observation:
		arguments = {
			'pid': self.pid,
			'window_id': self.window_id,
			'include_accessibility_tree': True,
			'include_screenshot': False,
		}
		try:
			# Drivers from 0.35 return elements only with full_output; older ones reject the argument.
			state = await self.driver.call(
				'get_window_state', {**arguments, 'full_output': True} if self._full_output else arguments
			)
		except DriverError as error:
			if not self._full_output or 'full_output' not in error.detail:
				raise
			self._full_output = False
			state = await self.driver.call('get_window_state', arguments)
		elements = sorted(state.get('elements', []), key=lambda e: e['element_index'])
		self._latest = {e['element_index']: e for e in elements}
		menu = _menu_bar(self._latest)
		usable = [e for e in elements if e.get('enabled') is not False and e['element_index'] not in menu]
		clicks = [e for e in usable if 'AXPress' in e.get('actions', []) and not _is_secure(e)]
		inputs = [e for e in usable if e['role'] in INPUT_ROLES and not _is_secret(e)]
		targets: dict[str, dict[str, Target]] = {}
		count, size = 0, 0
		for operation, candidates in (('click', clicks), ('input', inputs)):
			for element in candidates:
				description = _describe(element)
				size += len(description.encode())
				count += 1
				if count > MAX_TARGETS or size > DESCRIPTION_BUDGET:
					break
				targets.setdefault(operation, {})[str(element['element_index'])] = Target(
					ref=element['element_index'], description=description
				)
		title = state.get('window_title')
		shape = [
			title,
			state.get('elements_complete'),
			[
				[
					e['element_index'],
					e['role'],
					e.get('label'),
					e.get('value'),
					e.get('enabled'),
					e.get('selected'),
					e.get('frame'),
					e.get('actions'),
					e.get('parent_index'),
					e.get('subrole'),
				]
				for e in elements
			],
		]
		return Observation(
			surface='desktop',
			targets=targets,
			operations={'wait': 'Wait one second'},
			context={'app': state.get('app_name'), 'window': title},
			text=_text(elements),
			fingerprint=hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest(),
		)

	async def execute(self, operation: str, target: Target | None, text: str | None) -> None:
		if operation == 'wait':
			await asyncio.sleep(1)
			return
		if operation not in ('click', 'input'):
			raise ValueError(f'unsupported desktop operation: {operation}')
		if target is None or (operation == 'input' and text is None):
			raise ValueError(f'{operation} needs a target' + (' and text' if operation == 'input' else ''))
		element = self._latest.get(target.ref)
		if element is None:
			raise ActionError(f'{operation} failed: element {target.ref} is not in the latest observation')
		arguments = {'pid': self.pid, 'window_id': self.window_id, 'element_token': element['element_token']}
		try:
			if operation == 'click':
				await self.driver.call('click', {**arguments, 'delivery_mode': 'background'})
			else:
				await self.driver.call('set_value', {**arguments, 'value': text})
		except DriverError as error:
			# Message deliberately omits the typed text.
			raise ActionError(f'{operation} failed: {error}') from error
