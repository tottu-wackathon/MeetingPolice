import React, { useCallback, useEffect, useState } from 'react';
import { useVonageSession } from '../hooks/useVonageSession';
import { VideoPublisher } from './VideoPublisher';
import { VideoSubscriber } from './VideoSubscriber';
import { ControlBar } from './ControlBar';

interface VideoRoomProps {
  apiKey: string;
  sessionId: string;
  token: string;
  onParticipantsChange?: (participants: Array<{ id: string; name: string; role: 'host' | 'guest' }>) => void;
  onLeave?: () => void;
}

export function VideoRoom({
  apiKey,
  sessionId,
  token,
  onParticipantsChange,
  onLeave
}: VideoRoomProps) {
  const [isAudioEnabled, setIsAudioEnabled] = useState(true);
  const [isVideoEnabled, setIsVideoEnabled] = useState(true);
  const [isScreenSharing, setIsScreenSharing] = useState(false);

  const {
    session,
    status,
    error,
    participants,
    streams,
    disconnect
  } = useVonageSession({
    apiKey,
    sessionId,
    token,
    enabled: true
  });

  // Notify parent component about participant changes
  useEffect(() => {
    if (onParticipantsChange) {
      const formattedParticipants = participants.map(p => ({
        id: p.id,
        name: p.name,
        role: p.role
      }));
      onParticipantsChange(formattedParticipants);
    }
  }, [participants, onParticipantsChange]);

  const handleToggleAudio = useCallback(() => {
    setIsAudioEnabled(prev => !prev);
  }, []);

  const handleToggleVideo = useCallback(() => {
    setIsVideoEnabled(prev => !prev);
  }, []);

  const handleToggleScreenShare = useCallback(() => {
    setIsScreenSharing(prev => !prev);
  }, []);

  const handleLeave = useCallback(() => {
    disconnect();
    onLeave?.();
  }, [disconnect, onLeave]);

  if (status === 'error') {
    return (
      <div className="video-room-error">
        <h3>🚫 ビデオ会議接続エラー</h3>
        <p className="error-message">{error}</p>
        
        {error?.includes('APIキーが無効') && (
          <div className="error-troubleshooting">
            <h4>🔧 トラブルシューティング</h4>
            <div className="troubleshooting-steps">
              <div className="step">
                <strong>1. バックエンド設定確認</strong>
                <p>以下の環境変数が.envファイルに正しく設定されているか確認してください：</p>
                <ul>
                  <li><code>VONAGE_API_KEY</code> - Vonage Video APIキー</li>
                  <li><code>VONAGE_APPLICATION_ID</code> - Vonage アプリケーションID</li>
                  <li><code>VONAGE_PRIVATE_KEY_PATH</code> - 秘密鍵ファイルのパス</li>
                </ul>
              </div>
              <div className="step">
                <strong>2. 秘密鍵ファイル確認</strong>
                <p><code>secrets/vonage_private.key</code>ファイルが存在し、正しい内容が含まれているか確認してください。</p>
              </div>
              <div className="step">
                <strong>3. Vonage Dashboard確認</strong>
                <p>Vonage Video API Dashboardで認証情報が有効であることを確認してください。</p>
              </div>
            </div>
          </div>
        )}
        
        <div className="error-actions">
          <button onClick={handleLeave} className="btn btn-primary">
            戻る
          </button>
          <button 
            onClick={() => window.location.reload()} 
            className="btn btn-secondary"
          >
            再読み込み
          </button>
        </div>
      </div>
    );
  }

  if (status === 'connecting') {
    return (
      <div className="video-room-loading">
        <div className="loading-spinner"></div>
        <p>ビデオ会議に接続中...</p>
      </div>
    );
  }

  return (
    <div className="video-room">
      {/* Main video grid */}
      <div className="video-grid">
        {/* Publisher (self) */}
        {session && status === 'connected' && (
          <div className="video-tile publisher-tile">
            <VideoPublisher
              session={session}
              publishAudio={isAudioEnabled}
              publishVideo={isVideoEnabled}
              screenShare={isScreenSharing}
            />
            <div className="video-overlay">
              <span className="participant-name">あなた</span>
              {!isAudioEnabled && <span className="muted-indicator">🔇</span>}
              {!isVideoEnabled && <span className="video-off-indicator">📷</span>}
            </div>
          </div>
        )}

        {/* Subscribers (remote participants) */}
        {streams.map((stream) => {
          const participant = participants.find(p => p.stream?.streamId === stream.streamId);
          return (
            <div key={stream.streamId} className="video-tile subscriber-tile">
              <VideoSubscriber
                session={session}
                stream={stream}
              />
              <div className="video-overlay">
                <span className="participant-name">
                  {participant?.name || 'ゲスト'}
                </span>
                {!stream.hasAudio && <span className="muted-indicator">🔇</span>}
                {!stream.hasVideo && <span className="video-off-indicator">📷</span>}
              </div>
            </div>
          );
        })}

        {/* Empty slots for better layout */}
        {streams.length === 0 && (
          <div className="video-tile empty-tile">
            <div className="empty-message">
              <p>他の参加者を待っています...</p>
            </div>
          </div>
        )}
      </div>

      {/* Control bar */}
      <ControlBar
        isAudioEnabled={isAudioEnabled}
        isVideoEnabled={isVideoEnabled}
        isScreenSharing={isScreenSharing}
        onToggleAudio={handleToggleAudio}
        onToggleVideo={handleToggleVideo}
        onToggleScreenShare={handleToggleScreenShare}
        onLeave={handleLeave}
        participantCount={participants.length}
      />

      {/* Connection status */}
      <div className="connection-status">
        <span className={`status-indicator ${status}`}>
          {status === 'connected' ? '🟢' : '🟡'} {status}
        </span>
        <span className="participant-count">
          {participants.length}名参加中
        </span>
      </div>
    </div>
  );
}