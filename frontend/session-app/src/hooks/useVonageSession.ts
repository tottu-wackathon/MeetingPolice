import { useEffect, useRef, useState } from 'react';
import * as OT from '@vonage/client-sdk-video';

interface UseVonageSessionProps {
  apiKey: string;
  sessionId: string;
  token: string;
}

export function useVonageSession({ apiKey, sessionId, token }: UseVonageSessionProps) {
  const [session, setSession] = useState<OT.Session | null>(null);
  const [publisher, setPublisher] = useState<OT.Publisher | null>(null);
  const [subscribers, setSubscribers] = useState<OT.Subscriber[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAudioEnabled, setIsAudioEnabled] = useState(true);
  const [isVideoEnabled, setIsVideoEnabled] = useState(true);

  const sessionRef = useRef<OT.Session | null>(null);
  const publisherRef = useRef<OT.Publisher | null>(null);

  useEffect(() => {
    if (!apiKey || !sessionId || !token) {
      setError('Missing Vonage credentials');
      return;
    }

    console.log('🎬 Initializing Vonage session...');
    console.log('API Key:', apiKey.substring(0, 8) + '...');
    console.log('Session ID:', sessionId.substring(0, 20) + '...');
    console.log('Token length:', token.length);

    // Initialize session
    const newSession = OT.initSession(apiKey, sessionId);
    sessionRef.current = newSession;
    setSession(newSession);

    // Session event handlers
    newSession.on('sessionConnected', () => {
      console.log('✅ Session connected');
      setIsConnected(true);
      setError(null);

      // Initialize publisher
      const publisherElement = document.createElement('div');
      const newPublisher = OT.initPublisher(publisherElement, {
        insertMode: 'replace',
        width: '100%',
        height: '100%',
        publishAudio: isAudioEnabled,
        publishVideo: isVideoEnabled,
        mirror: true,
        name: 'You',
      });

      publisherRef.current = newPublisher;
      setPublisher(newPublisher);

      // Publish to session
      newSession.publish(newPublisher, (publishError) => {
        if (publishError) {
          console.error('❌ Publish failed:', publishError);
          setError(`Publish failed: ${publishError.message}`);
        } else {
          console.log('✅ Publishing started');
        }
      });
    });

    newSession.on('sessionDisconnected', () => {
      console.log('📤 Session disconnected');
      setIsConnected(false);
      setPublisher(null);
      setSubscribers([]);
    });

    newSession.on('streamCreated', (event) => {
      console.log('📺 Stream created:', event.stream.streamId);
      
      const subscriberElement = document.createElement('div');
      const subscriber = newSession.subscribe(
        event.stream,
        subscriberElement,
        {
          insertMode: 'replace',
          width: '100%',
          height: '100%',
        },
        (subscribeError) => {
          if (subscribeError) {
            console.error('❌ Subscribe failed:', subscribeError);
          } else {
            console.log('✅ Subscribed to stream');
            setSubscribers(prev => [...prev, subscriber]);
          }
        }
      );
    });

    newSession.on('streamDestroyed', (event) => {
      console.log('📺 Stream destroyed:', event.stream.streamId);
      setSubscribers(prev => prev.filter(sub => {
        // Remove the subscriber that matches the destroyed stream
        return true; // Simplified for now
      }));
    });

    // Connect to session
    newSession.connect(token, (connectError) => {
      if (connectError) {
        console.error('❌ Connection failed:', connectError);
        setError(`Connection failed: ${connectError.message} (Code: ${connectError.code})`);
      } else {
        console.log('✅ Connected to session');
      }
    });

    // Cleanup
    return () => {
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
    isConnected,
    error,
    isAudioEnabled,
    isVideoEnabled,
    toggleAudio,
    toggleVideo,
    disconnect,
  };
}