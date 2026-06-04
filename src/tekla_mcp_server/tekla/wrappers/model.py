"""
Module for Tekla Model wrapper.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import ClassVar

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_function_call
from tekla_mcp_server.tekla.filter_builder import add_filter

from tekla_mcp_server.tekla.loader import (
    Identifier,
    ArrayList,
    Model,
    ModelObject,
    ModelObjectSelector,
    ModelObjectEnumerator,
    ModelObjectSelectorUI,
    PhaseCollection,
    FilterExpression,
    BinaryFilterExpressionCollection,
    PartFilterExpressions,
    ObjectFilterExpressions,
    TeklaStructuresDatabaseTypeEnum,
)


class TeklaModel:
    """
    A wrapper class around the Tekla Structures Model object.
    Uses thread-safe singleton pattern to reuse the connection.

    NOTE: The Tekla Open API cannot re-establish a connection once it is lost
    (see the Model.GetConnectionStatus documentation). A genuine loss - e.g. Tekla
    Structures being closed and reopened - is unrecoverable in-process, and the MCP
    server must be restarted. Retries are therefore scoped to the initial connection,
    mid-session checks make a single cheap reconnect attempt and otherwise fail fast.
    """

    _instance: ClassVar["TeklaModel | None"] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()
    _max_retries: ClassVar[int] = 3
    _retry_delay: ClassVar[float] = 1.0  # seconds

    _connect_lock: threading.RLock
    _model: Model | None
    _initialized: bool

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._connect_lock = threading.RLock()
                    instance._model = None
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        with self._connect_lock:
            if self._initialized:
                return
            self._connect()

    def _connect(self, retries: int | None = None) -> None:
        """Connect to Tekla model with retry logic. Caller must hold ``_connect_lock``."""
        max_retries = retries if retries is not None else self._max_retries
        last_exception = None

        # Preserve current state so a failed reconnect attempt does not orphan a handle
        # that may still be valid (e.g. transient false-negative from ensure_connected).
        # On initial connect both are None/False, so restore is a no-op in that case.
        saved_model, saved_initialized = self._model, self._initialized

        for attempt in range(max_retries):
            try:
                model = Model()

                if not model.GetConnectionStatus():
                    raise ConnectionError("Cannot connect to Tekla model. Ensure Tekla is running and a model is open.")

                self._model = model
                self._initialized = True
                logger.debug("Connected to Tekla model (attempt %d)", attempt + 1)
                return

            except Exception as e:
                last_exception = e
                # Only log individual attempt warnings when multi-retry is in play
                # (e.g. initial connect). For single-attempt mid-session probes the
                # caller logs the outcome, so suppress here to avoid double-logging.
                if max_retries > 1:
                    logger.warning("Connection attempt %d/%d failed: %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))  # Linear backoff (1s, 2s, ...)

        self._model, self._initialized = saved_model, saved_initialized
        if last_exception:
            raise last_exception
        raise ConnectionError("Failed to connect to Tekla model")

    def is_connected(self) -> bool:
        """Check if the connection to Tekla model is still active.

        GetConnectionStatus() reads a local cached flag, it does not do a
        network round-trip, so it fast-fails when Tekla is gone.
        """
        if self._model is None:
            return False
        try:
            return self._model.GetConnectionStatus()
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        """
        Ensure the connection is active, making a single quick reconnect attempt if needed.

        A genuine connection loss cannot be recovered in-process (the Open API cannot
        re-establish a lost connection), so this makes just one cheap attempt - enough
        to ride out a transient false negative - rather than retrying a dead connection.

        Returns:
            True if connected after the check, False otherwise.
        """
        if self.is_connected():
            return True
        with self._connect_lock:
            # Re-check under the lock: another thread may have reconnected while we waited.
            if self.is_connected():
                return True
            logger.info("Connection lost, attempting a single reconnect...")
            try:
                self._connect(retries=1)
                return True
            except ConnectionError as e:
                logger.error("Reconnection failed: %s. Restart Tekla Structures and the MCP server to reconnect.", e)
                return False

    @property
    def model(self) -> Model:
        """
        Get the underlying Tekla Model instance.

        Returns:
            The Model instance for interacting with Tekla Structures

        Raises:
            ConnectionError: If the connection to Tekla is lost. The Open API cannot
                re-establish a lost connection, so the MCP server must be restarted.
        """
        # A concurrent failed reconnect can null _model after ensure_connected()
        # returned, so treat None as "not connected" too rather than returning it.
        model = self._model if self.ensure_connected() else None
        if model is None:
            raise ConnectionError("Tekla connection lost. Ensure Tekla Structures is running with a model open, then restart the MCP server to reconnect.")
        return model

    @property
    def model_path(self) -> str:
        """
        Return the current model's folder path.

        Read fresh on every call so it always reflects the model that is currently
        open, even when the user switches models within the same Tekla session.

        Returns:
            The model folder path, or an empty string if unavailable.

        Raises:
            ConnectionError: If not connected to a Tekla model.
        """
        info = self.model.GetInfo()
        return info.ModelPath or "" if info is not None else ""

    @log_function_call
    def commit_changes(self) -> bool:
        """
        Commit the changes made to the model.

        Returns:
            True if the commit was successful, False otherwise
        """
        return self.model.CommitChanges()

    @log_function_call
    def get_all_objects(self) -> ModelObjectEnumerator:
        """
        Get all objects in the model.

        Returns:
            ModelObjectEnumerator containing all objects in the model
        """
        selector = ModelObjectSelector()
        return selector.GetAllObjects()

    @log_function_call
    def get_selected_objects(self) -> ModelObjectEnumerator:
        """
        Returns currently selected objects in the model.

        Raises:
            ValueError: If no objects are selected.
        """
        selector = ModelObjectSelectorUI()
        selected_objects = selector.GetSelectedObjects()

        if not selected_objects.GetSize():
            raise ValueError("No objects are currently selected in the model.")

        return selected_objects

    @log_function_call
    def get_objects_by_class(self, tekla_class: int) -> ModelObjectEnumerator:
        """
        Returns objects in the model selected by the given Tekla class.

        Args:
            tekla_class: The Tekla class number to filter by

        Returns:
            ModelObjectEnumerator containing objects of the specified class
        """
        filter_collection = BinaryFilterExpressionCollection()
        add_filter(filter_collection, ObjectFilterExpressions.Type(), TeklaStructuresDatabaseTypeEnum.PART)
        add_filter(filter_collection, PartFilterExpressions.Class(), tekla_class)

        return self.get_objects_by_filter(filter_collection)

    @log_function_call
    def get_objects_by_guid(self, guids: list[str]) -> ArrayList:
        """
        Returns model objects by their GUIDs.

        Args:
            guids: List of GUID strings to retrieve

        Returns:
            ArrayList containing the found model objects
        """
        objects_to_select = ArrayList()
        for guid in guids:
            obj = self.model.SelectModelObject(Identifier(guid))
            if obj is not None:
                objects_to_select.Add(obj)

        return objects_to_select

    @log_function_call
    def get_object_by_guid(self, guid: str) -> ModelObject | None:
        """
        Return a single model object by GUID, or None if not found.
        """
        return self.model.SelectModelObject(Identifier(guid))

    @log_function_call
    def get_objects_by_filter(self, model_filter: FilterExpression | str) -> ModelObjectEnumerator:
        """
        Returns objects in the model selected by the given selection filter definition.

        Args:
            model_filter: FilterExpression object or filter name string

        Returns:
            ModelObjectEnumerator containing objects matching the filter

        Raises:
            TypeError: If the provided filter type is not FilterExpression or str.
        """
        selector = ModelObjectSelector()
        if isinstance(model_filter, FilterExpression):
            objects_to_select = selector.GetObjectsByFilter(model_filter)
        elif isinstance(model_filter, str):
            objects_to_select = selector.GetObjectsByFilterName(model_filter)
        else:
            raise TypeError(f"Invalid filter type: {type(model_filter)}. Expected FilterExpression or str.")

        if not objects_to_select.GetSize():
            return ModelObjectEnumerator()  # Empty

        return objects_to_select

    @log_function_call
    def get_phases(self) -> PhaseCollection:
        """Return all phases defined in the model."""
        return self.model.GetPhases()

    @staticmethod
    def select_objects(model_objects: Iterable) -> bool:
        """
        Selects the given model objects in the model.

        Args:
            model_objects: Iterable of model objects to select

        Returns:
            True if selection was successful
        """
        selector = ModelObjectSelectorUI()

        if isinstance(model_objects, ArrayList):
            return selector.Select(model_objects)

        array_list = ArrayList()
        for model_object in model_objects:
            array_list.Add(model_object)

        return selector.Select(array_list)

    @staticmethod
    def clear_selection() -> bool:
        """
        Clears the current selection in the model.

        Returns:
            True if selection was cleared successfully
        """
        selector = ModelObjectSelectorUI()
        return selector.Select(ArrayList())
