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
        <div className="session-grid">
          <div className="left-column">
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
            <section className="panel transcript-panel compact">
              <div className="panel-header">
                <h2>文字起こし</h2>
                <span className="badge">{transcripts.length}</span>
              </div>
              <div className="transcript-list">
                {transcripts.length === 0 && (
                  <p className="empty">発話すると表示されます。</p>
                )}
                {transcripts.map((entry, index) => (
                  <div key={`${entry.timestamp}-${index}`} className="transcript-item">
                    <div className="transcript-meta">
                      <span className="time">{formatTime(new Date(entry.timestamp))}</span>
                    </div>
                    <p className="transcript-text">{entry.transcript || '…'}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="right-column">
            <section className="panel classification-panel compact">
              <div className="panel-header">
                <div>
                  <h2>リアルタイム分類</h2>
                </div>
                {avgAlignment !== null && (
                  <span className="badge ghost">平均 {avgAlignment}%</span>
                )}
              </div>
              {alignmentAlert && <p className="error" role="alert">{alignmentAlert}</p>}
              {realtimeClassifications.length === 0 && (
                <p className="faded">確定した発話が分類されます。</p>
              )}
              {realtimeClassifications.length > 0 && (
                <div className="classification-list">
                  {realtimeClassifications.slice().reverse().map((item) => (
                    <article key={item.index} className="classification-row">
                      <div className="classification-meta">
                        <span className="category-tag">{item.category}</span>
                        <span className="alignment-tag">{typeof item.alignment === 'number' ? `${item.alignment}%` : '―'}</span>
                      </div>
                      <p>{item.text}</p>
                    </article>
                  ))}
                </div>
              )}
            </section>
            <MetricsPanel samples={samples} />
          </div>
        </div>

        <section className="panel meeting-overview compact">
          <div className="session-meta small">
            <span className="badge ghost">Meeting ID</span>
            <code>{session.meetingId}</code>
            <span className="badge ghost">Status</span>
            <span className="mono">{status}</span>
            <span className="badge ghost">Participants</span>
            <span className="mono">{participantCount}</span>
          </div>
          <div className="participant-chips">
            {participants.map((p) => (
              <span key={p.id} className="badge ghost">
                👤 {p.name || 'Guest'}
              </span>
            ))}
          </div>
        </section>

        <ControlBar
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
      title="Meeting Session"
      subtitle=""
    >
      {content}
    </Layout>
  );
}
