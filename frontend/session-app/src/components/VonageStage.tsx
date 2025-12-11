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
  const [sessionInfo, setSessionInfo] = useState<any>(null);
  const publisherRef = useRef<any>(null);
  const sessionRef = useRef<any>(null);
  const publisherContainerRef = useRef<HTMLDivElement | null>(null);
  const subscriberContainerRef = useRef<HTMLDivElement | null>(null);
  const participantRef = useRef<Array<{ id: string; name: string; role: 'host' | 'guest' }>>([]);

  const upsertParticipant = (participant: { id: string; name: string; role: 'host' | 'guest' }) => {
    console.log('[Vonage] upsertParticipant called with:', participant);
    console.log('[Vonage] Current participants before update:', participantRef.current);
    
    const existingIndex = participantRef.current.findIndex(p => p.id === participant.id);
    if (existingIndex >= 0) {
      // Update existing participant
      console.log('[Vonage] Updating existing participant at index:', existingIndex);
      participantRef.current[existingIndex] = participant;
    } else {
      // Add new participant
      console.log('[Vonage] Adding new participant');
      participantRef.current = [...participantRef.current, participant];
    }
    
    console.log('[Vonage] Updated participants:', participantRef.current);
    console.log('[Vonage] Calling onParticipantsChange with:', participantRef.current);
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
    console.log('[VonageStage] useEffect triggered', { 
      enabled, 
      apiKey: apiKey ? apiKey.substring(0, 8) + '...' : 'undefined', 
      sessionId: sessionId ? sessionId.substring(0, 20) + '...' : 'undefined', 
      token: token ? token.substring(0, 20) + '...' : 'undefined' 
    });
    
    if (!enabled) {
      console.log('[VonageStage] Not enabled, setting idle');
      setStatus('idle');
      setError(null);
      return undefined;
    }

    if (!apiKey || !sessionId || !token) {
      console.log('[VonageStage] Missing credentials', { hasApiKey: !!apiKey, hasSessionId: !!sessionId, hasToken: !!token });
      setStatus('error');
      setError('Vonage の接続情報が不足しています（音声のみの利用は可能です）');
      return undefined;
    }

    // グローバルなOTオブジェクトを確認
    const OTClient: any = (window as any).OT || OT;
    console.log('[VonageStage] Checking OT availability:', { 
      hasWindowOT: !!(window as any).OT, 
      hasImportedOT: !!OT, 
      hasInitSession: !!OTClient?.initSession 
    });
    
    if (!OTClient?.initSession) {
      console.log('[VonageStage] OpenTok SDK not available - OT object or initSession method missing');
      setStatus('error');
      setError('Vonage SDK を読み込めませんでした（音声のみの利用は可能です）');
      return undefined;
    }

    console.log('[VonageStage] Starting Vonage session initialization...');

    setStatus('connecting');
    setError(null);

    try {
      console.log('[VonageStage] Creating session with', { 
        apiKey: apiKey ? apiKey.substring(0, 8) + '...' : 'undefined', 
        sessionId: sessionId ? sessionId.substring(0, 20) + '...' : 'undefined' 
      });
      const session = OTClient.initSession(apiKey, sessionId);
      sessionRef.current = session;
      console.log('[VonageStage] Session created successfully');

      session.on('sessionConnected', (event: any) => {
        console.log('[Vonage] Session connected successfully');
        console.log('[Vonage] sessionConnected event:', event);
        const info = {
          sessionId: session.sessionId,
          connectionId: session.connection?.connectionId,
          connectionCount: session.connectionCount || 0,
          capabilities: session.capabilities || {},
          isConnected: session.isConnected(),
          connections: session.connections ? Object.keys(session.connections).length : 0
        };
        console.log('[Vonage] Session details:', info);
        console.log('[Vonage] All connections:', session.connections);
        setSessionInfo(info);
        setStatus('connected');
      });
      
      session.on('sessionDisconnected', (event: any) => {
        console.log('[Vonage] Session disconnected:', event.reason);
        setStatus('idle');
      });

      session.on('connectionCreated', (event: any) => {
        console.log('[Vonage] connectionCreated event triggered:', event);
        const connection = event.connection;
        const isLocal = connection?.connectionId === session.connection?.connectionId;
        const label = connectionLabel(connection, isLocal ? 'host' : 'guest');
        const participant = {
          id: connection?.connectionId || `conn-${Date.now()}`,
          name: label,
          role: isLocal ? 'host' : 'guest',
        } as const;
        
        console.log('[Vonage] Connection created details:', {
          participant,
          isLocal,
          connectionId: connection?.connectionId,
          connectionData: connection?.data,
          totalConnections: session.connectionCount,
          sessionConnectionId: session.connection?.connectionId,
          allConnections: session.connections ? Object.keys(session.connections) : []
        });
        
        // セッション情報を更新
        setSessionInfo((prev: any) => ({
          ...prev,
          connectionCount: session.connectionCount,
          totalConnections: session.connectionCount,
          connections: session.connections ? Object.keys(session.connections).length : 0
        }));
        
        console.log('[Vonage] Adding participant to list:', participant);
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

      console.log('[VonageStage] Attempting to connect with token:', token ? token.substring(0, 20) + '...' : 'undefined');
      console.log('[VonageStage] Full token for debugging:', token);
      
      // トークンの形式を分析
      try {
        if (token) {
          console.log('[VonageStage] Token analysis:');
          console.log('  - Length:', token.length);
          console.log('  - Starts with T1==:', token.startsWith('T1=='));
          console.log('  - Contains dots (JWT format):', token.includes('.'));
          
          // JWTの場合、デコードして内容を確認
          if (token.includes('.')) {
            const parts = token.split('.');
            console.log('  - JWT parts count:', parts.length);
            if (parts.length >= 2) {
              try {
                const payload = JSON.parse(atob(parts[1]));
                console.log('  - JWT payload:', payload);
              } catch (e) {
                console.log('  - JWT payload decode failed:', e);
              }
            }
          }
        }
      } catch (e) {
        console.log('[VonageStage] Token analysis failed:', e);
      }
      
      session.connect(token, (err: any) => {
        if (err) {
          console.error('[VonageStage] Connection failed with error:', err);
          console.error('[VonageStage] Error code:', err.code);
          console.error('[VonageStage] Error message:', err.message);
          console.error('[VonageStage] Error name:', err.name);
          console.error('[VonageStage] Full error object:', JSON.stringify(err, null, 2));
          
          // OpenTok エラーコードの詳細
          const errorMessages: { [key: number]: string } = {
            1004: 'Invalid token format - トークンの形式が無効です',
            1005: 'Invalid session ID - セッションIDが無効です',
            1006: 'Connect failed - 接続に失敗しました',
            1026: 'Terms of service failure - 利用規約エラー',
            2001: 'Authentication error - 認証エラー'
          };
          
          const detailedMessage = errorMessages[err.code] || `Unknown error (${err.code})`;
          console.error('[VonageStage] Detailed error:', detailedMessage);
          
          setStatus('error');
          setError(`${detailedMessage}: ${err.message || String(err)}`);
          return;
        }
        console.log('[VonageStage] Connected successfully, publishing...');
        session.publish(publisher, (pubErr: any) => {
          if (pubErr) {
            console.error('[VonageStage] Publish failed:', pubErr);
            setError(pubErr.message || String(pubErr));
          } else {
            console.log('[VonageStage] Published successfully');
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
        
        {sessionInfo && (
          <div style={{ marginTop: '8px', padding: '8px', backgroundColor: 'rgba(0,255,0,0.1)', borderRadius: '4px' }}>
            <div><strong>🔗 セッション詳細:</strong></div>
            <div style={{ marginLeft: '16px', fontSize: '0.8em' }}>
              <div>接続ID: {sessionInfo.connectionId}</div>
              <div>接続数: {sessionInfo.connectionCount}</div>
              <div>接続状態: {sessionInfo.isConnected ? '✅ 接続中' : '❌ 未接続'}</div>
            </div>
          </div>
        )}
        
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
        
        {/* セッション接続テストボタン */}
        {sessionRef.current && (
          <div style={{ marginTop: '8px' }}>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button 
                onClick={() => {
                  const session = sessionRef.current;
                  const info = {
                    sessionId: session.sessionId,
                    isConnected: session.isConnected(),
                    connectionCount: session.connectionCount,
                    connections: session.connections ? Object.keys(session.connections) : [],
                    capabilities: session.capabilities,
                    sessionState: session.sessionState
                  };
                  console.log('[Vonage] Manual session check:', info);
                  alert(`セッション状態:\n接続: ${info.isConnected}\n接続数: ${info.connectionCount}\n接続ID数: ${info.connections.length}`);
                }}
                style={{
                  padding: '4px 8px',
                  fontSize: '0.8em',
                  backgroundColor: '#007acc',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                🔍 セッション確認
              </button>
              
              <button 
                onClick={() => {
                  console.log('[Vonage] Testing connection with different session...');
                  // 同じセッションIDで新しい接続をテスト
                  const testSession = (window as any).OT?.initSession(apiKey, sessionId);
                  if (testSession) {
                    testSession.connect(token, (err: any) => {
                      if (err) {
                        console.error('[Vonage] Test connection failed:', err);
                        alert(`テスト接続失敗: ${err.message}`);
                      } else {
                        console.log('[Vonage] Test connection successful');
                        alert('テスト接続成功！セッションは有効です。');
                        testSession.disconnect();
                      }
                    });
                  }
                }}
                style={{
                  padding: '4px 8px',
                  fontSize: '0.8em',
                  backgroundColor: '#28a745',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                🧪 接続テスト
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 隠れたコンテナ（他の参加者用） */}
      <div style={{ display: 'none' }}>
        <div ref={publisherContainerRef}></div>
        <div ref={subscriberContainerRef}></div>
      </div>
    </div>
  );
}
