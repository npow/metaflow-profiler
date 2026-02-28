"""@profile_card step decorator.

Layer: Decorator (top-most)
May only import from: registry, ..profiler (ABC), standard library, metaflow

This module wires the profiler lifecycle into Metaflow's StepDecorator hooks
and auto-injects a @card(type='profile_card') onto the decorated step so
users only need a single decorator.
"""

from __future__ import annotations

import dataclasses
import traceback
from typing import Any
from typing import ClassVar

from metaflow.decorators import StepDecorator
from metaflow.exception import MetaflowException


class ProfileCardException(MetaflowException):
    headline = "Profile card error"


#: Artifact name written to the flow object and read by the card renderer.
#: Must NOT start with "_" — Metaflow excludes underscore-prefixed attributes
#: from artifact serialization.
_ARTIFACT_NAME = "profile_card_data"

#: Card type string — must match ProfileCard.type in card.py.
_CARD_TYPE = "profile_card"


class ProfileCardDecorator(StepDecorator):
    """Profile a Metaflow step and render an interactive flamegraph card.

    Parameters
    ----------
    profiler : str
        Backend to use.  One of ``"pyinstrument"`` (default when installed),
        ``"cprofile"`` (always available).  Defaults to the best available.
    sample_interval : float
        Sampling interval in seconds for statistical profilers (default 0.001).
    timeline_interval : float
        How often (seconds) to poll CPU / memory during the step (default 0.5).
    artifact_name : str
        Name of the task artifact that stores profiling data (default
        ``"_profile_card_data"``).  Override if you have multiple profiled
        steps and want distinct artifact names.
    create_card : bool
        Whether to auto-inject a @card decorator (default True).  Set to
        False if you want to manage card rendering yourself.
    """

    name = "profile_card"  # type: ignore[misc]

    defaults: ClassVar[dict[str, Any]] = {  # type: ignore[misc]
        "profiler": None,          # None → pick best available
        "sample_interval": 0.001,
        "timeline_interval": 0.5,
        "artifact_name": _ARTIFACT_NAME,
        "create_card": True,
    }

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def step_init(
        self,
        flow: Any,
        graph: Any,
        step_name: str,
        decorators: Any,
        environment: Any,
        flow_datastore: Any,
        logger: Any,
    ) -> None:
        self._logger = logger
        self._step_name = step_name
        self._artifact_name = self.attributes["artifact_name"]

        if self.attributes["create_card"]:
            card_id = f"profile_card_{step_name}"
            already_present = any(
                getattr(d, "name", None) == "card"
                and getattr(d, "attributes", {}).get("id") == card_id
                for d in decorators
            )
            if not already_present:
                from metaflow.plugins.cards.card_decorator import CardDecorator

                decorators.append(
                    CardDecorator(
                        attributes={
                            "type": _CARD_TYPE,
                            "id": card_id,
                            "options": {"artifact_name": self._artifact_name},
                        }
                    )
                )

    def task_pre_step(
        self,
        step_name: str,
        task_datastore: Any,
        metadata: Any,
        run_id: str,
        task_id: str,
        flow: Any,
        graph: Any,
        retry_count: int,
        max_user_code_retries: int,
        ubf_context: Any,
        inputs: Any,
    ) -> None:
        """Start the chosen profiler backend immediately before step code runs."""
        self._backend = None
        self._flow = flow

        try:
            from .profilers import default_backend
            from .profilers import get_backend

            backend_name: str = self.attributes["profiler"] or default_backend()
            self._backend = get_backend(backend_name)

            # Pass tuning parameters if the backend accepts them.
            # We recreate the backend with explicit kwargs so concrete
            # classes control their own __init__ signatures.
            from .profilers import _REGISTRY

            cls = _REGISTRY[backend_name]
            kwargs: dict[str, Any] = {}
            import inspect

            sig = inspect.signature(cls.__init__)
            if "sample_interval" in sig.parameters:
                kwargs["sample_interval"] = float(self.attributes["sample_interval"])
            if "timeline_interval" in sig.parameters:
                kwargs["timeline_interval"] = float(self.attributes["timeline_interval"])
            self._backend = cls(**kwargs)
            self._backend.start()

        except Exception as exc:
            self._logger(
                f"[@profile_card] Failed to start profiler: {exc}",
                timestamp=False,
                bad=True,
            )
            self._backend = None

    def task_post_step(
        self,
        step_name: str,
        flow: Any,
        graph: Any,
        retry_count: int,
        max_user_code_retries: int,
    ) -> None:
        """Stop profiling and persist data as a task artifact."""
        self._save(flow, step_failed=False)

    def task_exception(
        self,
        exception: Any,
        step_name: str,
        flow: Any,
        graph: Any,
        retry_count: int,
        max_user_code_retries: int,
    ) -> None:
        """Persist profiling data even when the step raises."""
        self._save(flow, step_failed=True)

    def task_finished(
        self,
        step_name: str,
        flow: Any,
        graph: Any,
        is_task_ok: bool,
        retry_count: int,
        max_user_code_retries: int,
    ) -> None:
        """Force card rendering for failed steps (Metaflow skips it by default)."""
        if is_task_ok or not self.attributes["create_card"]:
            return
        card_id = f"profile_card_{step_name}"
        try:
            for deco in graph[step_name].decorators:
                if (
                    getattr(deco, "name", None) == "card"
                    and getattr(deco, "attributes", {}).get("id") == card_id
                ):
                    create_opts = dict(
                        card_uuid=deco._card_uuid,
                        user_set_card_id=deco._user_set_card_id,
                        runtime_card=deco._is_runtime_card,
                        decorator_attributes=deco.attributes,
                        card_options=deco.card_options,
                        logger=self._logger,
                    )
                    deco.card_creator.create(mode="render", final=True, **create_opts)
                    break
        except Exception as exc:
            self._logger(
                f"[@profile_card] Could not render card for failed step: {exc}",
                timestamp=False,
                bad=False,
            )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _save(self, flow: Any, step_failed: bool) -> None:
        """Stop backend (if running) and write artifact to *flow*."""
        data_dict: dict[str, Any]

        if self._backend is None:
            data_dict = {
                "error": {
                    "type": "RuntimeError",
                    "message": "Profiler backend failed to start.",
                }
            }
        else:
            try:
                profile_data = self._backend.stop()
                data_dict = {
                    "step_failed": step_failed,
                    "data": dataclasses.asdict(profile_data),
                }
            except Exception as exc:
                data_dict = {
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                }

        setattr(flow, self._artifact_name, data_dict)
