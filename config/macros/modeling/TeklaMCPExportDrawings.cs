#pragma warning disable 1633 // Unrecognized #pragma directive
#pragma reference "Tekla.Macros.Wpf.Runtime"
#pragma reference "Tekla.Macros.Akit"
#pragma reference "Tekla.Macros.Runtime"
#pragma warning restore 1633 // Unrecognized #pragma directive

using System.Collections.Generic;
using System.IO;

namespace UserMacros {
    public sealed class Macro {
        [Tekla.Macros.Runtime.MacroEntryPointAttribute()]
        public static void Run(Tekla.Macros.Runtime.IMacroRuntime runtime) {
            Tekla.Macros.Akit.IAkitScriptHost akit = runtime.Get<Tekla.Macros.Akit.IAkitScriptHost>();
            Tekla.Macros.Wpf.Runtime.IWpfMacroHost wpf = runtime.Get<Tekla.Macros.Wpf.Runtime.IWpfMacroHost>();

            string exportPath = @".\TeklaMCPData\export.tmp";
            if (!File.Exists(exportPath)) {
                return;
            }

            string[] lines = File.ReadAllLines(exportPath);
            if (lines.Length < 2) {
                return;
            }

            // Line 0 carries the export setting name, fall back to the default
            string settingName = "TEKLA_MCP_EXPORT_BASE";
            if (lines[0].StartsWith("SETTING=")) {
                settingName = lines[0].Substring("SETTING=".Length);
            }

            // Remaining lines are drawing marks, one per line
            List<string> marks = new List<string>();
            for (int i = 1; i < lines.Length; i++) {
                if (lines[i].Length > 0) {
                    marks.Add(lines[i]);
                }
            }
            if (marks.Count == 0) {
                return;
            }

            string searchText = "\"" + marks[0] + "\"";
            for (int i = 1; i < marks.Count; i++) {
                searchText += " OR \"" + marks[i] + "\"";
            }

            wpf.InvokeCommand("CommandRepository", "Drawing.DrawingList");
            wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_SearchBox").As.TextBox.SetText(searchText);
            var grid = wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_DataGridControl");
            grid.As.DataGrid.NewSelection.WithRange(0, marks.Count).Invoke();
            grid.As.ContextMenu.Find("AID_DocMgr_Export").As.Button.Invoke();
            wpf.View("DrawingExport.UIFeature.MainContentView").Find("AID_SettingName", settingName).As.SelectorItem.Select();
            wpf.View("DrawingExport.UIFeature.ExportOptionsView").Find("AID_DwgExport_BottomControl", "AID_DwgExport_ExportButton").As.Button.Invoke();
        }
    }
}
