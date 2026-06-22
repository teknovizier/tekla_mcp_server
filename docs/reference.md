# Reference

Complete reference for tools and resources available in Tekla MCP Server.

## Tools

Safety annotations:
- 🔒 Read-only - reads model data without modifying it, kept visible in read‑only mode
- ✏️ Creative - creates new model objects without modifying or deleting existing data
- ⚠️ Destructive - modifies or deletes existing model data

Parameter notation:
**`param`** = required, `param` = optional.
Type and default shown where relevant.

| Category | Tool | Description | Parameters |
|----------|------|-------------|------------|
| Selection | 🔒 `select_elements_by_filter` | Select elements by type, Tekla class, name, profile, material, finish, phase, part/assembly prefix/number. Supports AND/OR logic | `element_type` (str), `tekla_classes` (int \| list[int]), `standard_string_filters` (dict), `standard_numeric_filters` (dict), `custom_string_filters` (dict), `custom_numeric_filters` (dict), `combine_with` (str, default: `"AND"`) - all optional |
| Selection | 🔒 `select_elements_by_filter_name` | Select elements using a saved Tekla filter | **`filter_name`** (str) |
| Selection | 🔒 `select_elements_by_guid` | Select elements by GUID | **`guids`** (list[str]) |
| Selection | 🔒 `select_elements_assemblies_or_main_parts` | Switch selection to assemblies or main parts for the currently selected elements | **`mode`** (str): `"Assembly"` \| `"Main Part"` |
| Components | ✏️ `put_components` | Insert a Tekla component on selected elements. Supports semantic attribute mapping and intelligent defaults (e.g. anchor type by weight) | **`component_name`** (str), `properties_set` (str, default: `"standard"`), `custom_properties` (dict) |
| Components | 🔒 `get_components` | Get all components attached to selected elements. Returns name, number, attribute schema and current values | - |
| Components | ⚠️ `modify_components` | Modify attributes of existing components on selected elements | **`component_name`** (str), **`custom_properties`** (dict) |
| Components | ⚠️ `remove_components` | Remove all components with the given name from selected elements | **`component_name`** (str) |
| Properties | 🔒 `get_elements_properties` | Retrieve structured data about selected elements. `mode="flat"` (default) returns flat tables (assemblies, parts, reinforcement, IFC objects) with UDAs and report properties. `mode="snapshot"` returns full snapshots with all report properties, all UDAs, and nested reinforcement - use for convention checking. `mode="guids_only"` returns just each element's GUID (skips property extraction) | `report_props_definitions` (list[str]), `mode` (str: `"flat"` \| `"snapshot"` \| `"guids_only"`, default: `"flat"`) - all optional |
| Properties | ⚠️ `set_elements_properties` | Set properties on selected elements. Parts: name, profile, material, finish, class, numbering, phase. Assemblies: name, numbering, phase. UDAs supported via `user_properties` | `name` (str), `profile` (str), `material` (str), `tekla_class` (int), `finish` (str), `part_prefix` (str), `part_start_number` (int), `assembly_prefix` (str), `assembly_start_number` (int), `phase` (int), `user_properties` (dict) - all optional |
| Properties | 🔒 `get_elements_cut_parts` | Find all boolean cut parts in selected elements, grouped by parent part with GUIDs and profiles | - |
| Properties | ⚠️ `clear_elements_udas` | Clear UDAs from selected parts and assemblies. Clears all UDAs if no names provided | `uda_names` (list[str], optional) |
| Properties | 🔒 `get_elements_coordinates` | Get coordinates of selected elements: start/end points and offsets for beams, contour points for slabs | - |
| Properties | 🔒 `get_elements_bounding_boxes` | Get axis-aligned bounding boxes for selected elements. Returns per element: `element_type` (Tekla C# class name), `min`/`max` corners `{x, y, z}`, `centroid` `{x, y, z}` (mm) | - |
| Properties | 🔒 `compare_elements` | Compare two selected elements and return detailed differences (properties, UDAs, cut parts, welds, reinforcements) | `ignore_numbering` (bool, default: `false`) |
| Properties | ⚠️ `copy_properties_from_ifc` | Copy properties from IFC reference objects to matching Tekla elements by bounding-box overlap | **`user_properties`** (dict[str, str]): IFC property name → Tekla UDA name |
| View | 🔒 `draw_elements_labels` | Draw temporary labels on selected elements. Parts show position, GUID, name, profile, material, finish, class, weight. Assemblies show position, GUID, name, weight | `label` (str, optional), `custom_label` (str, optional) |
| View | 🔒 `zoom_to_selection` | Zoom the active rendered view to fit selected elements | - |
| View | 🔒 `redraw_view` | Redraw the active view | - |
| View | 🔒 `show_only_selected` | Hide everything except selected elements in the active view | - |
| View | 🔒 `hide_selected` | Hide selected elements in the active view | - |
| View | 🔒 `color_selected` | Color selected elements with an RGB colour | **`red`** (int, 0–255), **`green`** (int, 0–255), **`blue`** (int, 0–255) |
| View | 🔒 `apply_view_filter` | Apply a saved view filter to the active view | **`filter_name`** (str) |
| Operations | ⚠️ `cut_elements_with_cutters` | Boolean-cut selected elements using parts identified by class or GUID | `cutter_class` (int \| null), `cutter_guids` (list[str] \| null) - exactly one required, `delete_cutting_parts` (bool, default: `false`) |
| Operations | ⚠️ `convert_cut_parts_to_real_parts` | Convert all cut parts in selected elements into standalone model parts | - |
| Operations | 🔒 `check_for_orphans` | Find orphaned embedded subassemblies or rebars inside the bounding box of selected elements. Returns `{object_guid, target_guid}` pairs to feed to the attach tools | **`mode`** (str): `"subassemblies"` \| `"rebars"` |
| Operations | ⚠️ `attach_assemblies` | Attach specified assemblies to target assemblies | **`pairs`** (list): each item has **`object_guid`** (str), **`target_guid`** (str) |
| Operations | ⚠️ `attach_rebars` | Attach specified reinforcement to target assemblies' main parts | **`pairs`** (list): each item has **`object_guid`** (str), **`target_guid`** (str) |
| Operations | 🔒 `check_for_invalid_objects` | Find invalid objects (missing profile/material, bad geometry, no parent) among selected elements and their bounding boxes | - |
| Operations | 🔒 `clash_check` | Run Tekla's clash check against the current selection. Returns one record per detected clash with `object1`, `object2` (each: `guid`, `name`, `profile`, `material`, `tekla_class`, `top_assembly_guid`), `clash_type`, and `overlap` (only for `CLASH_TYPE_CLASH`). When `filter_name` is supplied, selected assemblies are expanded to their child parts and reinforcement before the check runs, only objects matching the named filter are selected and checked | `min_distance` (float, mm, default: `0.0`), `between_parts` (bool, default: `true`), `between_reference_models` (bool, default: `false`), `objects_inside_reference_models` (bool, default: `false`), `filter_name` (str) - all optional |
| Operations | 🔒 `create_report` | Create a Tekla report from the current selection using a report template. Waits for the file to appear and returns `content_preview` (configurable via `reports.preview_max_chars`) + `size_bytes`. When `output_folder` is omitted, writes to `XS_REPORT_OUTPUT_DIRECTORY` | **`template_name`** (str), `output_filename` (str, optional - defaults to template name), `output_folder` (str, optional), `title1`/`title2`/`title3` (str) - optional, `return_full_content` (bool, default: `False`) |
| Operations | ⚠️ `run_macro` | Run a Tekla macro by filename | **`macro_name`** (str) |
| Operations | 🔒 `select_model_objects_from_drawings` | Select the model objects corresponding to the currently selected drawing objects | - |
| Drawings | 🔒 `get_drawings` | Get drawings with optional filtering | `drawing_type` (str: `G`/`A`/`W`/`C`/`M`), `name_filter` (dict), `mark_filter` (dict), `title1_filter` (dict), `title2_filter` (dict), `title3_filter` (dict) - all optional |
| Drawings | 🔒 `get_drawings_properties` | Get properties of drawings by mark list, or the currently selected drawings if omitted | `marks` (list[str], optional) |
| Drawings | ⚠️ `set_drawings_properties` | Set name, titles and UDAs on drawings by mark list, or the currently selected drawings if omitted. Does not require any drawing to be open | `marks` (list[str], optional), `name` (str), `title1`/`title2`/`title3` (str), `user_properties` (dict) - all optional |
| Drawings | ⚠️ `set_drawings_issue_state` | Issue or unissue drawings by mark list, or the currently selected drawings if omitted. Drawing-list level action, no drawing needs to be open | `marks` (list[str], optional), `action` (str: `"issue"`/`"unissue"`, default: `"issue"`) |
| Drawings | ⚠️ `update_drawings` | Update drawings from the model by mark list, or the currently selected drawings if omitted. Already up-to-date drawings are skipped, not errors. None of the target drawings can be the active drawing | `marks` (list[str], optional) |
| Drawings | ⚠️ `check_drawing_collisions` | Detect mark collisions in drawings selected in the Document Manager (or by `marks`) by exporting each to DXF and analysing geometry overlaps. None of the target drawings can be the active drawing, and all must be up to date. Magenta revision clouds are drawn at every found collision | `marks` (list[str], optional) |
| Drawings | 🔒 `print_drawings` | Print drawings to PDF with automatic paper size/orientation/multi-sheet tiling detection (A0-A4, or a clean tiling of one). With `print_settings`, customer settings are used as-is | `marks` (list[str], optional), `print_settings` (str, optional) |
| Drawings | 🔒 `export_drawings` | Export drawings to DWG/DXF/DGN via the Document Manager export macro. With `export_settings`, customer settings are used as-is | `marks` (list[str], optional), `drawing_format` (str: `dxf`/`dwg`/`dgn`, default: `dwg`), `version` (str: `2000`/`2004`/`2007`/`2010`/`2013`, default: `2010`), `export_settings` (str, optional) |
| Drawings | 🔒 `open_drawing` | Open a drawing by its mark in Tekla's drawing editor. | **`mark`** (str) |
| Drawings | 🔒 `close_drawing` | Close the active drawing | `save` (bool, default: `true`) |
| Drawings | 🔒 `get_drawing_views` | List all views in the active drawing with type, scale, position, size and display settings. Includes the sheet view (`is_sheet=true`, with its own size), needed to read title block annotations via `get_view_annotations`. Returns the total sheet count too. If the sheet combines multiple standard-size pages, each model view gets a `sheet_number` (1-based, top-left page first, or null if outside the page grid) | - |
| Drawings | 🔒 `get_view_objects` | List the model objects (parts, rebars, etc.) shown in a view, resolved to name/profile/material/class. Parts of an embedded detail sub assembly are reported once as the subassembly. Model objects only, not annotations. No geometry | **`view_key`** (str), `limit` (int, default: `200`) |
| Drawings | 🔒 `get_view_annotations` | Read the marks, dimensions and text in a view with their content (mark string, dimension value, text). Marks with no readable text (e.g. WeldMark, LevelMark) report content "N/A". For the sheet view, only `text`/`graphics` are returned (marks/dimensions are aggregated per child view). No geometry | **`view_key`** (str), `type_filter` (str: `all`/`dimensions`/`marks`/`text`/`graphics`, default: `all`), `limit` (int, default: `200`) |
| Drawings | ⚠️ `move_view` | Move a view by an offset (mm) | **`view_key`** (str), **`dx`** (float, mm), **`dy`** (float, mm) |
| Drawings | ⚠️ `align_section_views` | Align section views in projection with the view they were cut from: a horizontal cut aligns the section's X position, a vertical cut aligns Y (only one coordinate changes). Parent found by matching the section view's name to a section mark of the same name. A section that overlaps the parent on the non-aligned axis by more than `overlap_tolerance` is treated as intentionally placed outside its projection lane (e.g. parked in a row below the parent) and left as-is. `view_keys` aligns only the listed section views | `view_keys` (list[str], optional - aligns all when omitted), `overlap_tolerance` (float, default: `5.0`, mm) |
| Drawings | ⚠️ `set_views_attributes` | Set display attributes (scale, opening symbols, reflected/undeformed/unfolded) on one or more drawing views | **`views_attributes`** (list): each item has **`view_key`** (str) and at least one of `scale` (float), `show_part_openings_or_recess_symbol` (bool), `reflected_view` (bool), `undeformed_view` (bool), `unfolded_view` (bool) |
| Drawings | ⚠️ `delete_views` | Delete one or more views from the active drawing | **`view_keys`** (list[str]) |
| Drawings | ⚠️ `delete_clouds` | Delete all clouds from model views and the sheet view | `view_keys` (list[str], optional - processes all views when omitted) |
| Modeling | ✏️ `place_beams` | Place one or more beams | **`beams`** (list): each item has **`start_point`**, **`end_point`**, **`profile`**, **`material`**, **`tekla_class`** (int); optional: `start_point_offset`, `end_point_offset`, `name`, `position`, `part_number`, `assembly_number` |
| Modeling | ✏️ `place_columns` | Place one or more columns | **`columns`** (list): each item has **`base_point`**, **`height`** (float, mm), **`profile`**, **`material`**, **`tekla_class`** (int); optional: `start_point_offset`, `end_point_offset`, `name`, `position`, `part_number`, `assembly_number` |
| Modeling | ✏️ `place_panels` | Place one or more wall panels | **`panels`** (list): each item has **`start_point`**, **`end_point`**, **`profile`**, **`material`**, **`tekla_class`** (int); optional: `start_point_offset`, `end_point_offset`, `name`, `position`, `part_number`, `assembly_number` |
| Modeling | ✏️ `place_slabs` | Place one or more slabs | **`slabs`** (list): each item has **`points`** (list of ≥3 points), **`profile`**, **`material`**, **`tekla_class`** (int); optional: `name`, `position`, `part_number`, `assembly_number` |
| Modeling | ⚠️ `move_elements` | Move selected elements by a displacement vector | `dx` (float, mm, default: `0`), `dy` (float, mm, default: `0`), `dz` (float, mm, default: `0`) - at least one must be non-zero |
| Modeling | ✏️ `copy_elements` | Copy selected elements to a new position defined by the displacement vector, keeping originals in place. Assemblies are expanded to all constituent parts recursively | `dx` (float, mm, default: `0`), `dy` (float, mm, default: `0`), `dz` (float, mm, default: `0`) - at least one must be non-zero |
| Modeling | ✏️ `place_grid` | Place a rectangular grid in the Tekla model | **`x`** (list[float], mm), **`y`** (list[float], mm), `z` (list[float], mm), `x_labels` (list[str]), `y_labels` (list[str]), `z_labels` (list[str]), `origin` (PointInput), `name` (str) |
| Modeling | ⚠️ `delete_selected` | Delete all selected elements | - |
| Modeling | ✏️ `create_phase` | Create a new phase in the Tekla model | **`phase_number`** (int), `name` (str, optional) |

## Resources

| Resource | Description |
|----------|-------------|
| `project://context` | Index of project context Markdown files (name, description, file key) |
| `project://context/{file}` | Full content of a specific project context Markdown file |
| `tekla://components` | Mapping of Tekla component name → config key for all components configured on the server |
| `tekla://components/{component_key}` | Description and `custom_properties` schema (attribute keys, types, allowed values) for a specific component |
| `tekla://catalog/materials` | All available material names from the Tekla material catalog |
| `tekla://catalog/rebars` | All available rebar grades and sizes from the Tekla rebar catalog |
| `tekla://macros` | Available Tekla macro filenames from `XS_MACRO_DIRECTORY` |
| `tekla://reports` | Available Tekla report template names (`.rpt` files) from `XS_TEMPLATE_DIRECTORY` |
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
