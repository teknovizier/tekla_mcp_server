#pragma warning disable 1633 // Unrecognized #pragma directive
#pragma reference "Tekla.Macros.Wpf.Runtime"
#pragma reference "Tekla.Macros.Runtime"
#pragma warning restore 1633 // Unrecognized #pragma directive

namespace UserMacros {
    public sealed class Macro {
        [Tekla.Macros.Runtime.MacroEntryPointAttribute()]
        public static void Run(Tekla.Macros.Runtime.IMacroRuntime runtime) {
            Tekla.Macros.Wpf.Runtime.IWpfMacroHost wpf = runtime.Get<Tekla.Macros.Wpf.Runtime.IWpfMacroHost>();
            try {
                wpf.View("DPMPrinterFeature.DPMPrinterViewWindow").As.Window.Close();
            } catch (System.Exception) {
                // The dialog never opened (the print macro failed early), and an uncaught
                // error here would show a modal Tekla dialog that blocks later macros
            }
        }
    }
}
