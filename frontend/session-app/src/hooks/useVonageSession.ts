import { useEffect, useRef, useState, useCallback } from 'react';
import OT from '@opentok/client';

export interface VonageParticipant {
  id: string;
  name: string;
  role: 'host' | 'guest';
  stream?: OT.Stream;
}

interface UseVonageSessionProps {
  apiKey: string;
  sessionId: string;
  token: string;
  enabled: boolean;
}

export function useVonageSession({
  apiKey,
  sessionId,
  token,
  enabled
}: UseVonageSessionProps) {
  const [session, setSession] = useState<OT.Session | null>(null);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [participants, setParticipants] = useState<VonageParticipant[]>([]);
  const [streams, setStreams] = useState<OT.Stream[]>([]);
  
  const sessionRef = useRef<OT.Session | null>(null);

  // Log initialization
  useEffect(() => {
    console.log('='.repeat(60));
    console.log('🎬 VONAGE SESSION HOOK INITIALIZATION');
    console.log('='.repeat(60));
    console.log('📋 Configuration:');
    console.log('  - Enabled:', enabled);
    console.log('  - API Key:', apiKey ? `${apiKey.substring(0, 8)}...` : 'Not provided');
    console.log('  - Session ID:', sessionId ? `${sessionId.substring(0, 20)}...` : 'Not provided');
    console.log('  - Token:', token ? `${token.substring(0, 20)}... (length: ${token.length})` : 'Not provided');
    console.log('  - OpenTok SDK Available:', !!window.OT);
  }, [apiKey, sessionId, token, enabled]);

  // Initialize session
  useEffect(() => {
    if (!enabled) {
      setStatus('idle');
      setError(null);
      setParticipants([]);
      setStreams([]);
      return;
    }

    // Validate Vonage credentials
    if (!apiKey || !sessionId || !token) {
      setStatus('error');
      setError('Vonage の接続情報が不足しています');
      console.error('[useVonageSession] Missing credentials:', {
        hasApiKey: !!apiKey,
        hasSessionId: !!sessionId,
        hasToken: !!token
      });
      return;
    }

    // Check if credentials look like mock data
    if (apiKey === 'mock_api_key' || sessionId.includes('mock') || token.startsWith('T1==')) {
      setStatus('error');
      setError('モック認証情報が検出されました。実際のVonage APIキーを設定してください。');
      console.error('[useVonageSession] Mock credentials detected');
      return;
    }

    if (!OT?.initSession) {
      setStatus('error');
      setError('Vonage SDK を読み込めませんでした');
      return;
    }

    console.log('📋 Step 1: Initializing Vonage Session');
    console.log('  - API Key:', apiKey.substring(0, 8) + '...');
    console.log('  - Session ID:', sessionId.substring(0, 20) + '...');
    console.log('  - Token Length:', token.length);
    
    setStatus('connecting');
    setError(null);

    console.log('📋 Step 2: Creating OT Session Object');
    const newSession = OT.initSession(apiKey, sessionId);
    console.log('  ✅ OT.initSession() completed');
    
    sessionRef.current = newSession;
    setSession(newSession);

    // Session event handlers
    newSession.on('sessionConnected', (event: OT.SessionConnectEvent) => {
      console.log('✅ SESSION CONNECTED EVENT');
      console.log('  - Event:', event);
      console.log('  - Connection ID:', event.target?.connection?.connectionId);
      setStatus('connected');
      setError(null);
      
      // Add self as host
      const localConnectionId = newSession.connection?.connectionId || 'local';
      setParticipants([{
        id: localConnectionId,
        name: 'You',
        role: 'host'
      }]);
      
      console.log('  - Local participant added:', localConnectionId);
      console.log('✅ Session setup complete - ready for video!');
    });

    newSession.on('sessionDisconnected', (event: OT.SessionDisconnectEvent) => {
      console.log('[useVonageSession] Session disconnected:', event);
      setStatus('idle');
      setParticipants([]);
      setStreams([]);
    });

    newSession.on('connectionCreated', (event: OT.ConnectionEvent) => {
      console.log('[useVonageSession] Connection created:', event);
      const connection = event.connection;
      const isLocal = connection?.connectionId === newSession.connection?.connectionId;
      
      if (!isLocal && connection?.connectionId) {
        setParticipants(prev => {
          // Check if participant already exists
          const exists = prev.some(p => p.id === connection.connectionId);
          if (exists) {
            console.log('[useVonageSession] Participant already exists:', connection.connectionId);
            return prev;
          }
          
          const newParticipant: VonageParticipant = {
            id: connection.connectionId,
            name: `Guest ${prev.length}`,
            role: 'guest'
          };
          
          console.log('[useVonageSession] New participant added:', newParticipant);
          return [...prev, newParticipant];
        });
      }
    });

    newSession.on('connectionDestroyed', (event: OT.ConnectionEvent) => {
      console.log('[useVonageSession] Connection destroyed:', event);
      const connectionId = event.connection?.connectionId;
      if (connectionId) {
        setParticipants(prev => prev.filter(p => p.id !== connectionId));
      }
    });

    newSession.on('streamCreated', (event: OT.StreamEvent) => {
      console.log('[useVonageSession] Stream created:', event);
      const stream = event.stream;
      
      setStreams(prev => {
        // Check if stream already exists
        const exists = prev.some(s => s.streamId === stream.streamId);
        if (exists) {
          console.log('[useVonageSession] Stream already exists:', stream.streamId);
          return prev;
        }
        
        console.log('[useVonageSession] New stream added:', stream.streamId);
        return [...prev, stream];
      });
      
      // Update participant with stream
      setParticipants(prev => prev.map(p => 
        p.id === stream.connection.connectionId 
          ? { ...p, stream }
          : p
      ));
    });

    newSession.on('streamDestroyed', (event: OT.StreamEvent) => {
      console.log('[useVonageSession] Stream destroyed:', event);
      const streamId = event.stream?.streamId;
      if (streamId) {
        setStreams(prev => prev.filter(s => s.streamId !== streamId));
        
        // Remove stream from participant
        setParticipants(prev => prev.map(p => 
          p.stream?.streamId === streamId 
            ? { ...p, stream: undefined }
            : p
        ));
      }
    });

    newSession.on('sessionReconnecting', () => {
      console.log('[useVonageSession] Session reconnecting...');
      setStatus('connecting');
    });

    newSession.on('sessionReconnected', () => {
      console.log('[useVonageSession] Session reconnected');
      setStatus('connected');
    });

    // Add error handling for session
    newSession.on('exception', (event: any) => {
      console.error('[useVonageSession] Session exception:', event);
      setError(`セッションエラー: ${event.message || 'Unknown error'}`);
    });

    // Connect to session
    console.log('📋 Step 3: Connecting to Vonage Session');
    newSession.connect(token, (connectError) => {
      if (connectError) {
        console.error('❌ CONNECTION FAILED');
        console.error('  - Error Code:', connectError.code);
        console.error('  - Error Message:', connectError.message);
        console.error('  - Full Error:', connectError);
        
        setStatus('error');
        
        // Provide more user-friendly error messages
        let errorMessage = '接続に失敗しました';
        switch (connectError.code) {
          case 1004:
            errorMessage = 'APIキーが無効です。バックエンドのVonage設定を確認してください。';
            console.error('  🔧 Diagnosis: Invalid API Key - check backend Vonage configuration');
            break;
          case 1005:
            errorMessage = 'セッションIDが無効です。新しいセッションを作成してください。';
            console.error('  🔧 Diagnosis: Invalid Session ID - session may not exist');
            break;
          case 1006:
            errorMessage = 'トークンが無効または期限切れです。再度参加してください。';
            console.error('  🔧 Diagnosis: Invalid or expired token');
            break;
          case 1026:
            errorMessage = 'ネットワーク接続を確認してください。';
            console.error('  🔧 Diagnosis: Network connectivity issue');
            break;
          case 1013:
            errorMessage = 'セッションが見つかりません。正しいミーティングIDを確認してください。';
            console.error('  🔧 Diagnosis: Session not found');
            break;
          case 1014:
            errorMessage = 'セッションの参加者数が上限に達しています。';
            console.error('  🔧 Diagnosis: Session capacity exceeded');
            break;
          default:
            errorMessage = `接続エラー (${connectError.code}): ${connectError.message}`;
            console.error('  🔧 Diagnosis: Unknown error');
        }
        
        setError(errorMessage);
      } else {
        console.log('✅ CONNECTION SUCCESSFUL');
        console.log('  - Session connected successfully');
        console.log('  - Waiting for sessionConnected event...');
      }
    });

    // Cleanup
    return () => {
      console.log('[useVonageSession] Cleaning up session...');
      
      if (sessionRef.current) {
        try {
          sessionRef.current.disconnect();
        } catch (e) {
          console.warn('[useVonageSession] Error disconnecting session:', e);
        }
        sessionRef.current = null;
      }
      
      setSession(null);
      setParticipants([]);
      setStreams([]);
    };
  }, [apiKey, sessionId, token, enabled]);

  const disconnect = useCallback(() => {
    if (sessionRef.current) {
      sessionRef.current.disconnect();
    }
  }, []);

  return {
    session,
    status,
    error,
    participants,
    streams,
    disconnect
  };
}