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
    const existingIndex = participantRef.current.findIndex(p => p.id === participant.id);
    if (existingIndex >= 0) {
      // Update existing participant
      participantRef.current[existingIndex] = participant;
    } else {
      // Add new participant
      participantRef.current = [...participantRef.current, participant];
    }
    console.log('[Vonage] Updated participants:', participantRef.current);
    onParticipantsChange?.(participantRef.current);
  };

  const removeParticipant = (id: string) => {
    const beforeCount = participantRef.current.length;
    participantRef.current = participantRef.current.filter((p) => p.id !== id);
    const afterCount = participantRef.current.length;
    console.log(`[Vonage] Removed participant ${id}: ${beforeCount} -> ${afterCount}`);
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
        console.log('[Vonage] Session connected');
        setStatus('connected');
      });
      
      session.on('sessionDisconnected', () => {
        console.log('[Vonage] Session disconnected');
        setStatus('idle');
      });

      session.on('connectionCreated', (event: any) => {
        const connection = event.connection;
        const isLocal = connection?.connectionId === session.connection?.connectionId;
        const label = connectionLabel(connection, isLocal ? 'host' : 'guest');
        const participant = {
          id: connection?.connectionId || `conn-${Date.now()}`,
          name: label,
          role: isLocal ? 'host' : 'guest',
        } as const;
        console.log('[Vonage] Connection created:', participant);
        upsertParticipant(participant);
      });

      session.on('connectionDestroyed', (event: any) => {
        const id = event.connection?.connectionId;
        console.log('[Vonage] Connection destroyed:', id);
        if (!id) return;
        removeParticipant(id);
      });

      session.on('streamCreated', (event: any) => {
        console.log('[Vonage] Stream created:', event.stream);
        if (!subscriberContainerRef.current) return;
        session.subscribe(
          event.stream,
          subscriberContainerRef.current,
          { insertMode: 'append', width: '100%', height: '100%' },
          (err: any) => {
            if (err) {
              console.error('[Vonage] Subscribe error:', err);
              setError(err.message || String(err));
            } else {
              console.log('[Vonage] Successfully subscribed to stream');
            }
          },
        );
        const streamId = event.stream?.streamId || `guest-${Date.now()}`;
        const connection = event.stream?.connection;
        const label = connectionLabel(connection, 'guest');
        const participant = { id: streamId, name: label, role: 'guest' as const };
        console.log('[Vonage] Adding stream participant:', participant);
        upsertParticipant(participant);
      });

      session.on('streamDestroyed', (event: any) => {
        const streamId = event.stream?.streamId;
        console.log('[Vonage] Stream destroyed:', streamId);
        if (!streamId) return;
        removeParticipant(streamId);
      });

      // 指定されたDOM要素またはデフォルトのコンテナを使用
      const publisherContainer = document.getElementById('vonage-publisher') || publisherContainerRef.current;
      
      const publisherOptions = {
        insertMode: 'replace' as const,
        width: '100%',
        height: '100%',
        publishAudio: !muted,
        publishVideo: !videoOff,
        mirror: true,
        name: 'You',
        style: {
          buttonDisplayMode: 'off', // コントロールボタンを非表示
        },
      };

      const publisher = OTClient.initPublisher(
        publisherContainer,
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
        <div><strong>Vonage接続状況:</strong> {status}</div>
        <div><strong>APIキー:</strong> {apiKey ? `${apiKey.substring(0, 8)}...` : '未設定'}</div>
        <div><strong>セッションID:</strong> {sessionId ? `${sessionId.substring(0, 20)}...` : '未設定'}</div>
        <div><strong>参加者数:</strong> {participantRef.current.length}名</div>
        <div><strong>ミュート:</strong> {muted ? 'はい' : 'いいえ'}</div>
        <div><strong>ビデオオフ:</strong> {videoOff ? 'はい' : 'いいえ'}</div>
        {participantRef.current.length > 0 && (
          <div style={{ marginTop: '8px' }}>
            <strong>参加者一覧:</strong>
            {participantRef.current.map((p, i) => (
              <div key={p.id} style={{ marginLeft: '16px', fontSize: '0.8em' }}>
                {i + 1}. {p.name} ({p.role}) - ID: {p.id.substring(0, 8)}...
              </div>
            ))}
          </div>
        )}
        {error && <div style={{ color: '#f44336' }}><strong>エラー:</strong> {error}</div>}
        <div style={{ marginTop: '8px', fontSize: '0.8em', color: '#999' }}>
          💡 ビデオは参加者アイコン内に表示されます
        </div>
      </div>

      {/* 隠れたコンテナ（他の参加者用） */}
      <div style={{ display: 'none' }}>
        <div ref={publisherContainerRef}></div>
        <div ref={subscriberContainerRef}></div>
      </div>
    </div>
  );
}
