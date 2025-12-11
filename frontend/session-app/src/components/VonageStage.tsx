import { useEffect, useRef, useState } from 'react';
// eslint-disable-next-line import/no-unresolved
import OT from '@opentok/client';

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
  fallbackNotice,
  onParticipantsChange,
}: Props) {
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const publisherRef = useRef<any>(null);
  const sessionRef = useRef<any>(null);
  const publisherContainerRef = useRef<HTMLDivElement | null>(null);
  const subscriberContainerRef = useRef<HTMLDivElement | null>(null);
  const participantRef = useRef<Array<{ id: string; name: string; role: 'host' | 'guest' }>>([]);

  const upsertParticipant = (participant: { id: string; name: string; role: 'host' | 'guest' }) => {
    participantRef.current = [
      ...participantRef.current.filter((p) => p.id !== participant.id),
      participant,
    ];
    onParticipantsChange?.(participantRef.current);
  };

  const removeParticipant = (id: string) => {
    participantRef.current = participantRef.current.filter((p) => p.id !== id);
    onParticipantsChange?.(participantRef.current);
  };

  const connectionLabel = (connection: any, fallbackRole: 'host' | 'guest') => {
    const data = connection?.data;
    if (typeof data === 'string' && data.trim()) {
      try {
        const parsed = JSON.parse(data);
        if (parsed?.name) return String(parsed.name);
      } catch {
        return data;
      }
    }
    const existingGuests = participantRef.current.filter((p) => p.role === 'guest').length;
    if (fallbackRole === 'host') return 'You';
    return `Guest ${existingGuests + 1}`;
  };

  useEffect(() => {
    if (!enabled) {
      setStatus('idle');
      setError(null);
      return undefined;
    }

    if (!apiKey || !sessionId || !token) {
      setStatus('error');
      setError('Vonage の接続情報が不足しています（音声のみの利用は可能です）');
      return undefined;
    }

    const OTClient: any = OT as any;
    if (!OTClient?.initSession) {
      setStatus('error');
      setError('Vonage SDK を読み込めませんでした（音声のみの利用は可能です）');
      return undefined;
    }

    setStatus('connecting');
    setError(null);

    try {
      const session = OTClient.initSession(apiKey, sessionId);
      sessionRef.current = session;

      session.on('sessionConnected', () => {
        setStatus('connected');
      });
      session.on('sessionDisconnected', () => setStatus('idle'));

      session.on('connectionCreated', (event: any) => {
        const connection = event.connection;
        const isLocal = connection?.connectionId === session.connection?.connectionId;
        const label = connectionLabel(connection, isLocal ? 'host' : 'guest');
        const participant = {
          id: connection?.connectionId || `conn-${Date.now()}`,
          name: label,
          role: isLocal ? 'host' : 'guest',
        } as const;
        upsertParticipant(participant);
      });

      session.on('connectionDestroyed', (event: any) => {
        const id = event.connection?.connectionId;
        if (!id) return;
        removeParticipant(id);
      });

      session.on('streamCreated', (event: any) => {
        if (!subscriberContainerRef.current) return;
        session.subscribe(
          event.stream,
          subscriberContainerRef.current,
          { insertMode: 'append', width: '100%', height: '100%' },
          (err: any) => {
            if (err) {
              setError(err.message || String(err));
            }
          },
        );
        const streamId = event.stream?.streamId || `guest-${Date.now()}`;
        const connection = event.stream?.connection;
        const label = connectionLabel(connection, 'guest');
        upsertParticipant({ id: streamId, name: label, role: 'guest' });
      });

      session.on('streamDestroyed', (event: any) => {
        const streamId = event.stream?.streamId;
        if (!streamId) return;
        removeParticipant(streamId);
      });

      const publisherOptions = {
        insertMode: 'append' as const,
        width: '100%',
        height: '100%',
        publishAudio: !muted,
        publishVideo: !videoOff,
        mirror: true,
        name: 'You',
      };

      const publisher = OTClient.initPublisher(
        publisherContainerRef.current,
        publisherOptions,
        (err: any) => {
          if (err) {
            setError(err.message || String(err));
          }
        },
      );
      publisherRef.current = publisher;

      session.connect(token, (err: any) => {
        if (err) {
          setStatus('error');
          setError(err.message || String(err));
          return;
        }
        session.publish(publisher, (pubErr: any) => {
          if (pubErr) {
            setError(pubErr.message || String(pubErr));
          }
        });
      });
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Vonage 接続に失敗しました');
    }

    return () => {
      const activeSession = sessionRef.current;
      const activePublisher = publisherRef.current;
      try {
        activeSession?.disconnect();
      } catch {
        /* noop */
      }
      try {
        activePublisher?.destroy();
      } catch {
        /* noop */
      }
      sessionRef.current = null;
      publisherRef.current = null;
      participantRef.current = [];
      onParticipantsChange?.([]);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, sessionId, token, enabled]);

  useEffect(() => {
    if (publisherRef.current) {
      publisherRef.current.publishAudio(!muted);
    }
  }, [muted]);

  useEffect(() => {
    if (publisherRef.current) {
      publisherRef.current.publishVideo(!videoOff);
    }
  }, [videoOff]);

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
        <div><strong>接続状況:</strong> {status}</div>
        <div><strong>APIキー:</strong> {apiKey ? `${apiKey.substring(0, 8)}...` : '未設定'}</div>
        <div><strong>セッションID:</strong> {sessionId ? `${sessionId.substring(0, 20)}...` : '未設定'}</div>
        <div><strong>トークン:</strong> {token ? `${token.substring(0, 20)}...` : '未設定'}</div>
        <div><strong>ミュート:</strong> {muted ? 'はい' : 'いいえ'}</div>
        <div><strong>ビデオオフ:</strong> {videoOff ? 'はい' : 'いいえ'}</div>
        {error && <div style={{ color: '#f44336' }}><strong>エラー:</strong> {error}</div>}
      </div>

      <section className="video-stage compact">
        <div className="video-badge">
          {!enabled ? 'Audio Only' : status === 'connected' ? 'Live' : status === 'connecting' ? 'Connecting' : status === 'error' ? 'Error' : 'Idle'}
        </div>
        <div className="video-strip">
          <div className="video-tile small">
            <div className="video-feed" ref={publisherContainerRef}>
              {!enabled && <p className="video-placeholder">Audio Only</p>}
              {enabled && status === 'idle' && <p className="video-placeholder">待機中...</p>}
              {enabled && status === 'connecting' && <p className="video-placeholder">接続中...</p>}
              {enabled && status === 'connected' && !publisherRef.current && <p className="video-placeholder">カメラ初期化中...</p>}
              {enabled && status === 'error' && <p className="video-placeholder">接続エラー</p>}
            </div>
            <div className="video-meta">
              <p className="name">あなた</p>
            </div>
          </div>
          <div className="video-tile small" ref={subscriberContainerRef}>
            {!enabled && <p className="video-placeholder">Audio Only</p>}
            {enabled && status !== 'connected' && <p className="video-placeholder">参加者待ち</p>}
            {enabled && status === 'connected' && <p className="video-placeholder">参加者なし</p>}
          </div>
        </div>
        {(fallbackNotice || error) && (
          <p className="error" role="alert">
            {fallbackNotice || error}
          </p>
        )}
      </section>
    </div>
  );
}
