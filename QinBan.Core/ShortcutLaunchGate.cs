namespace QinBan.Core;
public enum ShortcutDecision { Ignored, WaitForRelease, Start, Cancelled }
public sealed record ShortcutState(bool Authorized, bool TargetForeground, bool ShiftDown, bool EnterDown,
    bool OtherModifierDown, bool StopRegistered, bool StartRegistered, bool Busy = false);
public sealed class ShortcutLaunchGate
{
    public bool Pending { get; private set; }
    public string Reason { get; private set; } = "";
    public ShortcutDecision Request(ShortcutState state)
    {
        if (Pending) return ShortcutDecision.Ignored;
        Pending = true; return Poll(state);
    }
    public ShortcutDecision Poll(ShortcutState state)
    {
        if (!Pending) return ShortcutDecision.Ignored;
        string? failure = !state.Authorized ? "快捷演奏未授权或曲谱不可演奏" : !state.StopRegistered ? "F9 未注册" :
            !state.StartRegistered ? "Shift+Enter 未注册" : !state.TargetForeground ? "目标游戏不在前台" :
            state.OtherModifierDown ? "请松开 Ctrl/Alt/Win" : state.Busy ? "已有播放正在运行" : null;
        if (failure != null) { Pending = false; Reason = failure; return ShortcutDecision.Cancelled; }
        if (state.ShiftDown || state.EnterDown) return ShortcutDecision.WaitForRelease;
        Pending = false; Reason = ""; return ShortcutDecision.Start;
    }
    public void Cancel() { Pending = false; Reason = "已取消快捷启动"; }
}
