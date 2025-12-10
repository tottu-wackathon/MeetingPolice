import { useEffect, useRef, useState } from 'react';
// eslint-disable-next-line import/no-unresolved
import OT from '@opentok/client';

type Props = {
  apiKey: string;
  sessionId: string;
  token: string;
  muted?: boolean;
  videoOff?: boolean;
};

export function VonageStage({ apiKey, sessionId, token, muted = false, videoOff = false }: Props) {
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const publisherRef = useRef<any>(null);
  const sessionRef = useRef<any>(null);
  const publisherContainerRef = useRef<HTMLDivElement | null>(null);
  const subscriberContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
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

      session.on('sessionConnected', () => setStatus('connected'));
      session.on('sessionDisconnected', () => setStatus('idle'));

      session.on('streamCreated', (event: any) => {
        if (!subscriberContainerRef.current) return;
        session.subscribe(
          event.stream,
          subscriberContainerRef.current,
          { insertMode: 'append', width: '100%', height: '100%' },
          (err: any) => {
            if (err) {
              setError(err.message || String(err));
            }
          },
        );
      });

      const publisherOptions = {
        insertMode: 'append' as const,
        width: '100%',
        height: '100%',
        publishAudio: !muted,
        publishVideo: !videoOff,
        mirror: true,
        name: 'You',
      };

      const publisher = OTClient.initPublisher(
        publisherContainerRef.current,
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
      try {
        session.disconnect();
      } catch {
        /* noop */
      }
      try {
        publisher.destroy();
      } catch {
        /* noop */
      }
      sessionRef.current = null;
      publisherRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, sessionId, token]);

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
    <section className="panel video-stage live-video">
      <div className="panel-header">
        <h2>Vonage ビデオ</h2>
        <span className={`status-chip ${status}`}>
          {status === 'connected' ? 'Live' : status === 'connecting' ? '接続中' : status}
        </span>
      </div>
      <div className="video-grid">
        <div className="video-tile speaking">
          <div className="video-feed" ref={publisherContainerRef}>
            {!publisherRef.current && status !== 'error' && <p className="video-placeholder">カメラを初期化しています…</p>}
            {status === 'error' && <p className="video-placeholder">ビデオを開始できませんでした。</p>}
          </div>
          <div className="video-meta">
            <div>
              <p className="name">You</p>
              <p className="role">Host</p>
            </div>
            <span className="badge">{muted ? 'Muted' : 'Live mic'}</span>
          </div>
        </div>
        <div className="video-tile">
          <div className="video-feed" ref={subscriberContainerRef}>
            <p className="video-placeholder">参加者が入室すると映像が表示されます</p>
          </div>
          <div className="video-meta">
            <div>
              <p className="name">Participants</p>
              <p className="role">vonage</p>
            </div>
            <span className="badge ghost">待機中</span>
          </div>
        </div>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
