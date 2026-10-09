using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using QinBan.Core;
namespace QinBan.Desktop;

public partial class MainWindow
{
    private async Task RunScrollValidationAsync()
    {
        string[] args = Environment.GetCommandLineArgs(); int dataAt = Array.IndexOf(args, "--data-dir");
        if (!_uiTest || dataAt < 0 || dataAt + 1 >= args.Length
            || !Path.GetFullPath(args[dataAt + 1]).Equals(Path.GetFullPath(_store.DataDirectory), StringComparison.OrdinalIgnoreCase)
            || Path.GetFullPath(_store.DataDirectory).Equals(Path.Combine(AppContext.BaseDirectory, "UserData"), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("滚动验证仅允许 --ui-test 和独立 --data-dir，不发送原生按键。");
        string output = Path.GetDirectoryName(_store.DataDirectory)!;
        var results = new List<object>(); var traces = new List<object>(); int failures = 0;
        void Check(bool ok, string why) { if (!ok) throw new InvalidOperationException(why); }
        async Task Test(string name, Func<Task> action)
        {
            try { await action(); results.Add(new { name, status = "PASS" }); }
            catch (Exception ex) { failures++; results.Add(new { name, status = "FAIL", error = ex.ToString() }); }
        }
        try
        {
            Width = 1080; Height = 720; UpdateLayout(); await Task.Delay(100);
            var viewer = MetadataVisuals(SongList).OfType<ScrollViewer>().First();
            void Wheel(int delta)
            {
                var e = new MouseWheelEventArgs(Mouse.PrimaryDevice, Environment.TickCount, delta)
                { RoutedEvent = Mouse.PreviewMouseWheelEvent, Source = SongList };
                SongList.RaiseEvent(e);
                // RaiseEvent does not promote preview input to the bubbling event like physical input does.
                if (!e.Handled) viewer.RaiseEvent(new MouseWheelEventArgs(Mouse.PrimaryDevice, Environment.TickCount, delta)
                { RoutedEvent = Mouse.MouseWheelEvent, Source = viewer });
            }
            async Task Reset(double offset = 0)
            {
                await Task.Delay(240); viewer.ScrollToVerticalOffset(offset); UpdateLayout(); await Task.Delay(40);
            }
            await Test("Pixel scrolling preserves recycling virtualization", () =>
            {
                Check(VirtualizingPanel.GetScrollUnit(SongList) == ScrollUnit.Pixel, "List scroll unit is still Item");
                Check(ScrollViewer.GetCanContentScroll(SongList) && VirtualizingPanel.GetIsVirtualizing(SongList)
                    && VirtualizingPanel.GetVirtualizationMode(SongList) == VirtualizationMode.Recycling, "virtualization disabled");
                Check(viewer.ExtentHeight > SongList.Items.Count && viewer.ScrollableHeight > 100, "extent is not measured in pixels");
                Check(ScrollViewer.GetPanningMode(SongList) == PanningMode.VerticalOnly, "touch panning disabled");
                return Task.CompletedTask;
            });
            await Test("One wheel notch has multiple intermediate rendered offsets and preserves selection", async () =>
            {
                await Reset(); var selected = SongList.SelectedItem; double start = viewer.VerticalOffset;
                var offsets = new List<double>();
                ScrollChangedEventHandler record = (_, e) => { if (e.VerticalChange != 0) offsets.Add(viewer.VerticalOffset); };
                viewer.ScrollChanged += record;
                try
                {
                    Wheel(-120); double immediate = viewer.VerticalOffset;
                    Check(Math.Abs(immediate - start) < .01, "wheel jumped immediately instead of animating");
                    await Task.Delay(300); double end = viewer.VerticalOffset;
                    traces.Add(new { name = "one-notch", start, immediate, end, offsets });
                    Check(end > start && end - start < 150, "unexpected wheel distance");
                    Check(offsets.Count(v => v > start + .01 && v < end - .01) >= 3, "no continuous intermediate offsets");
                    Check(offsets.Zip(offsets.Skip(1)).All(pair => pair.Second >= pair.First), "downward scroll reversed");
                    Check(Equals(selected, SongList.SelectedItem), "wheel changed selection");
                    Capture(Path.Combine(output, "smooth-scroll-mid-list.png"));
                }
                finally { viewer.ScrollChanged -= record; }
            });
            await Test("High-resolution wheel deltas retain fractional pixel movement", async () =>
            {
                await Reset(); Wheel(-15); await Task.Delay(300); double small = viewer.VerticalOffset;
                await Reset(); Wheel(-120); await Task.Delay(300); double full = viewer.VerticalOffset;
                traces.Add(new { name = "fractional-delta", small, full });
                Check(small > .1 && small < full / 2 && Math.Abs(small - full / 8) <= 1 / System.Windows.Media.VisualTreeHelper.GetDpi(SongList).DpiScaleY + .01, "small delta rounded to a whole item");
            });
            await Test("Rapid wheels accumulate and reverse without snapping", async () =>
            {
                await Reset(); Wheel(-120); await Task.Delay(300); double one = viewer.VerticalOffset;
                Check(one > 0, "wheel did not move content");
                await Reset(); Wheel(-120); Wheel(-120); Wheel(-120); await Task.Delay(300);
                Check(Math.Abs(viewer.VerticalOffset - one * 3) < 1, "rapid wheel input lost distance");
                double beforeReverse = viewer.VerticalOffset; Wheel(120); await Task.Delay(300);
                Check(Math.Abs(viewer.VerticalOffset - (beforeReverse - one)) < 1, "reverse wheel retained stale target");
            });
            await Test("Top/bottom clamp and direct scrollbar movement interrupt easing", async () =>
            {
                await Reset(); Wheel(120); await Task.Delay(300); Check(viewer.VerticalOffset == 0, "top overscroll");
                await Reset(viewer.ScrollableHeight); Wheel(-120); await Task.Delay(300);
                Check(Math.Abs(viewer.VerticalOffset - viewer.ScrollableHeight) < 1, "bottom overscroll");
                await Reset(); Wheel(-120); await Task.Delay(40); viewer.ScrollToVerticalOffset(320); UpdateLayout();
                await Task.Delay(300); Check(Math.Abs(viewer.VerticalOffset - 320) < 1, "animation overrode scrollbar position");
                viewer.ScrollToVerticalOffset(123.5); UpdateLayout(); await Task.Delay(40);
                Check(Math.Abs(viewer.VerticalOffset - 123.5) < 1, "scrollbar still snapped to item boundary");
            });
            await Test("Disabling and re-enabling releases rendering callbacks and resumes scrolling", async () =>
            {
                await Reset(); Wheel(-120); await Task.Delay(40);
                SmoothScroll.SetIsEnabled(SongList, false); UpdateLayout(); await Task.Delay(40);
                double stopped = viewer.VerticalOffset; await Task.Delay(240);
                Check(Math.Abs(viewer.VerticalOffset - stopped) < 1, "disabled behavior still animating");
                SmoothScroll.SetIsEnabled(SongList, true); Wheel(-120); await Task.Delay(300);
                Check(viewer.VerticalOffset > stopped, "re-enabled behavior did not reconnect");
            });
            await Test("Mid-animation reversal immediately follows the new direction", async () =>
            {
                await Reset(500); Wheel(-120); await Task.Delay(40);
                double before = viewer.VerticalOffset; Wheel(120); await Task.Delay(300);
                Check(viewer.VerticalOffset < before, "reversal kept scrolling toward old target");
            });
            await Test("Multiselect, bring-into-view, pagination and search remain intact", async () =>
            {
                await Reset(); SongList.SelectedItems.Clear(); SongList.SelectedItems.Add(SongList.Items[0]); SongList.SelectedItems.Add(SongList.Items[1]);
                Check(SongList.SelectedItems.Count == 2, "extended selection broken");
                SongList.SelectedIndex = 10; SongList.ScrollIntoView(SongList.SelectedItem);
                await WaitForPreparationAsync(); UpdateLayout(); await Task.Delay(60);
                var row = (ListBoxItem)SongList.ItemContainerGenerator.ContainerFromIndex(10);
                double rowY = row.TransformToAncestor(SongList).Transform(new Point()).Y;
                Check(SongList.SelectedIndex == 10 && rowY >= -1 && rowY + row.ActualHeight <= SongList.ActualHeight + 1,
                    $"selected row not brought into viewport: y={rowY}; height={row.ActualHeight}; viewport={SongList.ActualHeight}");
                Wheel(-120);
                NextPageButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); await WaitForLibraryAsync();
                Check(_libraryPage?.Offset == LibraryPageSize && SongList.Items.Count == LibraryPageSize, "next page broken");
                double newPageOffset = viewer.VerticalOffset; await Task.Delay(240);
                Check(Math.Abs(viewer.VerticalOffset - newPageOffset) < 1, "previous-page animation carried into new page");
                PreviousPageButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); await WaitForLibraryAsync();
                Check(_libraryPage?.Offset == 0, "previous page broken");
                SearchBox.Text = "不存在的曲谱__scroll_fixture"; await WaitForLibraryAsync();
                Check(SongList.Items.Count == 0, "search empty state broken");
                Wheel(-120); await Task.Delay(240);
                SearchBox.Text = ""; await WaitForLibraryAsync(); await WaitForPreparationAsync(); UpdateLayout();
                Check(SongList.Items.Count == LibraryPageSize, "search restore broken");
                Check(MetadataVisuals(SongList).OfType<ListBoxItem>().Count() < LibraryPageSize, "all page containers eagerly realized");
            });
        }
        catch (Exception ex) { failures++; results.Add(new { name = "scroll-validation-driver", status = "FAIL", error = ex.ToString() }); }
        finally
        {
            if (_validationUnhandled.Count > 0) { failures++; results.Add(new { name = "unhandled", status = "FAIL", errors = _validationUnhandled }); }
            if (_nativeAttempts != 0) failures++;
            File.WriteAllText(Path.Combine(output, "scroll-ui-report.json"), JsonSerializer.Serialize(new
            { cases = results.Count, failures, nativeSendAttempts = _nativeAttempts, executable = Environment.ProcessPath,
                systemWheelScrollLines = SystemParameters.WheelScrollLines, traces, results,
                physicalTouchpad = "NOT TESTED; fractional routed wheel events validated",
                physicalTouch = "NOT TESTED; native WPF vertical panning configured" }, JsonDefaults.Options));
            Application.Current.Shutdown(failures == 0 ? 0 : 1);
        }
    }
}
