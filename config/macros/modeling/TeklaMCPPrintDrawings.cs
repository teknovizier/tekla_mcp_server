#pragma warning disable 1633 // Unrecognized #pragma directive
#pragma reference "Tekla.Macros.Wpf.Runtime"
#pragma reference "Tekla.Macros.Akit"
#pragma reference "Tekla.Macros.Runtime"
#pragma reference "Tekla.Structures.Drawing"
#pragma warning restore 1633 // Unrecognized #pragma directive

using System;
using System.Collections.Generic;
using System.IO;
using Tekla.Structures.Drawing;

namespace UserMacros {
    public sealed class Macro {
        [Tekla.Macros.Runtime.MacroEntryPointAttribute()]
        public static void Run(Tekla.Macros.Runtime.IMacroRuntime runtime) {
            Tekla.Macros.Akit.IAkitScriptHost akit = runtime.Get<Tekla.Macros.Akit.IAkitScriptHost>();
            Tekla.Macros.Wpf.Runtime.IWpfMacroHost wpf = runtime.Get<Tekla.Macros.Wpf.Runtime.IWpfMacroHost>();

            // The caller reads this file once the macro has finished: "OK" or "ERROR: <reason>"
            string resultPath = @".\TeklaMCPData\print.result";
            try {
                string printPath = @".\TeklaMCPData\print.tmp";
                if (!File.Exists(printPath)) {
                    File.WriteAllText(resultPath, "ERROR: print.tmp not found");
                    return;
                }

                string[] lines = File.ReadAllLines(printPath);

                // Line 0 carries the print setting name, fall back to the default
                string settingName = "TEKLA_MCP_PDF_BASE";
                if (lines.Length > 0 && lines[0].StartsWith("SETTING=")) {
                    settingName = lines[0].Substring("SETTING=".Length);
                }

                // Remaining lines are drawing marks, one per line
                List<string> marks = new List<string>();
                for (int i = 1; i < lines.Length; i++) {
                    if (lines[i].Length > 0 && !marks.Contains(lines[i])) {
                        marks.Add(lines[i]);
                    }
                }
                if (marks.Count == 0) {
                    File.WriteAllText(resultPath, "ERROR: no drawing marks in print.tmp");
                    return;
                }

                string searchText = "\"" + marks[0] + "\"";
                for (int i = 1; i < marks.Count; i++) {
                    searchText += " OR \"" + marks[i] + "\"";
                }

                wpf.InvokeCommand("CommandRepository", "Drawing.DrawingList");
                wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_SearchBox").As.TextBox.SetText(searchText);
                var grid = wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_DataGridControl");

                // The search is a loose text match across all columns, so it can list drawings
                // that were not asked for. Select each listed row on its own, read its mark back
                // and keep only exact matches
                List<int> rows = new List<int>();
                List<string> found = new List<string>();
                DrawingHandler drawingHandler = new DrawingHandler();
                for (int row = 0; found.Count < marks.Count; row++) {
                    try {
                        grid.As.DataGrid.NewSelection.With(row).Invoke();
                    } catch (OperationCanceledException) {
                        // Selecting past the last listed row times out
                        break;
                    }
                    DrawingEnumerator selected = drawingHandler.GetDrawingSelector().GetSelected();
                    if (!selected.MoveNext()) {
                        break;
                    }
                    string mark = selected.Current.Mark;
                    if (marks.Contains(mark) && !found.Contains(mark)) {
                        found.Add(mark);
                        rows.Add(row);
                    }
                }

                if (found.Count < marks.Count) {
                    List<string> missing = new List<string>();
                    foreach (string mark in marks) {
                        if (!found.Contains(mark)) {
                            missing.Add(mark);
                        }
                    }
                    File.WriteAllText(resultPath, "ERROR: drawings not found in Document Manager: " + string.Join(", ", missing.ToArray()));
                    return;
                }

                var selection = grid.As.DataGrid.NewSelection;
                foreach (int row in rows) {
                    selection = selection.With(row);
                }
                selection.Invoke();

                grid.As.ContextMenu.Find("AID_DocMgr_Print").As.Button.Invoke();
                wpf.View("DPMPrinterFeature.DPMPrinterViewWindow").Find("AID_PDFPD_LoadSaveCombo").As.ComboBox.SetText(settingName);
                wpf.View("DPMPrinterFeature.DPMPrinterViewWindow").Find("AID_PDFPD_PrintButton").As.Button.Invoke();
                File.WriteAllText(resultPath, "OK");
            } catch (Exception e) {
                // Report instead of letting Tekla show a modal error that blocks later macros
                File.WriteAllText(resultPath, "ERROR: " + e.GetType().Name + ": " + e.Message);
            }
        }
    }
}
