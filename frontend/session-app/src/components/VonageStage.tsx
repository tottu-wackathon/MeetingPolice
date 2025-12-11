import { useEffect, useState } from 'react';
import { useVonageSession } from '../hooks/useVonageSession';
import { VideoPublisher } from './VideoPublisher';
import { VideoSubscriber } from './VideoSubscriber';

type Props = {
  apiKey: string;
  sessionId: string;
  token: string;
  muted?: boolean;
  videoOff?: boolean;
  enabled?: boolean;
  fallbackNotice?: string | null;
  onParticipantsChange?: (participants: Array<{ id: string; name: string; role: 'host' | 'guest' }>) => void;
};

export function VonageStage({
  apiKey,
  sessionId,
  token,
  muted = false,
  videoOff = false,
  enabled = true,
  onParticipantsChange,
}: Props) {
  const [publisherError, setPublisherError] = useState<string | null>(null);
  const [subscriberErrors, setSubscriberErrors] = useState<{ [streamId: string]: string }>({});

  const {
    session,
    status,
    error,
    participants,
    streams,
  } = useVonageSession({
    apiKey,
    sessionId,
    token,
    enabled
  });

  // Update participants callback
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

  const handlePublisherError = (publisherErr: any) => {
    const errorMessage = publisherErr.message || String(publisherErr);
    console.error('[VonageStage] Publisher error:', errorMessage);
    setPublisherError(errorMessage);
  };

  const handleSubscriberError = (streamId: string, subscriberErr: any) => {
    const errorMessage = subscriberErr.message || String(subscriberErr);
    console.error('[VonageStage] Subscriber error for stream', streamId, ':', errorMessage);
    setSubscriberErrors(prev => ({
      ...prev,
      [streamId]: errorMessage
    }));
  };

  return (
    <div>
      {/* Debug Information */}
      <div style={{ 
        marginBottom: '16px', 
        padding: '12px', 
        backgroundColor: 'rgba(0,0,0,0.3)', 
        borderRadius: '4px',
        fontSize: '0.85em',
        color: '#ccc'
      }}>
        <div><strong>Vonage接続状況:</strong> {status}</div>
        <div><strong>APIキー:</strong> {apiKey ? `${apiKey.substring(0, 8)}...` : '未設定'}</div>
        <div><strong>セッションID:</strong> {sessionId ? `${sessionId.substring(0, 20)}...` : '未設定'}</div>
        <div><strong>参加者数:</strong> {participants.length}名</div>
        <div><strong>ストリーム数:</strong> {streams.length}個</div>
        
        {participants.length > 0 && (
          <div style={{ marginTop: '8px' }}>
            <strong>参加者一覧:</strong>
            {participants.map((p, i) => (
              <div key={p.id} style={{ marginLeft: '16px', fontSize: '0.8em' }}>
                {i + 1}. {p.name} ({p.role}) - ID: {p.id.substring(0, 8)}...
                {p.stream && <span style={{ color: '#4caf50' }}> [ストリーム有り]</span>}
              </div>
            ))}
          </div>
        )}
        
        {error && <div style={{ color: '#f44336' }}><strong>セッションエラー:</strong> {error}</div>}
        {publisherError && <div style={{ color: '#f44336' }}><strong>配信エラー:</strong> {publisherError}</div>}
        {Object.keys(subscriberErrors).length > 0 && (
          <div style={{ color: '#f44336' }}>
            <strong>受信エラー:</strong>
            {Object.entries(subscriberErrors).map(([streamId, err]) => (
              <div key={streamId} style={{ marginLeft: '16px', fontSize: '0.8em' }}>
                Stream {streamId.substring(0, 8)}...: {err}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Video Components */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px' }}>
        {/* Publisher (Self) */}
        {session && status === 'connected' && (
          <div style={{ 
            width: '200px', 
            height: '150px', 
            border: '2px solid #00ffff',
            borderRadius: '8px',
            overflow: 'hidden'
          }}>
            <div style={{ 
              fontSize: '12px', 
              padding: '4px 8px', 
              backgroundColor: 'rgba(0,255,255,0.2)',
              color: '#00ffff'
            }}>
              You (Publisher)
            </div>
            <div style={{ height: 'calc(100% - 28px)' }}>
              <VideoPublisher
                session={session}
                publishAudio={!muted}
                publishVideo={!videoOff}
                onError={handlePublisherError}
              />
            </div>
          </div>
        )}

        {/* Subscribers (Remote participants) */}
        {streams.map((stream) => (
          <div key={stream.streamId} style={{ 
            width: '200px', 
            height: '150px', 
            border: '2px solid #4caf50',
            borderRadius: '8px',
            overflow: 'hidden'
          }}>
            <div style={{ 
              fontSize: '12px', 
              padding: '4px 8px', 
              backgroundColor: 'rgba(76,175,80,0.2)',
              color: '#4caf50'
            }}>
              {stream.name || 'Guest'} (Remote)
            </div>
            <div style={{ height: 'calc(100% - 28px)' }}>
              <VideoSubscriber
                session={session}
                stream={stream}
                onError={(err) => handleSubscriberError(stream.streamId, err)}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}