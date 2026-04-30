"""
Module for Tekla Model wrapper.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from tekla_mcp_server.init import logger
from tekla_mcp_server.utils import log_function_call

from tekla_mcp_server.tekla.loader import (
    Identifier,
    ArrayList,
    Model,
    ModelObjectSelector,
    ModelObjectEnumerator,
    ModelObjectSelectorUI,
    FilterExpression,
    BinaryFilterOperatorType,
    BinaryFilterExpressionCollection,
    BinaryFilterExpressionItem,
    NumericOperatorType,
    NumericConstantFilterExpression,
    BinaryFilterExpression,
    PartFilterExpressions,
    ObjectFilterExpressions,
    TeklaStructuresDatabaseTypeEnum,
)


class TeklaModel:
    """
    A wrapper class around the Tekla Structures Model object.
    Uses thread-safe singleton pattern to reuse the connection.
    """

    _instance = None
    _lock = threading.Lock()
    _max_retries = 3
    _retry_delay = 1.0  # seconds

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._connect()

    def _connect(self, retries: int | None = None) -> None:
        """Connect to Tekla model with retry logic."""
        max_retries = retries if retries is not None else self._max_retries
        last_exception = None

        for attempt in range(max_retries):
            try:
                self._model = None
                self._initialized = False

                model = Model()

                if not model.GetConnectionStatus():
                    raise ConnectionError("Cannot connect to Tekla model. Ensure Tekla is running and a model is open.")

                self._model = model
                self._initialized = True
                logger.debug("Connected to Tekla model (attempt %d)", attempt + 1)
                return

            except Exception as e:
                last_exception = e
                logger.warning("Connection attempt %d/%d failed: %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    import time

                    time.sleep(self._retry_delay * (attempt + 1))  # Exponential backoff

        self._model = None
        self._initialized = False
        if last_exception:
            raise last_exception
        raise ConnectionError("Failed to connect to Tekla model")

    @classmethod
    def reconnect(cls) -> "TeklaModel":
        """Force a reconnection to the Tekla model."""
        with cls._lock:
            instance = cls()
            instance._connect()
            return instance

    def is_connected(self) -> bool:
        """Check if the connection to Tekla model is still active."""
        if self._model is None:
            return False
        try:
            return self._model.GetConnectionStatus()
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        """
        Ensure connection is active, reconnect if needed.

        Returns:
            True if connected after check, False otherwise
        """
        if self.is_connected():
            return True
        logger.info("Connection lost, attempting reconnection...")
        try:
            self._connect()
            return self.is_connected()
        except Exception as e:
            logger.error("Reconnection failed: %s", e)
            return False

    @property
    def model(self) -> Model:
        """
        Get the underlying Tekla Model instance.

        Returns:
            The Model instance for interacting with Tekla Structures

        Raises:
            ConnectionError: If connection to Tekla model is lost and cannot be reconnected
        """
        if not self.ensure_connected():
            raise ConnectionError("Cannot connect to Tekla model. Ensure Tekla is running and a model is open.")
        return self._model

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

        # Filter on parts
        filter_parts = BinaryFilterExpression(ObjectFilterExpressions.Type(), NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(TeklaStructuresDatabaseTypeEnum.PART))
        filter_collection.Add(BinaryFilterExpressionItem(filter_parts, BinaryFilterOperatorType.BOOLEAN_AND))

        # Filter on class
        filter_collection_class = BinaryFilterExpressionCollection()
        filter_class = BinaryFilterExpression(PartFilterExpressions.Class(), NumericOperatorType.IS_EQUAL, NumericConstantFilterExpression(tekla_class))
        filter_collection_class.Add(BinaryFilterExpressionItem(filter_class, BinaryFilterOperatorType.BOOLEAN_OR))
        filter_collection.Add(BinaryFilterExpressionItem(filter_collection_class))

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
