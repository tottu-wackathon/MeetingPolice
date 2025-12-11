import { useEffect, useRef } from 'react';

interface VideoSubscriberProps {
  subscriber: any;
  stream: any;
}

export function VideoSubscriber({ subscriber, stream }: VideoSubscriberProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (subscriber && containerRef.current) {
      // Clear any existing content
      containerRef.current.innerHTML = '';
      
      // Get the subscriber's video element and append it
      if (subscriber.element) {
        containerRef.current.appendChild(subscriber.element);
      }
    }
  }, [subscriber]);

  return (
    <div className="video-subscriber">
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
        <span className="participant-name">{stream.name || 'Guest'}</span>
        <div className="control-indicators">
          {!stream.hasAudio && <span className="muted">🔇</span>}
          {!stream.hasVideo && <span className="video-off">📷</span>}
        </div>
      </div>
    </div>
  );
}