#pragma warning disable 1633 // Unrecognized #pragma directive
#pragma reference "Tekla.Macros.Wpf.Runtime"
#pragma reference "Tekla.Macros.Akit"
#pragma reference "Tekla.Macros.Runtime"
#pragma warning restore 1633 // Unrecognized #pragma directive

using System.IO;

namespace UserMacros {
    public sealed class Macro {
        [Tekla.Macros.Runtime.MacroEntryPointAttribute()]
        public static void Run(Tekla.Macros.Runtime.IMacroRuntime runtime) {
            Tekla.Macros.Akit.IAkitScriptHost akit = runtime.Get<Tekla.Macros.Akit.IAkitScriptHost>();
            Tekla.Macros.Wpf.Runtime.IWpfMacroHost wpf = runtime.Get<Tekla.Macros.Wpf.Runtime.IWpfMacroHost>();

            string marksPath = @".\TeklaMCPData\marks.tmp";
            if (!File.Exists(marksPath)) {
                return;
            }

            string[] marks = File.ReadAllLines(marksPath);
            if (marks.Length == 0) {
                return;
            }

            string searchText = "\"" + marks[0] + "\"";
            for (int i = 1; i < marks.Length; i++) {
                searchText += " OR \"" + marks[i] + "\"";
            }

            wpf.InvokeCommand("CommandRepository", "Drawing.DrawingList");
            wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_SearchBox").As.TextBox.SetText(searchText);
            var grid = wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_DataGridControl");
            grid.As.DataGrid.NewSelection.WithRange(0, marks.Length).Invoke();
            grid.As.ContextMenu.Find("AID_DocMgr_Export").As.Button.Invoke();
            wpf.View("DrawingExport.UIFeature.MainContentView").Find("AID_SettingName", "TEKLA_MCP_DXF_EXPORT").As.SelectorItem.Select();
            wpf.View("DrawingExport.UIFeature.ExportOptionsView").Find("AID_DwgExport_BottomControl", "AID_DwgExport_ExportButton").As.Button.Invoke();
        }
    }
}
