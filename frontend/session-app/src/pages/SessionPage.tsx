import { FormEvent, useState } from 'react';
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

  const [meetingCode, setMeetingCode] = useState('');
  const [joining, setJoining] = useState(false);

  const handleJoin = async (event: FormEvent) => {
    event.preventDefault();
    if (!meetingCode.trim()) return;
    setJoining(true);
    try {
      await joinMeeting(meetingCode);
    } finally {
      setJoining(false);
    }
  };

  return (
    <Layout
      title="MeetingPolice Live Session"
      subtitle="管理者が発行した Meeting ID を入力して Vonage でビデオ会議。音声はリアルタイム文字起こしされます。"
    >
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

      {session ? (
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

          <VonageStage
            apiKey={session.apiKey}
            sessionId={session.sessionId}
            token={session.token}
            muted={isMuted}
            videoOff={isVideoOff}
          />

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
            onToggleHand={toggleHand}
            onLeave={leaveMeeting}
          />
        </>
      ) : (
        <section className="panel hero-session">
          <h2>poc_satomin のフローを踏襲したライブモード</h2>
          <p>上の「セッションを作成」で Meeting ID を発行し、参加者に共有してください。</p>
          <ul className="instructions">
            <li>参加者は共有された ID を入力して Vonage でビデオ参加できます。</li>
            <li>接続すると自動で文字起こしが開始され、左側のパネルに流れます。</li>
            <li>マイクとカメラは下部のコントロールバーでいつでも切り替え可能です。</li>
          </ul>
        </section>
      )}
    </Layout>
  );
}
