interface ControlBarProps {
  isAudioEnabled: boolean;
  isVideoEnabled: boolean;
  onToggleAudio: () => void;
  onToggleVideo: () => void;
  onLeave: () => void;
}

export function ControlBar({
  isAudioEnabled,
  isVideoEnabled,
  onToggleAudio,
  onToggleVideo,
  onLeave,
}: ControlBarProps) {
  return (
    <div className="control-bar">
      <button
        className={`control-btn ${isAudioEnabled ? 'active' : 'inactive'}`}
        onClick={onToggleAudio}
        title={isAudioEnabled ? 'ミュート' : 'ミュート解除'}
      >
        {isAudioEnabled ? '🎙️' : '🔇'}
      </button>
      
      <button
        className={`control-btn ${isVideoEnabled ? 'active' : 'inactive'}`}
        onClick={onToggleVideo}
        title={isVideoEnabled ? 'ビデオ停止' : 'ビデオ開始'}
      >
        {isVideoEnabled ? '🎥' : '📷'}
      </button>
      
      <button
        className="control-btn leave-btn"
        onClick={onLeave}
        title="退出"
      >
        📞
      </button>
    </div>
  );
}