using System.Windows.Controls;
using System.Windows.Input;

namespace AutoMidiPlayer.WPF.Controls.MidiPreviewPlayer;

public partial class MidiPreviewPlayer : UserControl
{
    public MidiPreviewPlayer()
    {
        InitializeComponent();
    }

    private MidiPreviewPlayerViewModel? ViewModel => DataContext as MidiPreviewPlayerViewModel;

}
