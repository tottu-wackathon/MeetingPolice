type Props = {
  isMuted: boolean;
  isVideoOff: boolean;
  handRaised: boolean;
  onToggleMute: () => void;
  onToggleVideo: () => void;
  onToggleHand: () => void;
  onLeave: () => void;
};

export function ControlBar({
  isMuted,
  isVideoOff,
  handRaised,
  onToggleMute,
  onToggleVideo,
  onToggleHand,
  onLeave,
}: Props) {
  return (
    <div className="floating-controls">
      <button type="button" onClick={onToggleMute} className={`icon-btn ${isMuted ? 'off' : ''}`} title={isMuted ? 'ミュート解除' : 'ミュート'}>
        {isMuted ? '🔇' : '🎙️'}
      </button>
      <button type="button" onClick={onToggleVideo} className={`icon-btn ${isVideoOff ? 'off' : ''}`} title={isVideoOff ? 'ビデオ再開' : 'ビデオ停止'}>
        {isVideoOff ? '📷' : '🎥'}
      </button>
      <button type="button" onClick={onToggleHand} className={`icon-btn ${handRaised ? 'active' : ''}`} title={handRaised ? '手を下げる' : '手を挙げる'}>
        ✋
      </button>
      <button type="button" className="icon-btn danger" onClick={onLeave} title="退出">
        🚪
      </button>
    </div>
  );
}
