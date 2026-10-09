using System.IO;
using System.Windows;
namespace QinBan.Desktop;
public partial class App : Application
{
    private Mutex? _instance;
    private bool _ownsInstance;
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        string? data = null; bool uiTest = e.Args.Contains("--ui-test");
        int at = Array.IndexOf(e.Args, "--data-dir"); if (at >= 0 && at + 1 < e.Args.Length) data = e.Args[at + 1];
        string canonicalData = Path.GetFullPath(data ?? Path.Combine(AppContext.BaseDirectory, "UserData")).ToUpperInvariant();
        string instanceId = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(canonicalData)))[..24];
        _instance = new Mutex(true, "Local\\QinBan." + instanceId, out _ownsInstance);
        if (!_ownsInstance) { MessageBox.Show("此数据目录已有琴伴实例在运行。请使用现有窗口，避免并发改写曲库和热键冲突。", "琴伴"); Shutdown(0); return; }
        DispatcherUnhandledException += (_, args) =>
        {
            if (MainWindow is MainWindow main) main.EmergencyStop("程序异常，已请求释放按键");
            if (MainWindow is MainWindow validation && validation.HandleValidationError(args.Exception)) { args.Handled = true; return; }
            MessageBox.Show(args.Exception.Message, "琴伴 · 错误", MessageBoxButton.OK, MessageBoxImage.Error);
            args.Handled = true;
        };
        string? catalog = null;
        int catalogAt = Array.IndexOf(e.Args, "--catalog-dir");
        if (catalogAt >= 0)
        {
            if (!uiTest || catalogAt + 1 >= e.Args.Length) { Shutdown(2); return; }
            catalog = e.Args[catalogAt + 1];
        }
        try { var window = new MainWindow(data, uiTest, catalog); MainWindow = window; window.Show(); }
        catch (Exception ex) { MessageBox.Show("启动失败，未发送按键。\n\n" + ex.Message, "琴伴", MessageBoxButton.OK, MessageBoxImage.Error); Shutdown(1); }
    }
    protected override void OnExit(ExitEventArgs e)
    {
        if (_ownsInstance) _instance?.ReleaseMutex();
        _instance?.Dispose(); base.OnExit(e);
    }
}
