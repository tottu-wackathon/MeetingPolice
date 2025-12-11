import { useEffect, useRef, useState, useCallback } from 'react';
import OT from '@opentok/client';

interface VideoSubscriberProps {
  session: OT.Session | null;
  stream: OT.Stream;
  onSubscriberCreated?: (subscriber: OT.Subscriber) => void;
  onError?: (error: OT.OTError) => void;
  className?: string;
}

export function VideoSubscriber({
  session,
  stream,
  onSubscriberCreated,
  onError,
  className
}: VideoSubscriberProps) {
  const [subscriber, setSubscriber] = useState<OT.Subscriber | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!session || !stream || !containerRef.current) return;

    console.log('[VideoSubscriber] Creating subscriber for stream:', stream.streamId);
    setIsLoading(true);
    setHasError(false);

    const subscriberOptions: OT.SubscriberProperties = {
      insertMode: 'replace',
      width: '100%',
      height: '100%',
      style: {
        buttonDisplayMode: 'off',
        nameDisplayMode: 'off',
      },
      preferredResolution: { width: 640, height: 480 },
      preferredFrameRate: 30,
    };

    const newSubscriber = session.subscribe(
      stream,
      containerRef.current,
      subscriberOptions,
      (error) => {
        setIsLoading(false);
        if (error) {
          console.error('[VideoSubscriber] Subscribe failed:', error);
          setHasError(true);
          onError?.(error);
        } else {
          console.log('[VideoSubscriber] Successfully subscribed to stream');
          setSubscriber(newSubscriber);
          onSubscriberCreated?.(newSubscriber);
        }
      }
    );

    // Add event listeners for better error handling
    if (newSubscriber) {
      newSubscriber.on('videoEnabled', () => {
        console.log('[VideoSubscriber] Video enabled for stream:', stream.streamId);
      });

      newSubscriber.on('videoDisabled', () => {
        console.log('[VideoSubscriber] Video disabled for stream:', stream.streamId);
      });

      newSubscriber.on('audioEnabled', () => {
        console.log('[VideoSubscriber] Audio enabled for stream:', stream.streamId);
      });

      newSubscriber.on('audioDisabled', () => {
        console.log('[VideoSubscriber] Audio disabled for stream:', stream.streamId);
      });
    }

    return () => {
      if (newSubscriber) {
        console.log('[VideoSubscriber] Destroying subscriber...');
        try {
          newSubscriber.destroy();
        } catch (e) {
          console.warn('[VideoSubscriber] Error destroying subscriber:', e);
        }
      }
    };
  }, [session, stream, onSubscriberCreated, onError]);

  return (
    <div 
      className={className}
      style={{ 
        width: '100%', 
        height: '100%',
        borderRadius: '8px',
        overflow: 'hidden',
        backgroundColor: '#1a1a1a',
        position: 'relative'
      }}
    >
      <div 
        ref={containerRef}
        style={{ 
          width: '100%', 
          height: '100%'
        }}
      />
      
      {/* Loading indicator */}
      {isLoading && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          color: '#fff',
          fontSize: '14px',
          zIndex: 10
        }}>
          <div className="loading-spinner"></div>
          <span style={{ marginLeft: '8px' }}>接続中...</span>
        </div>
      )}

      {/* Error indicator */}
      {hasError && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'rgba(244, 67, 54, 0.8)',
          color: '#fff',
          fontSize: '14px',
          zIndex: 10
        }}>
          ❌ 接続エラー
        </div>
      )}

      {/* Stream status indicators */}
      {subscriber && (
        <div style={{
          position: 'absolute',
          top: '8px',
          left: '8px',
          display: 'flex',
          gap: '4px',
          zIndex: 20
        }}>
          {!stream.hasAudio && (
            <div style={{
              backgroundColor: 'rgba(244, 67, 54, 0.8)',
              color: 'white',
              padding: '2px 6px',
              borderRadius: '4px',
              fontSize: '10px'
            }}>
              🔇
            </div>
          )}
          {!stream.hasVideo && (
            <div style={{
              backgroundColor: 'rgba(158, 158, 158, 0.8)',
              color: 'white',
              padding: '2px 6px',
              borderRadius: '4px',
              fontSize: '10px'
            }}>
              📷
            </div>
          )}
        </div>
      )}
    </div>
  );
}