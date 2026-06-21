#pragma warning disable 1633 // Unrecognized #pragma directive
#pragma reference "Tekla.Macros.Wpf.Runtime"
#pragma reference "Tekla.Macros.Akit"
#pragma reference "Tekla.Macros.Runtime"
#pragma warning restore 1633 // Unrecognized #pragma directive

namespace UserMacros {
    public sealed class Macro {
        [Tekla.Macros.Runtime.MacroEntryPointAttribute()]
        public static void Run(Tekla.Macros.Runtime.IMacroRuntime runtime) {
            Tekla.Macros.Akit.IAkitScriptHost akit = runtime.Get<Tekla.Macros.Akit.IAkitScriptHost>();
            Tekla.Macros.Wpf.Runtime.IWpfMacroHost wpf = runtime.Get<Tekla.Macros.Wpf.Runtime.IWpfMacroHost>();
            wpf.View("DocumentManager.MainWindow").Find("AID_DOCMAN_DataGridControl").As.ContextMenu.Find("AID_DocMgr_Export").As.Button.Invoke();
            wpf.View("DrawingExport.UIFeature.MainContentView").Find("AID_SettingName", "TEKLA_MCP_DXF_EXPORT").As.SelectorItem.Select();
            wpf.View("DrawingExport.UIFeature.ExportOptionsView").Find("AID_DwgExport_BottomControl", "AID_DwgExport_ExportButton").As.Button.Invoke();
        }
    }
}
