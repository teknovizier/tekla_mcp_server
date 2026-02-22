"""
Module for Tekla Model wrapper.
"""

from __future__ import annotations

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
    Uses singleton pattern to reuse the connection.
    """

    _instance: "TeklaModel | None" = None

    def __new__(cls) -> "TeklaModel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            logger.debug("Reusing existing Tekla model connection")
            return
        self._model = Model()
        if not self._model.GetConnectionStatus():
            raise ConnectionError("Cannot connect to Tekla model. Please check that Tekla Structures is running and the model is opened.")
        logger.debug("Connected to Tekla model")
        self._initialized = True

    @property
    def model(self) -> Model:
        """
        Returns the underlying Model instance.
        """
        return self._model

    @log_function_call
    def commit_changes(self) -> bool:
        """
        Commits the changes made to the model.
        """
        return self.model.CommitChanges()

    @log_function_call
    def get_all_objects(self) -> ModelObjectEnumerator:
        """
        Returns all objects in the model.
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

        # FIlter on class
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
