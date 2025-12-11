import { useState } from 'react';

interface ControlBarProps {
  isAudioEnabled: boolean;
  isVideoEnabled: boolean;
  isScreenSharing: boolean;
  onToggleAudio: () => void;
  onToggleVideo: () => void;
  onToggleScreenShare: () => void;
  onLeave: () => void;
  participantCount: number;
}

export function ControlBar({
  isAudioEnabled,
  isVideoEnabled,
  isScreenSharing,
  onToggleAudio,
  onToggleVideo,
  onToggleScreenShare,
  onLeave,
  participantCount,
}: ControlBarProps) {
  const [showTooltip, setShowTooltip] = useState<string | null>(null);

  return (
    <div className="control-bar">
      <div className="control-group">
        {/* Audio control */}
        <button
          type="button"
          onClick={onToggleAudio}
          className={`control-btn ${!isAudioEnabled ? 'off' : ''}`}
          title={isAudioEnabled ? 'ミュート' : 'ミュート解除'}
          onMouseEnter={() => setShowTooltip('audio')}
          onMouseLeave={() => setShowTooltip(null)}
        >
          {isAudioEnabled ? '🎙️' : '🔇'}
          {showTooltip === 'audio' && (
            <div className="tooltip">
              {isAudioEnabled ? 'ミュート' : 'ミュート解除'}
            </div>
          )}
        </button>

        {/* Video control */}
        <button
          type="button"
          onClick={onToggleVideo}
          className={`control-btn ${!isVideoEnabled ? 'off' : ''}`}
          title={isVideoEnabled ? 'ビデオ停止' : 'ビデオ開始'}
          onMouseEnter={() => setShowTooltip('video')}
          onMouseLeave={() => setShowTooltip(null)}
        >
          {isVideoEnabled ? '🎥' : '📷'}
          {showTooltip === 'video' && (
            <div className="tooltip">
              {isVideoEnabled ? 'ビデオ停止' : 'ビデオ開始'}
            </div>
          )}
        </button>

        {/* Screen share control */}
        <button
          type="button"
          onClick={onToggleScreenShare}
          className={`control-btn ${isScreenSharing ? 'active' : ''}`}
          title={isScreenSharing ? '画面共有停止' : '画面共有開始'}
          onMouseEnter={() => setShowTooltip('screen')}
          onMouseLeave={() => setShowTooltip(null)}
        >
          {isScreenSharing ? '🖥️' : '📺'}
          {showTooltip === 'screen' && (
            <div className="tooltip">
              {isScreenSharing ? '画面共有停止' : '画面共有開始'}
            </div>
          )}
        </button>
      </div>

      <div className="control-info">
        <span className="participant-count">
          👥 {participantCount}名
        </span>
      </div>

      <div className="control-group">
        {/* Leave button */}
        <button
          type="button"
          className="control-btn danger"
          onClick={onLeave}
          title="会議を退出"
          onMouseEnter={() => setShowTooltip('leave')}
          onMouseLeave={() => setShowTooltip(null)}
        >
          🚪
          {showTooltip === 'leave' && (
            <div className="tooltip">
              会議を退出
            </div>
          )}
        </button>
      </div>
    </div>
  );
}
