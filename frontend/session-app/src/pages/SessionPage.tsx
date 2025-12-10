import { FormEvent, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ControlBar } from '../components/ControlBar';
import { Layout } from '../components/Layout';
import { MetricsPanel } from '../components/MetricsPanel';
import { VonageStage } from '../components/VonageStage';
import { useAnalyticsStream } from '../hooks/useAnalyticsStream';
import { useMeetingSession } from '../hooks/useMeetingSession';
import { useTranscripts } from '../hooks/useTranscripts';
import { formatTime } from '../utils/time';

export function SessionPage() {
  const {
    session,
    status,
    error,
    joinMeeting,
    leaveMeeting,
    isMuted,
    isVideoOff,
    handRaised,
    toggleMute,
    toggleVideo,
    toggleHand,
  } = useMeetingSession();
  const { samples } = useAnalyticsStream(session?.meetingId);
  const { transcripts } = useTranscripts(session?.meetingId);
  const { meetingId } = useParams();
  const navigate = useNavigate();

  const [meetingCode, setMeetingCode] = useState('');
  const [joining, setJoining] = useState(false);

  const handleJoin = async (event: FormEvent) => {
    event.preventDefault();
    if (!meetingCode.trim()) return;
    setJoining(true);
    try {
      await joinMeeting(meetingCode);
      navigate(`/session/${meetingCode.trim()}`);
    } catch (err) {
      console.error('Failed to join meeting', err);
      // useMeetingSession が error をセットするのでここではログのみにする
    } finally {
      setJoining(false);
    }
  };

  // URL に meetingId がある場合は自動で join する
  useEffect(() => {
    const autoJoin = async () => {
      if (!meetingId || session || status === 'connecting') return;
      setMeetingCode(meetingId);
      setJoining(true);
      try {
        await joinMeeting(meetingId);
      } catch (err) {
        const message = err instanceof Error ? err.message : '参加に失敗しました';
        console.error('Failed to auto-join meeting', err);
        setMeetingCode(meetingId);
        setError(message);
      } finally {
        setJoining(false);
      }
    };
    void autoJoin();
  }, [meetingId, joinMeeting, session, status]);

  const joinSection = (
    <section className="panel join-card">
      <div className="panel-header">
        <h2>参加する</h2>
        <span className="badge ghost">Guest</span>
      </div>
      <p>管理者が配布した Meeting ID を入力してください。入室後に自動で文字起こしが始まります。</p>
      <form className="meeting-form" onSubmit={handleJoin}>
        <input
          type="text"
          placeholder="Meeting ID"
          value={meetingCode}
          onChange={(event) => setMeetingCode(event.target.value)}
        />
        <button type="submit" disabled={joining || status === 'connecting'}>
          {joining ? '接続中…' : '入室する'}
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );

  const handleLeave = () => {
    leaveMeeting();
    navigate('/');
  };

  const hasVideoCreds = Boolean(session?.apiKey && session?.sessionId && session?.token);

  let content = joinSection;
  try {
    if (session) {
      content = (
        <>
          <section className="panel meeting-overview">
            <div>
              <p className="label">現在のセッション</p>
              <h2>{session.title}</h2>
              <p className="label">Meeting ID</p>
              <code>{session.meetingId}</code>
            </div>
            <div className="session-meta">
              <div>
                <p className="label">Vonage Session</p>
                <p>{session.sessionId}</p>
              </div>
              <div>
                <p className="label">Vonage API Key</p>
                <p>{session.apiKey || '未設定'}</p>
              </div>
              <div>
                <p className="label">ステータス</p>
                <p className="status-text">{status === 'connected' ? 'ライブ中' : status}</p>
              </div>
            </div>
          </section>

          {hasVideoCreds ? (
            <VonageStage
              apiKey={session.apiKey}
              sessionId={session.sessionId}
              token={session.token}
              muted={isMuted}
              videoOff={isVideoOff}
            />
          ) : (
            <section className="panel video-stage live-video">
              <div className="panel-header">
                <h2>Vonage ビデオ</h2>
                <span className="status-chip error">video unavailable</span>
              </div>
              <div className="video-grid">
                <div className="video-tile speaking">
                  <div className="video-feed">
                    <p className="video-placeholder">ビデオ資格情報が不足しています。音声のみご利用ください。</p>
                  </div>
                </div>
              </div>
            </section>
          )}

          <div className="panel-grid">
            <section className="panel transcript-panel">
              <div className="panel-header">
                <h2>リアルタイム文字起こし</h2>
                <span className="badge">{transcripts.length} 件</span>
              </div>
              <div className="transcript-list">
                {transcripts.length === 0 && (
                  <p className="empty">まだ発話がありません。マイクをオンにして話してください。</p>
                )}
                {transcripts.map((entry, index) => (
                  <div key={`${entry.timestamp}-${index}`} className="transcript-item">
                    <div className="transcript-meta">
                      <span className="time">{formatTime(new Date(entry.timestamp))}</span>
                      <span className={`sentiment ${entry.sentiment?.toLowerCase()}`}>
                        {entry.sentiment}
                      </span>
                    </div>
                    <p className="transcript-text">{entry.transcript || '…'}</p>
                  </div>
                ))}
              </div>
            </section>
            <MetricsPanel samples={samples} />
          </div>

          <ControlBar
            status={status}
            isMuted={isMuted}
            isVideoOff={isVideoOff}
            handRaised={handRaised}
            onToggleMute={toggleMute}
            onToggleVideo={toggleVideo}
            onLeave={handleLeave}
          />
        </>
      );
    }
  } catch (err) {
    console.error('Failed to render session UI', err);
    content = (
      <section className="panel hero-session">
        <h2>表示に失敗しました</h2>
        <p>再読み込みするか、もう一度接続し直してください。</p>
        {joinSection}
      </section>
    );
  }

  return (
    <Layout
      title="MeetingPolice Live Session"
      subtitle="管理者が発行した Meeting ID を入力して Vonage でビデオ会議。音声はリアルタイム文字起こしされます。"
    >
      {content}
    </Layout>
  );
}
