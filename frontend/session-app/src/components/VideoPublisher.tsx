import { useEffect, useRef } from 'react';
import * as OT from '@vonage/client-sdk-video';

interface VideoPublisherProps {
  publisher: OT.Publisher | null;
  isAudioEnabled: boolean;
  isVideoEnabled: boolean;
}

export function VideoPublisher({ publisher, isAudioEnabled, isVideoEnabled }: VideoPublisherProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (publisher && containerRef.current) {
      // Clear any existing content
      containerRef.current.innerHTML = '';
      
      // Get the publisher's video element and append it
      const publisherElement = publisher.element;
      if (publisherElement) {
        containerRef.current.appendChild(publisherElement);
      }
    }
  }, [publisher]);

  return (
    <div className="video-publisher">
      <div 
        ref={containerRef}
        className="video-container"
        style={{
          width: '100%',
          height: '100%',
          backgroundColor: '#1a1a1a',
          borderRadius: '8px',
          overflow: 'hidden',
          position: 'relative',
        }}
      />
      
      {/* Status indicators */}
      <div className="video-controls">
        <span className="participant-name">You</span>
        <div className="control-indicators">
          {!isAudioEnabled && <span className="muted">🔇</span>}
          {!isVideoEnabled && <span className="video-off">📷</span>}
        </div>
      </div>
    </div>
  );
}