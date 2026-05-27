# Reference

Complete reference for tools and resources available in Tekla MCP Server.

## Tools

Parameter notation:
**`param`** = required, `param` = optional.
Type and default shown where relevant.

| Category | Tool | Description | Parameters |
|----------|------|-------------|------------|
| Selection | `select_elements_by_filter` | Select elements by type, Tekla class, name, profile, material, finish, phase, part/assembly prefix/number. Supports AND/OR logic | `element_type` (str), `tekla_classes` (int \| list[int]), `standard_string_filters` (dict), `standard_numeric_filters` (dict), `custom_string_filters` (dict), `custom_numeric_filters` (dict), `combine_with` (str, default: `"AND"`) - all optional |
| Selection | `select_elements_by_filter_name` | Select elements using a saved Tekla filter | **`filter_name`** (str) |
| Selection | `select_elements_by_guid` | Select elements by GUID | **`guids`** (list[str]) |
| Selection | `select_elements_assemblies_or_main_parts` | Switch selection to assemblies or main parts for the currently selected elements | **`mode`** (str): `"Assembly"` \| `"Main Part"` |
| Components | `put_components` | Insert a Tekla component on selected elements. Supports semantic attribute mapping and intelligent defaults (e.g. anchor type by weight) | **`component_name`** (str), `properties_set` (str, default: `"standard"`), `custom_properties` (dict) |
| Components | `get_components` | Get all components attached to selected elements. Returns name, number, attribute schema and current values | - |
| Components | `modify_components` | Modify attributes of existing components on selected elements | **`component_name`** (str), **`custom_properties`** (dict) |
| Components | `remove_components` | Remove all components with the given name from selected elements | **`component_name`** (str) |
| Properties | `get_elements_properties` | Retrieve structured data about selected elements. Default mode returns flat tables (assemblies, parts, IFC objects) with UDAs and report properties. `snapshot_mode=true` returns full snapshots with all report properties, all UDAs, and nested reinforcement - use for convention checking | `report_props_definitions` (list[str]), `snapshot_mode` (bool, default: `false`) - all optional |
| Properties | `set_elements_properties` | Set properties on selected elements. Parts: name, profile, material, finish, class, numbering, phase. Assemblies: name, numbering, phase. UDAs supported via `user_properties` | `name` (str), `profile` (str), `material` (str), `tekla_class` (int), `finish` (str), `part_prefix` (str), `part_start_number` (int), `assembly_prefix` (str), `assembly_start_number` (int), `phase` (int), `user_properties` (dict) - all optional |
| Properties | `get_elements_cut_parts` | Find all cut parts in selected elements, grouped by profile | - |
| Properties | `clear_elements_udas` | Clear UDAs from selected parts and assemblies. Clears all UDAs if no names provided | `uda_names` (list[str], optional) |
| Properties | `get_elements_coordinates` | Get coordinates of selected elements: start/end points and offsets for beams, contour points for slabs | - |
| Properties | `compare_elements` | Compare two selected elements and return detailed differences (properties, UDAs, cut parts, welds, reinforcements) | `ignore_numbering` (bool, default: `false`) |
| Properties | `copy_properties_from_ifc` | Copy properties from IFC reference objects to matching Tekla elements by bounding-box overlap | **`user_properties`** (dict[str, str]): IFC property name → Tekla UDA name |
| View | `draw_elements_labels` | Draw temporary labels on selected elements. Parts show position, GUID, name, profile, material, finish, class, weight. Assemblies show position, GUID, name, weight | `label` (str, optional), `custom_label` (str, optional) |
| View | `zoom_to_selection` | Zoom the active rendered view to fit selected elements | - |
| View | `redraw_view` | Redraw the active view | - |
| View | `show_only_selected` | Hide everything except selected elements in the active view | - |
| View | `hide_selected` | Hide selected elements in the active view | - |
| View | `color_selected` | Color selected elements with an RGB colour | **`red`** (int, 0–255), **`green`** (int, 0–255), **`blue`** (int, 0–255) |
| View | `apply_view_filter` | Apply a saved view filter to the active view | **`filter_name`** (str) |
| Operations | `cut_elements_with_cutters` | Boolean-cut selected elements using parts identified by class or GUID | `cutter_class` (int \| null), `cutter_guids` (list[str] \| null) - exactly one required, `delete_cutting_parts` (bool, default: `false`) |
| Operations | `convert_cut_parts_to_real_parts` | Convert all cut parts in selected elements into standalone model parts | - |
| Operations | `check_for_orphans` | Find orphaned embeds or rebars inside the bounding box of selected elements. Optionally attach orphans to their parent assembly | **`mode`** (str): `"embeds"` \| `"rebars"`, `attach` (bool, default: `false`) |
| Operations | `check_for_invalid_objects` | Find invalid objects (missing profile/material, bad geometry, no parent) among selected elements and their bounding boxes | - |
| Operations | `clash_check` | Run Tekla's clash check against the current selection. Returns one record per detected clash with `object1`, `object2` (each: `guid`, `name`, `profile`, `material`, `tekla_class`, `top_assembly_guid`), `clash_type`, and `overlap` (only for `CLASH_TYPE_CLASH`). When `filter_name` is supplied, selected assemblies are expanded to their child parts and reinforcement before the check runs, only objects matching the named filter are selected and checked | `min_distance` (float, mm, default: `0.0`), `between_parts` (bool, default: `true`), `between_reference_models` (bool, default: `false`), `objects_inside_reference_models` (bool, default: `false`), `filter_name` (str) - all optional |
| Operations | `run_macro` | Run a Tekla macro by filename | **`macro_name`** (str) |
| Drawings | `get_drawings` | Get drawings with optional filtering | `drawing_type` (str: `G`/`A`/`W`/`C`/`M`), `name_filter` (dict), `mark_filter` (dict), `title1_filter` (dict), `title2_filter` (dict), `title3_filter` (dict) - all optional |
| Drawings | `get_drawing_properties` | Get properties of drawings by mark list, or the currently selected drawings if omitted | `marks` (list[str], optional) |
| Drawings | `detect_collisions_between_marks` | Detect mark collisions in drawings; colliding marks are coloured red | `marks` (list[str], optional - uses selected drawings if omitted) |
| Drawings | `print_drawings` | Print drawings to PDF with automatic paper size detection (A4–A0) | `marks` (list[str]), `output_filename` (str), `output_folder` (str), `printer_attributes` (dict) - all optional |
| Modeling | `place_beams` | Place one or more beams | **`beams`** (list): each item has **`start_point`**, **`end_point`**, **`profile`**, **`material`**, **`tekla_class`** (int); optional: `start_point_offset`, `end_point_offset`, `name`, `position`, `part_number`, `assembly_number` |
| Modeling | `place_columns` | Place one or more columns | **`columns`** (list): each item has **`base_point`**, **`height`** (float, mm), **`profile`**, **`material`**, **`tekla_class`** (int); optional: `start_point_offset`, `end_point_offset`, `name`, `position`, `part_number`, `assembly_number` |
| Modeling | `place_panels` | Place one or more wall panels | **`panels`** (list): each item has **`start_point`**, **`end_point`**, **`profile`**, **`material`**, **`tekla_class`** (int); optional: `start_point_offset`, `end_point_offset`, `name`, `position`, `part_number`, `assembly_number` |
| Modeling | `place_slabs` | Place one or more slabs | **`slabs`** (list): each item has **`points`** (list of ≥3 points), **`profile`**, **`material`**, **`tekla_class`** (int); optional: `name`, `position`, `part_number`, `assembly_number` |
| Modeling | `move_elements` | Move or copy selected elements by a displacement vector. Assemblies are expanded to all constituent parts recursively. `copy=true` keeps originals and creates new elements at the displaced position | `dx` (float, mm, default: `0`), `dy` (float, mm, default: `0`), `dz` (float, mm, default: `0`), `copy` (bool, default: `false`) - all optional |
| Modeling | `place_grid` | Place a rectangular grid in the Tekla model | **`x`** (list[float], mm), **`y`** (list[float], mm), `z` (list[float], mm), `x_labels` (list[str]), `y_labels` (list[str]), `z_labels` (list[str]), `origin` (PointInput), `name` (str) |
| Modeling | `delete_selected` | Delete all selected elements | - |

## Resources

| Resource | Description |
|----------|-------------|
| `project://context` | Index of project context Markdown files (name, description, file key) |
| `project://context/{file}` | Full content of a specific project context Markdown file |
| `tekla://components` | Mapping of Tekla component name → config key for all components configured on the server |
| `tekla://components/{component_key}` | Description and `custom_properties` schema (attribute keys, types, allowed values) for a specific component |
| `tekla://catalog/materials` | All available material names from the Tekla material catalog |
| `tekla://catalog/rebars` | All available rebar grades and sizes from the Tekla rebar catalog |
| `tekla://macros` | Available Tekla macro filenames from configured directories |
| `tekla://element_types` | Element types with their Tekla class numbers from `element_types.json` |
| `tekla://filters/selection` | Available Tekla selection filter names (`.SObjGrp` files) |
| `tekla://filters/view` | Available Tekla view filter names (`.VObjGrp` files) |
| `tekla://phases` | All phases in the current model (number, name, comment) and the active phase number |
| `tekla://grids` | Rectangular grid data: guid, name, X/Y/Z axes with coordinates and labels |
| `tekla://connection_status` | Current Tekla connection status: connected (bool), message |

Filter resources search in:
- `XS_FIRM` advanced option directories
- `XS_PROJECT` advanced option directories
- Model attributes directory (`./attributes`)
