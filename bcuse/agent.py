"""One loop for every surface and policy: observe, choose, recheck, execute once."""

from collections.abc import Awaitable, Callable, Sequence

from bcuse.model import ActionError, Policy, RunResult, Step, Surface, SurfaceName


class Agent:
	"""Drive one or more surfaces with a Decision model or an LLM.

	Only the active surface is observed and offered each step; `switch_to_<surface>`
	operations move between surfaces. Surfaces stay owned by the caller.
	"""

	def __init__(self, task: str, policy: Policy, surfaces: Sequence[Surface]):
		if not task.strip() or len(task) > 4000:
			raise ValueError('task must be 1-4000 characters.')
		self.task = task
		self.policy = policy
		self.surfaces: dict[SurfaceName, Surface] = {surface.name: surface for surface in surfaces}
		if not self.surfaces or len(self.surfaces) != len(surfaces):
			raise ValueError('Pass at least one surface, at most one per kind.')

	async def run(
		self,
		max_steps: int = 50,
		*,
		start: SurfaceName | None = None,
		outcome_verifier: Callable[[], Awaitable[bool]] | None = None,
	) -> RunResult:
		"""Run bounded steps. An optional independent verifier checks a model-declared DONE."""
		if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
			raise ValueError('max_steps must be a positive integer.')
		active = self.surfaces[start] if start else next(iter(self.surfaces.values()))
		result = RunResult(status='max_steps')
		for _ in range(max_steps):
			switches = {
				f'switch_to_{name}': f'Observe the {name} instead' for name in self.surfaces if name != active.name
			}
			observation = await active.observe()
			choice = await self.policy.choose(self.task, observation, switches, result.steps)
			if choice.operation in switches:
				result.steps.append(Step(active.name, choice.operation))
				active = self.surfaces[choice.operation.removeprefix('switch_to_')]
				continue
			current = await active.observe()
			if current.fingerprint != observation.fingerprint:
				result.status = 'stale_state'
				return result
			result.steps.append(Step(active.name, choice.operation, choice.key))
			if choice.operation == 'DONE':
				result.status = 'model_done'
				result.verified = await outcome_verifier() if outcome_verifier else None
				return result
			if choice.operation == 'BLOCKED':
				result.status = 'blocked'
				return result
			target = current.targets[choice.operation][choice.key] if choice.key is not None else None
			try:
				await active.execute(choice.operation, target, choice.text)
			except ActionError:
				result.status = 'action_error'
				return result
		return result
