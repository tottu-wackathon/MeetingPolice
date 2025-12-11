import { useEffect, useRef, useState } from 'react';
import * as OT from '@vonage/client-sdk-video';

interface UseVonageSessionProps {
  apiKey: string;
  sessionId: string;
  token: string;
}

export function useVonageSession({ apiKey, sessionId, token }: UseVonageSessionProps) {
  const [session, setSession] = useState<any>(null);
  const [publisher, setPublisher] = useState<any>(null);
  const [subscribers, setSubscribers] = useState<any[]>([]);
  const [streams, setStreams] = useState<any[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAudioEnabled, setIsAudioEnabled] = useState(true);
  const [isVideoEnabled, setIsVideoEnabled] = useState(true);

  const sessionRef = useRef<any>(null);
  const publisherRef = useRef<any>(null);

  useEffect(() => {
    if (!apiKey || !sessionId || !token) {
      setError('Missing Vonage credentials');
      return;
    }

    console.log('🎬 Initializing Vonage Video Client...');
    console.log('API Key:', apiKey.substring(0, 8) + '...');
    console.log('Session ID:', sessionId.substring(0, 20) + '...');
    console.log('Token length:', token.length);
    console.log('Token format:', token.startsWith('eyJ') ? 'JWT' : 'Legacy');

    try {
      console.log('🔍 Available OT methods:', Object.keys(OT));
      
      // Initialize session using the correct Vonage SDK method
      const newSession = OT.initSession(apiKey, sessionId);
      sessionRef.current = newSession;
      setSession(newSession);

      // Session event handlers
      newSession.on('sessionConnected', async () => {
        console.log('✅ Session connected');
        setIsConnected(true);
        setError(null);

        try {
          // Initialize publisher
          const publisherElement = document.createElement('div');
          const newPublisher = OT.initPublisher(publisherElement, {
            publishAudio: isAudioEnabled,
            publishVideo: isVideoEnabled,
            mirror: true,
            name: 'You',
          });

          publisherRef.current = newPublisher;
          setPublisher(newPublisher);

          // Publish to session
          newSession.publish(newPublisher, (publishError: any) => {
            if (publishError) {
              console.error('❌ Publish failed:', publishError);
              setError(`Publish failed: ${publishError.message}`);
            } else {
              console.log('✅ Publishing started');
            }
          });
        } catch (publishError) {
          console.error('❌ Publish failed:', publishError);
          setError(`Publish failed: ${publishError}`);
        }
      });

      newSession.on('sessionDisconnected', () => {
        console.log('📤 Session disconnected');
        setIsConnected(false);
        setPublisher(null);
        setSubscribers([]);
        setStreams([]);
      });

      newSession.on('streamCreated', (event: any) => {
        console.log('📺 Stream created:', event.stream.streamId);
        
        setStreams(prev => [...prev, event.stream]);

        try {
          const subscriberElement = document.createElement('div');
          const subscriber = newSession.subscribe(
            event.stream,
            subscriberElement,
            {
              insertMode: 'replace',
              width: '100%',
              height: '100%',
            },
            (subscribeError: any) => {
              if (subscribeError) {
                console.error('❌ Subscribe failed:', subscribeError);
              } else {
                console.log('✅ Subscribed to stream');
                setSubscribers(prev => [...prev, subscriber]);
              }
            }
          );
        } catch (subscribeError) {
          console.error('❌ Subscribe failed:', subscribeError);
        }
      });

      newSession.on('streamDestroyed', (event: any) => {
        console.log('📺 Stream destroyed:', event.stream.streamId);
        
        setStreams(prev => prev.filter(stream => stream.streamId !== event.stream.streamId));
        setSubscribers(prev => prev.filter(sub => sub.stream && sub.stream.streamId !== event.stream.streamId));
      });

      // Connect to session
      newSession.connect(token, (connectError: any) => {
        if (connectError) {
          console.error('❌ Connection failed:', connectError);
          setError(`Connection failed: ${connectError.message} (Code: ${connectError.code})`);
        } else {
          console.log('✅ Connected to session');
        }
      });

    } catch (initError) {
      console.error('❌ Failed to initialize Vonage client:', initError);
      setError(`Initialization failed: ${initError}`);
    }

    // Cleanup
    return () => {
      if (publisherRef.current && sessionRef.current) {
        sessionRef.current.unpublish(publisherRef.current);
      }
      if (sessionRef.current) {
        sessionRef.current.disconnect();
      }
    };
  }, [apiKey, sessionId, token]);

  const toggleAudio = () => {
    if (publisherRef.current) {
      const newState = !isAudioEnabled;
      publisherRef.current.publishAudio(newState);
      setIsAudioEnabled(newState);
    }
  };

  const toggleVideo = () => {
    if (publisherRef.current) {
      const newState = !isVideoEnabled;
      publisherRef.current.publishVideo(newState);
      setIsVideoEnabled(newState);
    }
  };

  const disconnect = () => {
    if (sessionRef.current) {
      sessionRef.current.disconnect();
    }
  };

  return {
    session,
    publisher,
    subscribers,
    streams,
    isConnected,
    error,
    isAudioEnabled,
    isVideoEnabled,
    toggleAudio,
    toggleVideo,
    disconnect,
  };
}