using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Interop;
using QinBan.Core;
namespace QinBan.Desktop;

public sealed record GameWindow(nint Handle, int ProcessId, string ProcessName, string Title)
{
    public override string ToString() => $"{Title} · PID {ProcessId}";
}

public static class GameWindows
{
    private static readonly HashSet<string> AllowedNames = new(StringComparer.OrdinalIgnoreCase) { "YuanShen", "GenshinImpact" };
    [DllImport("user32.dll")] public static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool IsWindow(nint hwnd);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint hwnd, out uint process);
    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(nint hwnd, StringBuilder text, int maximum);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(nint hwnd);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumCallback callback, nint parameter);
    private delegate bool EnumCallback(nint hwnd, nint parameter);
    public static List<GameWindow> List()
    {
        var windows = new List<GameWindow>();
        EnumWindows((hwnd, _) =>
        {
            if (!IsWindowVisible(hwnd)) return true;
            GetWindowThreadProcessId(hwnd, out uint pid);
            try
            {
                using var process = Process.GetProcessById((int)pid);
                if (!AllowedNames.Contains(process.ProcessName)) return true;
                var title = new StringBuilder(512); GetWindowText(hwnd, title, title.Capacity);
                if (title.Length > 0) windows.Add(new(hwnd, (int)pid, process.ProcessName, title.ToString()));
            }
            catch (ArgumentException) { } // Window/process disappeared during enumeration.
            return true;
        }, 0);
        return windows;
    }
    private static bool IsTarget(GameWindow window)
    {
        if (!AllowedNames.Contains(window.ProcessName) || !IsWindow(window.Handle)) return false;
        GetWindowThreadProcessId(window.Handle, out uint pid);
        return pid == window.ProcessId;
    }
    private static bool Down(int key) => (GetAsyncKeyState(key) & 0x8000) != 0;
    public static ShortcutState ReadShortcutState(GameWindow window, bool authorized, bool stopRegistered, bool startRegistered, bool busy) =>
        new(authorized, IsTarget(window) && GetForegroundWindow() == window.Handle, Down(0x10), Down(0x0D),
            new[] { 0x11, 0x12, 0x5B, 0x5C }.Any(Down), stopRegistered, startRegistered, busy);
    public static InputGuard Check(GameWindow window)
    {
        if (!IsTarget(window)) return new(false, "原神目标窗口已关闭、进程已变化或不受支持。");
        if (GetForegroundWindow() != window.Handle) return new(false, "原神失去前台焦点，已停止并释放按键。");
        if (new[] { 0x10, 0x11, 0x12, 0x5B, 0x5C }.Any(Down))
            return new(false, "检测到 Shift/Ctrl/Alt/Win 修饰键，已停止以避免组合快捷键。");
        return new(true);
    }
}

// Foreground-only Windows keyboard sink. Never armed during automated tests or preview.
public sealed class WindowsKeySink : IKeySink, IDisposable
{
    private readonly GameWindow _window;
    private readonly string _allowedKeys;
    private readonly HashSet<char> _held = [];
    private bool _armed;
    public int SendAttempts { get; private set; }
    public string? ReleaseError { get; private set; }
    public WindowsKeySink(GameWindow window, string instrumentId = "windsong")
    {
        _window = window;
        var profile = InstrumentCatalog.Get(instrumentId);
        if (!profile.CanAutoPlay) throw new InvalidOperationException("此乐器的游戏键位尚未核验，拒绝授权输出。");
        _allowedKeys = new string(profile.Keys.Select(k => k.Key).ToArray());
    }
    public void Arm()
    {
        var guard = GameWindows.Check(_window);
        if (!guard.Allowed) throw new InvalidOperationException(guard.Reason);
        _armed = true;
    }
    public void Press(IReadOnlyList<char> keys)
    {
        if (!_armed) throw new InvalidOperationException("按键输出尚未授权。");
        var guard = GameWindows.Check(_window);
        if (!guard.Allowed) throw new InvalidOperationException(guard.Reason);
        if (keys.Any(k => !_allowedKeys.Contains(k))) throw new InvalidOperationException("拒绝发送乐器键位以外的按键。");
        foreach (char key in keys) _held.Add(key); // Include partial sends in the emergency release set.
        Send(keys, false);
    }
    public void Release(IReadOnlyList<char> keys)
    {
        var actual = keys.Where(k => _held.Contains(k)).Distinct().ToArray();
        if (actual.Length == 0) return;
        Send(actual, true);
        foreach (char key in actual) _held.Remove(key);
    }
    public void ReleaseAll()
    {
        var actual = _held.ToArray();
        if (actual.Length == 0) return;
        try { Send(actual, true); _held.Clear(); }
        catch (Exception ex) { ReleaseError = ex.Message; } // Kept visible in completion status; not silently discarded.
    }
    private void Send(IReadOnlyList<char> keys, bool up)
    {
        var input = keys.Select(key => new Input
        {
            Type = 1,
            Data = new InputUnion { Keyboard = new KeyboardInput { Scan = (ushort)MapVirtualKey(key, 0), Flags = 0x0008u | (up ? 0x0002u : 0) } }
        }).ToArray();
        SendAttempts++;
        uint sent = SendInput((uint)input.Length, input, Marshal.SizeOf<Input>());
        if (sent != input.Length) throw new InvalidOperationException($"系统仅接受 {sent}/{input.Length} 个按键事件（错误 {Marshal.GetLastWin32Error()}）。可能存在权限级别差异；不会自动提权或切换后台输入。");
    }
    public void Dispose() { ReleaseAll(); _armed = false; }
    [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(uint count, Input[] inputs, int size);
    [DllImport("user32.dll")] private static extern uint MapVirtualKey(uint code, uint type);
    [StructLayout(LayoutKind.Sequential)] private struct Input { public uint Type; public InputUnion Data; }
    [StructLayout(LayoutKind.Explicit)] private struct InputUnion
    {
        [FieldOffset(0)] public KeyboardInput Keyboard;
        [FieldOffset(0)] public MouseInput Mouse;
    }
    [StructLayout(LayoutKind.Sequential)] private struct KeyboardInput { public ushort Virtual, Scan; public uint Flags, Time; public nint Extra; }
    [StructLayout(LayoutKind.Sequential)] private struct MouseInput { public int X, Y; public uint Data, Flags, Time; public nint Extra; }
    public static int InputStructureSize => Marshal.SizeOf<Input>();
}

public sealed class GlobalHotkeys : IDisposable
{
    private readonly nint _handle;
    private readonly HwndSource _source;
    private readonly Action _pause, _stop, _start;
    public const uint StartModifiers = 0x4004; // MOD_SHIFT | MOD_NOREPEAT
    public const uint StartVirtualKey = 0x0D; // VK_RETURN
    public bool StartRegistered { get; }
    public bool PauseRegistered { get; }
    public bool StopRegistered { get; }
    public GlobalHotkeys(nint handle, Action pause, Action stop, Action start)
    {
        _handle = handle; _source = HwndSource.FromHwnd(handle); _pause = pause; _stop = stop; _start = start;
        PauseRegistered = RegisterHotKey(handle, 1001, 0x4000, 0x77);
        StopRegistered = RegisterHotKey(handle, 1002, 0x4000, 0x78);
        StartRegistered = RegisterHotKey(handle, 1003, StartModifiers, StartVirtualKey);
        _source.AddHook(Hook);
    }
    private nint Hook(nint hwnd, int msg, nint param, nint data, ref bool handled)
    {
        if (msg == 0x0312 && param == 1001) { _pause(); handled = true; }
        if (msg == 0x0312 && param == 1003) { _start(); handled = true; }
        if (msg == 0x0312 && param == 1002) { _stop(); handled = true; }
        return 0;
    }
    public void Dispose()
    {
        _source.RemoveHook(Hook);
        if (PauseRegistered) UnregisterHotKey(_handle, 1001);
        if (StopRegistered) UnregisterHotKey(_handle, 1002);
        if (StartRegistered) UnregisterHotKey(_handle, 1003);
    }
    [DllImport("user32.dll", SetLastError = true)] private static extern bool RegisterHotKey(nint hwnd, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(nint hwnd, int id);
}
