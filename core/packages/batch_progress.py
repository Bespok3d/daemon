"""The live progress a batch publishes while it runs: which plugin it is on, and each install phase
as it finishes. Split out of `batch.py` so the apply engine holds only the applying.
"""

from collections.abc import Callable

# One sink that receives each batch-progress event as a dict (the install-progress hub's publish).
ProgressSink = Callable[[dict], None]


def _drop_event(_event: dict) -> None:
    return None


class BatchProgress:
    """Shapes a batch's live events onto one sink. A `plugin` event names the plugin a batch is
    starting (zero-based index of total); the deferred restart is announced as a `plugin` under
    SERVICES_PLUGIN_ID with index == total. A `phase` event carries a finished install phase.
    """

    def __init__(self, publish: ProgressSink) -> None:
        self._publish = publish

    def plugin(self, plugin_id: str, index: int, total: int) -> None:
        self._publish({"type": "plugin", "plugin_id": plugin_id, "index": index, "total": total})

    def phase(self, finished_phase: dict) -> None:
        self._publish({"type": "phase", "phase": finished_phase})


def make_progress(publish: ProgressSink | None) -> BatchProgress:
    return BatchProgress(publish or _drop_event)
