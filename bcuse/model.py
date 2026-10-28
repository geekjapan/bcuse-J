"""Domain types shared by every surface and policy.

A surface (browser or desktop) turns what it observes into a finite table of
targets per operation. A policy (Decision model or LLM) picks one operation and,
for targeted operations, one key from that table. Nothing the model returns is
executed unless it names an observed key.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import JsonValue

SurfaceName = Literal['browser', 'desktop']

TARGETED_OPERATIONS = ('click', 'input', 'select')
TERMINAL_OPERATIONS = ('DONE', 'BLOCKED')


class ActionError(RuntimeError):
	"""The surface refused or failed an action. It may have partially happened; never retried."""


@dataclass(frozen=True)
class Target:
	ref: int
	"""Surface-private handle (browser selector index, desktop element index). Never shown to a model."""
	description: str
	option: str | None = None
	"""Native select option text to choose; only browser select targets set it."""


@dataclass(frozen=True)
class Observation:
	surface: SurfaceName
	targets: Mapping[str, Mapping[str, Target]]
	"""operation -> key -> target, for operations in TARGETED_OPERATIONS that have candidates."""
	operations: Mapping[str, str]
	"""Untargeted operations this surface supports right now: name -> model-facing description."""
	context: Mapping[str, JsonValue]
	"""Small model-facing facts (url, title, app, window)."""
	text: str
	"""Model-facing page or window text; policies may truncate it to fit a request budget."""
	fingerprint: str
	"""Hash of the complete observation; equal fingerprints mean the targets still mean the same thing."""


@dataclass(frozen=True)
class Choice:
	operation: str
	key: str | None = None
	text: str | None = None


@dataclass(frozen=True)
class Step:
	surface: SurfaceName
	operation: str
	key: str | None = None


RunStatus = Literal['model_done', 'blocked', 'max_steps', 'stale_state', 'action_error']


@dataclass
class RunResult:
	status: RunStatus
	steps: list[Step] = field(default_factory=list)
	verified: bool | None = None
	"""Set only by an outcome verifier after DONE. A model's DONE alone is not success."""


class Surface(Protocol):
	name: SurfaceName

	async def observe(self) -> Observation: ...

	async def execute(self, operation: str, target: Target | None, text: str | None) -> None:
		"""Act on the target from the most recent observe(). Raises ActionError."""
		...


class Policy(Protocol):
	can_type: bool
	"""Whether the policy can supply text, so input targets may be offered."""

	async def choose(
		self, task: str, observation: Observation, switches: Mapping[str, str], history: list[Step]
	) -> Choice: ...
