# Reference

Complete reference for tools and resources available in Tekla MCP Server.

## Tools

| Category | Tool | Description | Parameters |
|----------|------|-------------|------------|
| Selection | `select_elements_by_filter` | Select elements in Tekla model based on type/Tekla class, name, profile, material, finish, phase, part/assembly prefix and  part/assembly start number. Supports complex filters with AND/OR logic | `element_type`, `tekla_classes`, `standard_string_filters`, `standard_numeric_filters`, `custom_string_filters`, `custom_numeric_filters`, `combine_with` |
| Selection | `select_elements_by_filter_name` | Select elements in Tekla model based on a predefined filter | `filter_name` (required) |
| Selection | `select_elements_by_guid` | Select elements in Tekla model by their GUID | `guids` (required) |
| Selection | `select_elements_assemblies_or_main_parts` | Get assemblies or main parts for the selected elements and select them | `mode` (required): Assembly or Main Part |
| Components | `put_components` | Insert Tekla components with optional semantic attribute mapping that converts user-friendly names (e.g., "concrete cover thickness") to config keys (e.g., "CoverThickness"). Intelligent components like `Lifting Anchor` automatically select anchor types based on element weight and place them with recesses according to handler settings | `component_name` (required), `properties_set`, `custom_properties` |
| Components | `get_components` | Get all components attached to selected elements. Returns component name, number, attribute schema and values | - |
| Components | `modify_components` | Modify attributes of existing components on selected elements | `component_name` (required), `custom_properties` (required) |
| Components | `remove_components` | Remove Tekla components with specified name from the selected elements | `component_name` (required) |
| Properties | `get_elements_properties` | Retrieve structured data about selected elements. Returns three tables: assemblies, parts, and IFC reference objects. Includes UDAs and report properties | `report_props_definitions` |
| Properties | `set_elements_properties` | Set properties on selected elements. **For parts:** name, profile, material, finish, class, part/assembly numbering, phase. **For assemblies:** name, assembly numbering, phase. UDAs supported | `name`, `profile`, `material`, `tekla_class`, `finish`, `part_prefix`, `part_start_number`, `assembly_prefix`, `assembly_start_number`, `phase`, `user_properties` |
| Properties | `get_elements_cut_parts` | Find all cut parts in the selected elements and returns a summary grouped by profile | - |
| Properties | `clear_elements_udas` | Clear user-defined attributes (UDAs) from selected Tekla parts and assemblies. If no specific UDA names are provided, clears all UDAs | `uda_names` |
| Properties | `get_elements_coordinates` | Get coordinates of selected elements. Returns start point, end point, start point offset, end point offset for beams, contour points for slabs | - |
| Properties | `compare_elements` | Compare two selected Tekla elements and returns detailed differences (part properties, UDA, cutparts, welds, reinforcements) | `ignore_numbering` |
| View | `draw_elements_labels` | Draw temporary labels for selected elements. **For parts:** position, GUID, name, profile, material, finish, class, weight. **For assemblies:** position, GUID, name, weight. Supports custom report properties | `label`, `custom_label` |
| View | `zoom_to_selection` | Zooms the currently active rendered view to fit the currently selected elements | - |
| View | `redraw_view` | Redraws the currently active view in Tekla | - |
| View | `show_only_selected` | Show only the currently selected elements in the currently active rendered view | - |
| View | `hide_selected` | Hide the currently selected elements in the currently active rendered view | - |
| View | `color_selected` | Color the currently selected elements in the currently active rendered view with a specified RGB color | `red`, `green`, `blue` (required, 0-255) |
| View | `apply_view_filter` | Apply a view filter the currently active view in Tekla | `filter_name` (required) |
| Operations | `cut_elements_with_zero_class_parts` | Performs boolean cuts on selected elements using elements in class 0, with optional deletion of cutting parts | `delete_cutting_parts` |
| Operations | `convert_cut_parts_to_real_parts` | Convert all cut parts in the selected elements into real model parts | - |
| Operations | `check_for_orphaned_embeds` | Find embedded details within bounding box of selected elements that are not attached to any selected assembly. Returns orphaned details and colors them red | - |
| Operations | `run_macro` | Run a Tekla macro with the specified name | `macro_name` (required) |
| Drawings | `get_drawings` | Get drawings from Tekla model with optional filtering by type, name, mark, title1/2/3 | `drawing_type`, `name_filter`, `mark_filter`, `title1_filter`, `title2_filter`, `title3_filter` |
| Drawings | `get_drawing_properties` | Get properties of drawings by their marks or currently selected drawings in Tekla | `marks` |
| Drawings | `detect_collisions_between_marks` | Detect collisions between part marks in drawings by their marks or currently selected drawings in Tekla. Colliding marks are colored red | `marks` |
| Drawings | `print_drawings` | Print drawings to PDF with automatic size detection (A4-A0) | `marks`, `output_filename`, `output_folder`, `printer_attributes` |
| Modeling | `place_beams` | Place one or more beams in the Tekla model | `beams` (list with start point, end point, start point offset, end_point offset, profile, material, Tekla class, name, position) |
| Modeling | `place_columns` | Place one or more columns in the Tekla model | `columns` (list with base point, height, start point offset, end point offset, profile, material, Tekla class, name, position) |
| Modeling | `place_panels` | Place one or more wall panels in the Tekla model | `panels` (list with start point, end point, start point offset, end point offset, profile, material, Tekla class, name, position) |
| Modeling | `place_slabs` | Place one or more slabs in the Tekla model | `slabs` (list with points (min 3), profile, material, Tekla class, name, position) |
| Modeling | `delete_selected` | Delete all currently selected elements in Tekla | - |
| IFC | `copy_properties_from_ifc` | Copy user-defined properties from IFC reference objects to matching Tekla model elements by bounding box matching | `user_properties` (required): Mapping of IFC property names to Tekla UDA names |

## Resources

| Resource | Description |
|----------|-------------|
| `project://requirements` | Returns combined content of markdown files from the requirements folder (e.g., reinforcement defaults, material specs) |
| `tekla://components` | Returns the list of Tekla components available in server configuration |
| `tekla://components/{component_key}` | Returns the custom_properties schema for a specific component |
| `tekla://macros` | Returns list of available Tekla macros from configured directories |
| `tekla://element_types` | Returns element types from `element_types.json` config as flat list |
| `tekla://filters/selection` | Returns list of available Tekla selection filter names from `.SObjGrp` files |
| `tekla://filters/view` | Returns list of available Tekla view filter names from `.VObjGrp` files |
| `tekla://phases` | Returns list of all phases in the current Tekla model |
| `tekla://grids` | Returns rectangular grid data from the current Tekla model (guid, name, axes with coordinates and labels) |
| `tekla://connection_status` | Returns the current Tekla connection status (connected, model_path, message) |

Filter resources search in:
- `XS_FIRM` advanced option directories
- `XS_PROJECT` advanced option directories
- Model attributes directory (`./attributes`)
