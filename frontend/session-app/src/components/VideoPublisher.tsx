import { useEffect, useRef, useState } from 'react';
import * as OT from '@vonage/client-sdk-video';

interface VideoPublisherProps {
  session: OT.Session | null;
  publishAudio: boolean;
  publishVideo: boolean;
  screenShare?: boolean;
  onPublisherCreated?: (publisher: OT.Publisher) => void;
  onError?: (error: OT.OTError) => void;
}

export function VideoPublisher({
  session,
  publishAudio,
  publishVideo,
  screenShare = false,
  onPublisherCreated,
  onError
}: VideoPublisherProps) {
  const [publisher, setPublisher] = useState<OT.Publisher | null>(null);
  const [screenPublisher, setScreenPublisher] = useState<OT.Publisher | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isScreenPublishing, setIsScreenPublishing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const screenContainerRef = useRef<HTMLDivElement>(null);

  // Initialize camera publisher
  useEffect(() => {
    if (!session || !containerRef.current || screenShare) return;

    console.log('[VideoPublisher] Initializing camera publisher...');

    const publisherOptions: OT.PublisherProperties = {
      insertMode: 'replace',
      width: '100%',
      height: '100%',
      publishAudio,
      publishVideo,
      mirror: true,
      name: 'You',
      style: {
        buttonDisplayMode: 'off',
        nameDisplayMode: 'off',
      },
      resolution: '640x480',
      frameRate: 30,
    };

    const newPublisher = OT.initPublisher(
      containerRef.current,
      publisherOptions,
      (error) => {
        if (error) {
          console.error('[VideoPublisher] Camera publisher initialization failed:', error);
          onError?.(error);
        } else {
          console.log('[VideoPublisher] Camera publisher initialized successfully');
          setPublisher(newPublisher);
          onPublisherCreated?.(newPublisher);
        }
      }
    );

    return () => {
      if (newPublisher) {
        console.log('[VideoPublisher] Destroying camera publisher...');
        try {
          if (session && isPublishing) {
            session.unpublish(newPublisher);
          }
          // Publisher cleanup is handled by session.unpublish
        } catch (e) {
          console.warn('[VideoPublisher] Error destroying camera publisher:', e);
        }
      }
    };
  }, [session, screenShare]);

  // Initialize screen share publisher
  useEffect(() => {
    if (!session || !screenContainerRef.current || !screenShare) return;

    console.log('[VideoPublisher] Initializing screen share publisher...');

    const screenOptions: OT.PublisherProperties = {
      insertMode: 'replace',
      width: '100%',
      height: '100%',
      publishAudio: false, // Usually no audio for screen share
      publishVideo: true,
      mirror: false,
      name: 'Screen Share',
      videoSource: 'screen',
      style: {
        buttonDisplayMode: 'off',
        nameDisplayMode: 'off',
      },
    };

    const newScreenPublisher = OT.initPublisher(
      screenContainerRef.current,
      screenOptions,
      (error) => {
        if (error) {
          console.error('[VideoPublisher] Screen publisher initialization failed:', error);
          onError?.(error);
        } else {
          console.log('[VideoPublisher] Screen publisher initialized successfully');
          setScreenPublisher(newScreenPublisher);
        }
      }
    );

    return () => {
      if (newScreenPublisher) {
        console.log('[VideoPublisher] Destroying screen publisher...');
        try {
          if (session && isScreenPublishing) {
            session.unpublish(newScreenPublisher);
          }
          // Screen publisher cleanup is handled by session.unpublish
        } catch (e) {
          console.warn('[VideoPublisher] Error destroying screen publisher:', e);
        }
      }
    };
  }, [session, screenShare]);

  // Publish camera when session is connected
  useEffect(() => {
    if (!session || !publisher || isPublishing || screenShare) return;

    const handleSessionConnected = () => {
      console.log('[VideoPublisher] Session connected, starting camera publish...');
      setIsPublishing(true);
      
      session.publish(publisher, (error) => {
        if (error) {
          console.error('[VideoPublisher] Camera publish failed:', error);
          onError?.(error);
          setIsPublishing(false);
        } else {
          console.log('[VideoPublisher] Camera publishing started successfully');
        }
      });
    };

    if (session.connection) {
      handleSessionConnected();
    } else {
      session.on('sessionConnected', handleSessionConnected);
    }

    return () => {
      session.off('sessionConnected', handleSessionConnected);
    };
  }, [session, publisher, isPublishing, screenShare, onError]);

  // Publish screen share when session is connected
  useEffect(() => {
    if (!session || !screenPublisher || isScreenPublishing || !screenShare) return;

    const handleScreenPublish = () => {
      console.log('[VideoPublisher] Starting screen share publish...');
      setIsScreenPublishing(true);
      
      session.publish(screenPublisher, (error) => {
        if (error) {
          console.error('[VideoPublisher] Screen share publish failed:', error);
          onError?.(error);
          setIsScreenPublishing(false);
        } else {
          console.log('[VideoPublisher] Screen share publishing started successfully');
        }
      });
    };

    if (session.connection) {
      handleScreenPublish();
    } else {
      session.on('sessionConnected', handleScreenPublish);
    }

    return () => {
      session.off('sessionConnected', handleScreenPublish);
    };
  }, [session, screenPublisher, isScreenPublishing, screenShare, onError]);

  // Update audio/video settings
  useEffect(() => {
    if (publisher) {
      publisher.publishAudio(publishAudio);
      console.log('[VideoPublisher] Audio publish:', publishAudio);
    }
  }, [publisher, publishAudio]);

  useEffect(() => {
    if (publisher) {
      publisher.publishVideo(publishVideo);
      console.log('[VideoPublisher] Video publish:', publishVideo);
    }
  }, [publisher, publishVideo]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      {/* Camera publisher */}
      {!screenShare && (
        <div 
          ref={containerRef}
          style={{ 
            width: '100%', 
            height: '100%',
            borderRadius: '8px',
            overflow: 'hidden',
            backgroundColor: '#1a1a1a'
          }}
        >
          {!publishVideo && (
            <div style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: '#333',
              color: '#fff',
              fontSize: '2em',
              zIndex: 10
            }}>
              📷
            </div>
          )}
        </div>
      )}

      {/* Screen share publisher */}
      {screenShare && (
        <div 
          ref={screenContainerRef}
          style={{ 
            width: '100%', 
            height: '100%',
            borderRadius: '8px',
            overflow: 'hidden',
            backgroundColor: '#1a1a1a'
          }}
        />
      )}

      {/* Audio indicator */}
      {!publishAudio && (
        <div style={{
          position: 'absolute',
          top: '8px',
          right: '8px',
          backgroundColor: 'rgba(244, 67, 54, 0.8)',
          color: 'white',
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '12px',
          zIndex: 20
        }}>
          🔇 ミュート
        </div>
      )}
    </div>
  );
}