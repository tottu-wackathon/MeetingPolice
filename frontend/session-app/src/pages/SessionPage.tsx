import { FormEvent, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Layout } from '../components/Layout';

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
  const [participants, setParticipants] = useState<Participant[]>([
    { id: 'local', name: 'You', role: 'host', isSpeaking: false },
    { id: 'guest1', name: 'Guest 1', role: 'guest', isSpeaking: false },
    { id: 'guest2', name: 'Guest 2', role: 'guest', isSpeaking: false }
  ]);
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
        {/* 参加者一覧 */}
        <section className="panel participants-panel">
          <div className="participants-grid">
            {participants.map((p) => (
              <div key={p.id} className="participant-window">
                <div className="participant-avatar">
                  {p.name?.charAt(0) || 'G'}
                </div>
                <div className="participant-controls">
                  <button 
                    type="button" 
                    onClick={toggleMute} 
                    className={`control-btn ${isMuted ? 'off' : ''}`}
                    title={isMuted ? 'ミュート解除' : 'ミュート'}
                  >
                    {isMuted ? '🔇' : '🎙️'}
                  </button>
                  <button 
                    type="button" 
                    onClick={toggleVideo} 
                    className={`control-btn ${isVideoOff ? 'off' : ''}`}
                    title={isVideoOff ? 'ビデオ再開' : 'ビデオ停止'}
                  >
                    {isVideoOff ? '📷' : '🎥'}
                  </button>
                  <button 
                    type="button" 
                    onClick={toggleHand} 
                    className={`control-btn ${handRaised ? 'active' : ''}`}
                    title={handRaised ? '手を下げる' : '手を挙げる'}
                  >
                    ✋
                  </button>
                  <button 
                    type="button" 
                    className="control-btn danger" 
                    onClick={handleLeave} 
                    title="退出"
                  >
                    🚪
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 文字起こしとリアルタイム分類の2列レイアウト */}
        <div className="content-grid">
          <section className="panel transcript-panel">
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

          <section className="panel classification-panel">
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
        </div>

        {/* ステータス情報 */}
        <section className="panel status-panel">
          <div className="status-grid">
            <div className="status-item">
              <span className="status-label">ID</span>
              <code className="status-value">{session.meetingId}</code>
            </div>
            <div className="status-item">
              <span className="status-label">状態</span>
              <span className="status-value">{status}</span>
            </div>
            <div className="status-item">
              <span className="status-label">参加人数</span>
              <span className="status-value">{participantCount}</span>
            </div>
          </div>
        </section>
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
