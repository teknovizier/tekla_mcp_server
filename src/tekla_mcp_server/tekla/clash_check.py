"""
Wrappers around the Tekla clash check API.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any

from tekla_mcp_server.init import logger
from tekla_mcp_server.tekla.loader import (
    ClashCheckHandler,
    Events,
)

from tekla_mcp_server.tekla.wrappers.model import TeklaModel
from tekla_mcp_server.tekla.wrappers.model_object import wrap_model_object


@dataclass
class ClashCheckObject:
    """Resolved object data for one participant in a clash check result."""

    guid: str | None = None
    name: str = "N/A"
    profile: str = "N/A"
    material: str = "N/A"
    tekla_class: int = 0
    top_assembly_guid: str | None = None


# Default timeout for the Tekla clash check engine to signal completion
_DEFAULT_TIMEOUT = 600.0


class TeklaClashCheckData:
    """
    Python wrapper around ClashCheckData.

    Exposes the four properties of the underlying record plus a `to_dict` serialiser.
    """

    def __init__(self, raw: Any, cache: dict[str, Any]) -> None:
        self._raw = raw
        # Built on the main thread after the engine finishes
        self.object1: ClashCheckObject = self._build(raw.Object1, cache)
        self.object2: ClashCheckObject = self._build(raw.Object2, cache)

    @staticmethod
    def _build(obj: Any, cache: dict[str, Any]) -> ClashCheckObject:
        _na = "N/A"
        ref = wrap_model_object(obj)
        if ref is None:
            return ClashCheckObject()

        fetched = cache.get(ref.guid)
        if fetched is None:
            return ClashCheckObject()

        top = fetched.get_top_level_assembly()
        return ClashCheckObject(
            guid=fetched.guid,
            name=getattr(fetched, "name", _na) or _na,
            profile=getattr(fetched, "profile", _na) or _na,
            material=getattr(fetched, "material", _na) or _na,
            tekla_class=getattr(fetched, "tekla_class", 0) or 0,
            top_assembly_guid=top.guid if top else None,
        )

    @property
    def clash_type(self) -> str:
        return str(self._raw.Type)

    @property
    def overlap(self) -> float | None:
        if self.clash_type == "CLASH_TYPE_CLASH":
            return float(self._raw.Overlap)
        return None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "object1": asdict(self.object1),
            "object2": asdict(self.object2),
            "clash_type": self.clash_type,
        }
        if self.overlap is not None:
            d["overlap"] = self.overlap
        return d


class TeklaClashCheckHandler:
    """
    Wrapper around ClashCheckHandler.

    Subscribes to Events.ClashDetected and Events.ClashCheckDone, runs the requested
    clash-check variant, and blocks until completion. Returns the collected
    ClashCheckData records.
    """

    def __init__(self, timeout_seconds: float = _DEFAULT_TIMEOUT):
        self._handler = ClashCheckHandler()
        self._events = Events()
        self._timeout_seconds = timeout_seconds
        self._raw_records: list[Any] = []
        self._done = threading.Event()
        self._last_count: int = 0
        self._subscribed = False

    def _on_clash_detected(self, clash_data: Any) -> None:
        self._raw_records.append(clash_data)  # Store raw records only

    def _on_clash_check_done(self, count: int) -> None:
        self._last_count = int(count)
        self._done.set()

    def _subscribe(self) -> None:
        if self._subscribed:
            logger.warning("Already subscribed to clash check events")
            return

        self._raw_records = []
        self._done.clear()
        self._last_count = 0
        self._subscribed = True
        self._events.ClashDetected += self._on_clash_detected
        self._events.ClashCheckDone += self._on_clash_check_done
        self._events.Register()

    def _unsubscribe(self) -> None:
        if not self._subscribed:
            logger.debug("Not currently subscribed to clash check events")
            return

        try:
            self._events.UnRegister()
        finally:
            try:
                self._events.ClashDetected -= self._on_clash_detected
            except Exception as e:
                logger.warning("Failed to unsubscribe ClashDetected handler: %s", e)
            try:
                self._events.ClashCheckDone -= self._on_clash_check_done
            except Exception as e:
                logger.warning("Failed to unsubscribe ClashCheckDone handler: %s", e)
            self._subscribed = False

    def stop(self) -> bool:
        """Forwards to ClashCheckHandler.StopClashCheck."""
        return bool(self._handler.StopClashCheck())

    def get_intersection_bounding_boxes(self, id1: Any, id2: Any) -> Any:
        """Forwards to ClashCheckHandler.GetIntersectionBoundingBoxes."""
        return self._handler.GetIntersectionBoundingBoxes(id1, id2)

    def run(
        self,
        between_parts: bool = True,
        between_reference_models: bool = False,
        objects_inside_reference_models: bool = False,
        min_distance: float = 0.0,
    ) -> list[TeklaClashCheckData]:
        """
        Runs the Tekla clash check against the current selection.

        Returns the list of ClashCheckData records collected via the ClashDetected event.
        """
        self._subscribe()
        try:
            success = self._handler.RunClashCheckWithOptions(
                between_reference_models,
                objects_inside_reference_models,
                float(min_distance),
                between_parts,
            )
            if not success:
                raise RuntimeError("ClashCheckHandler.RunClashCheckWithOptions returned false")

            if not self._done.wait(timeout=self._timeout_seconds):
                logger.warning("ClashCheckHandler.run timed out after %.0fs waiting for ClashCheckDone", self._timeout_seconds)
        finally:
            self._unsubscribe()

        # Build GUID cache directly from wrapped objects without re-lookups
        # NOTE: `raw_obj` is the lightweight reference from the clash record.
        # To access full Tekla object properties (e.g. name, profile, material), refetch via `get_object_by_guid(wrapped.guid)`.
        # The cache stores current wraps so downstream code can do the full refetch when needed.
        guid_cache: dict[str, Any] = {}
        for raw in self._raw_records:
            for raw_obj in (raw.Object1, raw.Object2):
                ref = wrap_model_object(raw_obj)
                if ref is not None and ref.guid not in guid_cache:
                    fetched = wrap_model_object(TeklaModel().get_object_by_guid(ref.guid))
                    if fetched is not None:
                        guid_cache[ref.guid] = fetched
        logger.debug("Built clash GUID cache: %d unique objects for %d records", len(guid_cache), len(self._raw_records))

        # Build on the main thread
        records = [TeklaClashCheckData(r, guid_cache) for r in self._raw_records]
        logger.debug("ClashCheckHandler.run collected %d records (engine reported %d)", len(records), self._last_count)
        return records
