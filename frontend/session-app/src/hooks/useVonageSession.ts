import { useEffect, useRef, useState } from 'react';
import createVonageVideoClient, { 
  type VonageVideoClient, 
  type Session, 
  type Publisher, 
  type Subscriber,
  type Stream,
  type VideoError 
} from '@vonage/client-sdk-video';

interface UseVonageSessionProps {
  apiKey: string;
  sessionId: string;
  token: string;
}

export function useVonageSession({ apiKey, sessionId, token }: UseVonageSessionProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [publisher, setPublisher] = useState<Publisher | null>(null);
  const [subscribers, setSubscribers] = useState<Subscriber[]>([]);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAudioEnabled, setIsAudioEnabled] = useState(true);
  const [isVideoEnabled, setIsVideoEnabled] = useState(true);

  const sessionRef = useRef<Session | null>(null);
  const publisherRef = useRef<Publisher | null>(null);
  const clientRef = useRef<VonageVideoClient | null>(null);

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
      // Initialize Vonage Video Client
      const client = createVonageVideoClient(apiKey);
      clientRef.current = client;

      // Initialize session
      const newSession = client.initSession(sessionId);
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
          const newPublisher = client.initPublisher(publisherElement, {
            publishAudio: isAudioEnabled,
            publishVideo: isVideoEnabled,
            mirror: true,
            name: 'You',
          });

          publisherRef.current = newPublisher;
          setPublisher(newPublisher);

          // Publish to session
          await newSession.publish(newPublisher);
          console.log('✅ Publishing started');
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

      newSession.on('streamCreated', (event: { stream: Stream }) => {
        console.log('📺 Stream created:', event.stream.streamId);
        
        setStreams(prev => [...prev, event.stream]);

        try {
          const subscriberElement = document.createElement('div');
          const subscriber = newSession.subscribe(
            event.stream,
            subscriberElement,
            {
              subscribeToAudio: true,
              subscribeToVideo: true,
            }
          );

          console.log('✅ Subscribed to stream');
          setSubscribers(prev => [...prev, subscriber]);
        } catch (subscribeError) {
          console.error('❌ Subscribe failed:', subscribeError);
        }
      });

      newSession.on('streamDestroyed', (event: { stream: Stream }) => {
        console.log('📺 Stream destroyed:', event.stream.streamId);
        
        setStreams(prev => prev.filter(stream => stream.streamId !== event.stream.streamId));
        setSubscribers(prev => prev.filter(sub => sub.stream.streamId !== event.stream.streamId));
      });

      // Connect to session
      newSession.connect(token)
        .then(() => {
          console.log('✅ Connected to session');
        })
        .catch((connectError: VideoError) => {
          console.error('❌ Connection failed:', connectError);
          setError(`Connection failed: ${connectError.message} (Code: ${connectError.code})`);
        });

    } catch (initError) {
      console.error('❌ Failed to initialize Vonage client:', initError);
      setError(`Initialization failed: ${initError}`);
    }

    // Cleanup
    return () => {
      if (publisherRef.current) {
        publisherRef.current.destroy();
      }
      if (sessionRef.current) {
        sessionRef.current.disconnect();
      }
    };
  }, [apiKey, sessionId, token, isAudioEnabled, isVideoEnabled]);

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