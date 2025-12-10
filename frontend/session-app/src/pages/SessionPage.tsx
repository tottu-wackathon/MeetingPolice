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
import type { Participant } from '../types';

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
  const [realtimeClassifications, setRealtimeClassifications] = useState<
    Array<{ index: number; text: string; speaker: string; category: string; alignment: number; method: string; is_final?: boolean; timestamp?: string }>
  >([]);
  const { transcripts } = useTranscripts(session?.meetingId, (payload) => {
    setRealtimeClassifications((prev) => {
      const exists = prev.find((p) => p.index === payload.index);
      if (exists) {
        return prev.map((p) => (p.index === payload.index ? { ...p, ...payload } : p));
      }
      return [...prev, payload].slice(-20);
    });
  });
  const { meetingId } = useParams();
  const navigate = useNavigate();

  const [meetingCode, setMeetingCode] = useState('');
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([{ id: 'local', name: 'You', role: 'host', isSpeaking: false }]);
  const [alignmentAlert, setAlignmentAlert] = useState<string | null>(null);
  const [avgAlignment, setAvgAlignment] = useState<number | null>(null);

  const handleJoin = async (event: FormEvent) => {
    event.preventDefault();
    if (!meetingCode.trim()) return;
    setJoining(true);
    setJoinError(null);
    try {
      await joinMeeting(meetingCode);
      navigate(`/session/${meetingCode.trim()}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : '参加に失敗しました';
      console.error('Failed to join meeting', err);
      setJoinError(message);
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
      setJoinError(null);
      try {
        await joinMeeting(meetingId);
      } catch (err) {
        const message = err instanceof Error ? err.message : '参加に失敗しました';
        console.error('Failed to auto-join meeting', err);
        setMeetingCode(meetingId);
        setJoinError(message);
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
      {(joinError || error) && (
        <p className="error" role="alert">
          {joinError || error}
        </p>
      )}
    </section>
  );

  const handleLeave = () => {
    leaveMeeting();
    navigate('/');
  };

  const videoEnabled = Boolean(session?.videoEnabled && session?.apiKey && session?.sessionId && session?.token);
  const videoFallbackMessage = !videoEnabled
    ? 'ビデオ資格情報を取得できなかったため音声のみで参加しています。'
    : null;
  const participantCount = participants.length;

  useEffect(() => {
    if (realtimeClassifications.length === 0) {
      setAvgAlignment(null);
      setAlignmentAlert(null);
      return;
    }
    const recent = realtimeClassifications.slice(-5);
    const avg = Math.round(
      recent.reduce((sum, item) => sum + (typeof item.alignment === 'number' ? item.alignment : 0), 0) /
        recent.length,
    );
    setAvgAlignment(avg);
    if (avg <= 30) {
      setAlignmentAlert('議題との一致度が低い発話が続いています（平均30%以下）');
    } else if (avg <= 50) {
      setAlignmentAlert('議題との一致度が低下しています（平均50%以下）');
    } else {
      setAlignmentAlert(null);
    }
  }, [realtimeClassifications]);

  let content = joinSection;

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
              <p>{videoEnabled ? session.sessionId : 'ビデオ未接続'}</p>
            </div>
            <div>
              <p className="label">Vonage API Key</p>
              <p>{videoEnabled ? session.apiKey : '未設定（音声のみ）'}</p>
            </div>
            <div>
              <p className="label">ステータス</p>
              <p className="status-text">{status === 'connected' ? 'ライブ中' : status}</p>
            </div>
            <div>
              <p className="label">参加者</p>
              <p className="status-text">{participantCount} 人</p>
            </div>
          </div>
          <div className="participant-chips">
            {participants.map((p) => (
              <span key={p.id} className="badge ghost">
                👤 {p.name || 'Guest'}
              </span>
            ))}
          </div>
        </section>

        <VonageStage
          apiKey={session.apiKey}
          sessionId={session.sessionId}
          token={session.token}
          muted={isMuted}
          videoOff={isVideoOff}
          enabled={videoEnabled}
          fallbackNotice={videoFallbackMessage}
          onParticipantsChange={(list) => {
            const normalized = list.map((p) => ({
              id: p.id,
              name: p.name || 'Guest',
              role: p.role,
              isSpeaking: false,
            }));
            setParticipants(normalized.length > 0 ? normalized : [{ id: 'local', name: 'You', role: 'host', isSpeaking: false }]);
          }}
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

        <section className="panel classification-panel">
          <div className="panel-header">
            <div>
              <p className="label">リアルタイム分類</p>
              <h2>{realtimeClassifications.length} 件</h2>
            </div>
            {avgAlignment !== null && (
              <span className="badge ghost">平均適合度 {avgAlignment}%</span>
            )}
          </div>
          {alignmentAlert && <p className="error" role="alert">{alignmentAlert}</p>}
          {realtimeClassifications.length === 0 && (
            <p className="faded">発話が確定すると Bedrock で分類結果が表示されます。</p>
          )}
          {realtimeClassifications.length > 0 && (
            <div className="classification-list">
              {realtimeClassifications.slice().reverse().map((item) => (
                <article key={item.index} className="classification-row">
                  <div className="classification-meta">
                    <strong>{item.speaker || 'Unknown'}</strong>
                    <span className="alignment-tag">適合度 {typeof item.alignment === 'number' ? `${item.alignment}%` : '―'}</span>
                    <span className="category-tag">{item.category}</span>
                    {item.timestamp && <span className="mono">{item.timestamp}</span>}
                  </div>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <ControlBar
          status={status}
          isMuted={isMuted}
          isVideoOff={isVideoOff}
          handRaised={handRaised}
          onToggleMute={toggleMute}
          onToggleVideo={toggleVideo}
          onToggleHand={toggleHand}
          onLeave={handleLeave}
        />
      </>
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
