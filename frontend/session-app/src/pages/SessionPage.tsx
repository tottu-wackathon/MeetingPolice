import { FormEvent, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Layout } from '../components/Layout';

import { useMeetingSession } from '../hooks/useMeetingSession';
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

  const [transcripts, setTranscripts] = useState<Array<{ index: number; speaker: string; raw_speaker?: string; result_id?: string; text: string; timestamp: string }>>([]);
  const [realtimeClassifications, setRealtimeClassifications] = useState<
    Array<{ index: number; text: string; speaker: string; category: string; alignment: number; method: string; is_final?: boolean }>
  >([]);
  const [speakerStats, setSpeakerStats] = useState<Array<{ speaker: string; count: number; percentage: number; isNew?: boolean }>>([]);
  const knownSpeakersRef = useRef<Set<string>>(new Set());
  const [speakerNames, setSpeakerNames] = useState<{ [key: string]: string }>({});
  const wsRef = useRef<WebSocket | null>(null);
  
  // poc_satominと同じ警告機能
  const [showWarning, setShowWarning] = useState<boolean>(false);
  const [showPoliceWarning, setShowPoliceWarning] = useState<boolean>(false);
  const [policeWarningShownAt, setPoliceWarningShownAt] = useState<number | null>(null);
  const [lowAlignmentStartTime, setLowAlignmentStartTime] = useState<number | null>(null);
  const policeWarningTimeoutRef = useRef<number | null>(null);
  const speechSynthRef = useRef<SpeechSynthesisUtterance | null>(null);
  const alertIntervalRef = useRef<number | null>(null);

  // WebSocket接続とデータ処理
  useEffect(() => {
    if (!session?.meetingId) {
      setTranscripts([]);
      setRealtimeClassifications([]);
      return;
    }

    const wsUrl = buildWsUrl(session.meetingId);
    console.log('[SessionPage] Connecting to WebSocket:', wsUrl);
    
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[SessionPage] WebSocket connected');
    };

    ws.onmessage = (event) => {
      console.log('[SessionPage] Received message:', event.data);
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'transcript') {
          const payload = data;
          const action = 'append'; // sessionでは常にappend
          
          setTranscripts((prev) => {
            const key = payload.result_id ?? `idx-${payload.index}`;
            const exists = prev.some((item) => (item.result_id ?? `idx-${item.index}`) === key);
            
            if (!exists) {
              return [...prev, {
                index: payload.index || prev.length + 1,
                speaker: payload.speaker || 'Unknown',
                raw_speaker: payload.raw_speaker,
                result_id: payload.result_id,
                text: payload.transcript || payload.text || '',
                timestamp: payload.timestamp || new Date().toISOString(),
              }];
            } else {
              return prev.map((item) => {
                const itemKey = item.result_id ?? `idx-${item.index}`;
                if (itemKey !== key) return item;
                return {
                  ...item,
                  text: payload.transcript || payload.text || item.text,
                  speaker: payload.speaker || item.speaker,
                  raw_speaker: payload.raw_speaker || item.raw_speaker,
                };
              });
            }
          });
        } else if (data.type === 'realtime_classification') {
          const { index, text, speaker, category, alignment, method, is_final } = data.payload;
          const action = data.action || 'append';

          console.log(`[SessionPage] リアルタイム分析: ${speaker} - ${text} → [${category}] ${alignment}% (${method}${is_final ? ' 確定' : ''})`);

          setRealtimeClassifications((prev) => {
            const existingIndex = prev.findIndex((item) => item.index === index);

            if (existingIndex >= 0) {
              const updated = [...prev];
              updated[existingIndex] = { index, text, speaker, category, alignment, method, is_final };
              return updated;
            }

            return [...prev, { index, text, speaker, category, alignment, method, is_final }];
          });
        }
      } catch (err) {
        console.warn('[SessionPage] Failed to parse message:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('[SessionPage] WebSocket error:', error);
    };

    ws.onclose = (event) => {
      console.log('[SessionPage] WebSocket closed:', event.code, event.reason);
    };

    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [session?.meetingId]);

  // 話者別の発話ボリュームを計算（判別中は除外）
  useEffect(() => {
    const lengthMap: Record<string, number> = {};
    transcripts.forEach((item) => {
      if (item.speaker === '判別中...') return;
      const length = item.text.length;
      lengthMap[item.speaker] = (lengthMap[item.speaker] || 0) + length;
    });
    const total = Object.values(lengthMap).reduce((sum, v) => sum + v, 0);
    const stats = Object.entries(lengthMap)
      .map(([speaker, count]) => ({
        speaker,
        count,
        percentage: total > 0 ? Math.round((count / total) * 100) : 0,
        isNew: !knownSpeakersRef.current.has(speaker),
      }))
      .sort((a, b) => b.count - a.count);
    setSpeakerStats(stats);
    const merged = new Set(knownSpeakersRef.current);
    stats.forEach((s) => merged.add(s.speaker));
    knownSpeakersRef.current = merged;
  }, [transcripts]);

  const buildWsUrl = (meetingId: string) => {
    const apiBase = import.meta.env.VITE_API_BASE ?? '/api';
    if (apiBase.startsWith('http')) {
      const url = new URL(apiBase);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const basePath = url.pathname.endsWith('/') ? url.pathname.slice(0, -1) : url.pathname;
      return `${url.origin}${basePath}/session/ws/${meetingId}`;
    }
    const origin = window.location.origin.replace(/^http/, 'ws');
    const base = apiBase.endsWith('/') ? apiBase.slice(0, -1) : apiBase;
    return `${origin}${base}/session/ws/${meetingId}`;
  };

  const displaySpeaker = (speaker: string) => {
    const name = speakerNames[speaker];
    return name ? `${name}さん` : speaker;
  };
  const { meetingId } = useParams();
  const navigate = useNavigate();

  const [meetingCode, setMeetingCode] = useState('');
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([
    { id: 'local', name: 'You', role: 'host', isSpeaking: false }
  ]);

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

  // poc_satominと同じ音声アラート機能
  const playVoiceAlert = (message: string) => {
    if (message === '一致度が低下しています') {
      const audio = new Audio('/alert-sound.mp3');
      audio.volume = 1.0;
      audio.addEventListener('canplaythrough', () => {
        audio.play().catch(error => {
          console.error('音声ファイルの再生に失敗:', error);
          playTextToSpeech(message);
        });
      });
      audio.load();
      return;
    }
    playTextToSpeech(message);
  };

  const playTextToSpeech = (message: string) => {
    if (speechSynthRef.current) {
      window.speechSynthesis.cancel();
    }
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.lang = 'ja-JP';
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    speechSynthRef.current = utterance;
    window.speechSynthesis.speak(utterance);
  };

  // poc_satominと同じ警告ロジック
  useEffect(() => {
    if (!session || realtimeClassifications.length === 0) {
      if (alertIntervalRef.current) {
        clearInterval(alertIntervalRef.current);
        alertIntervalRef.current = null;
      }
      if (speechSynthRef.current) {
        window.speechSynthesis.cancel();
      }
      setShowWarning(false);
      return;
    }

    const validItems = realtimeClassifications.filter(item => item.text.length >= 10);
    if (validItems.length < 3) {
      setShowWarning(false);
      return;
    }

    const recentItems = validItems.slice(-5);
    const avgAlignment = Math.round(
      recentItems.reduce((sum, item) => sum + item.alignment, 0) / recentItems.length
    );

    const now = Date.now();

    if (avgAlignment <= 30) {
      if (lowAlignmentStartTime === null) {
        setLowAlignmentStartTime(now);
      }

      const shouldShowPolice =
        policeWarningShownAt === null ||
        (now - policeWarningShownAt >= 5 * 60 * 1000);

      if (shouldShowPolice && !showPoliceWarning) {
        setShowPoliceWarning(true);
        setPoliceWarningShownAt(now);
        setShowWarning(false);

        if (policeWarningTimeoutRef.current) {
          clearTimeout(policeWarningTimeoutRef.current);
        }
        policeWarningTimeoutRef.current = window.setTimeout(() => {
          setShowPoliceWarning(false);
        }, 15000);
      } else if (!shouldShowPolice) {
        setShowWarning(true);
        setShowPoliceWarning(false);
      }
    } else if (avgAlignment <= 50) {
      setShowWarning(true);
      setShowPoliceWarning(false);
      setLowAlignmentStartTime(null);
    } else {
      setShowWarning(false);
      setShowPoliceWarning(false);
      setLowAlignmentStartTime(null);
    }

    const shouldAlert = avgAlignment <= 50;
    const isAlertActive = alertIntervalRef.current !== null;

    if (shouldAlert && !isAlertActive) {
      playVoiceAlert('一致度が低下しています');
      alertIntervalRef.current = window.setInterval(() => {
        playVoiceAlert('一致度が低下しています');
      }, 60000);
    } else if (!shouldAlert && isAlertActive) {
      if (alertIntervalRef.current) {
        clearInterval(alertIntervalRef.current);
        alertIntervalRef.current = null;
      }
      if (speechSynthRef.current) {
        window.speechSynthesis.cancel();
      }
    }
  }, [realtimeClassifications, session]);

  // クリーンアップ
  useEffect(() => {
    return () => {
      if (alertIntervalRef.current) {
        clearInterval(alertIntervalRef.current);
        alertIntervalRef.current = null;
      }
      if (policeWarningTimeoutRef.current) {
        clearTimeout(policeWarningTimeoutRef.current);
        policeWarningTimeoutRef.current = null;
      }
    };
  }, []);

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
                {p.id === 'local' && (
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
                )}
              </div>
            ))}
          </div>
        </section>

        {/* poc_satominと同じ2列レイアウト */}
        <div className="poc-columns">
          <div className="poc-left">
            {/* 左側は空 - sessionでは参加者一覧が上にあるため */}
          </div>

          <div className="poc-right">
            <section className="panel transcript-panel">
              <div className="panel-header" style={{ flexWrap: 'nowrap', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'nowrap' }}>
                  <p className="label" style={{ margin: 0, whiteSpace: 'nowrap' }}>リアルタイム文字起こし</p>
                  <h2 style={{ margin: 0, whiteSpace: 'nowrap' }}>{transcripts.length} 行</h2>
                </div>
              </div>
              <div className="transcript-feed">
                {transcripts.map((item) => (
                  <article key={item.timestamp + item.index} className="transcript-item">
                    <header>
                      <strong>{displaySpeaker(item.speaker)}</strong>
                      {item.raw_speaker && <span className="pill mono">{item.raw_speaker}</span>}
                      <span>{item.timestamp}</span>
                    </header>
                    <p>{item.text}</p>
                  </article>
                ))}
                {transcripts.length === 0 && <p className="faded">発言を開始すると文字起こしが表示されます。</p>}
              </div>
            </section>

            <section className="panel">
              <div className="panel-header" style={{ flexWrap: 'nowrap', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'nowrap' }}>
                  <p className="label" style={{ margin: 0, whiteSpace: 'nowrap' }}>🔍 リアルタイム分析</p>
                  <h2 style={{ margin: 0, whiteSpace: 'nowrap' }}>{realtimeClassifications.length} 件</h2>
                </div>
              </div>

              {speakerStats.length > 0 && (
                <div
                  style={{
                    padding: '15px',
                    backgroundColor: 'rgba(255, 255, 255, 0.3)',
                    borderRadius: '8px',
                    marginBottom: '16px',
                    border: '2px solid #00ffff'
                  }}
                >
                  <p style={{ margin: '0 0 12px 0', fontSize: '0.9em', color: '#00ffff', fontWeight: 'bold' }}>
                    👥 話者別発言割合
                  </p>
                  {speakerStats.map(({ speaker, count, percentage, isNew }) => {
                    const displayName = speakerNames[speaker] ? `${speakerNames[speaker]}さん` : speaker;
                    const barColor = percentage >= 85 ? '#ff4444' : percentage >= 70 ? '#ffaa00' : '#00ff00';

                    return (
                      <div
                        key={speaker}
                        className="speaker-card"
                        style={{
                          marginBottom: '12px',
                          animation: isNew ? 'mpFadeSlide 0.4s ease' : undefined
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ color: '#00ffff', fontSize: '0.9em' }}>
                              {displayName}
                            </span>
                            <input
                              type="text"
                              placeholder="名前を入力"
                              value={speakerNames[speaker] || ''}
                              onChange={(e) => setSpeakerNames({ ...speakerNames, [speaker]: e.target.value })}
                              style={{
                                width: '120px',
                                padding: '4px 8px',
                                fontSize: '0.8em',
                                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                                border: '1px solid #00ffff',
                                borderRadius: '4px',
                                color: '#00ffff'
                              }}
                            />
                          </div>
                          <span style={{ color: barColor, fontSize: '0.9em', fontWeight: 'bold' }}>{percentage}%</span>
                        </div>
                        <div
                          style={{
                            width: '100%',
                            height: '8px',
                            backgroundColor: 'rgba(0, 0, 0, 0.3)',
                            borderRadius: '4px',
                            overflow: 'hidden'
                          }}
                        >
                          <div
                            className="speaker-bar"
                            style={{
                              width: `${percentage}%`,
                              height: '100%',
                              backgroundColor: barColor
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {realtimeClassifications.length > 0 && (() => {
                // コメント（短い発言）を除外
                const validItems = realtimeClassifications.filter(item => item.text.length >= 10);
                if (validItems.length === 0) return null;

                const recent10 = validItems.slice(-10);
                // 直近5件に重み3、それ以前に重み1の加重平均
                const weightsForRecent = recent10.map((_, idx) => (idx >= recent10.length - 5 ? 3 : 1));
                const totalWeightForRecent = weightsForRecent.reduce((s, w) => s + w, 0) || 1;
                const avgAlignment = recent10.length
                  ? Math.round(
                    recent10.reduce((sum, item, idx) => sum + item.alignment * weightsForRecent[idx], 0) / totalWeightForRecent
                  )
                  : 0;

                const padding = 8; // 両端が見切れないように少し余白

                const barWidth = recent10.length ? (100 - padding * 2) / recent10.length : 0;
                const bars = recent10.map((item, idx) => {
                  const x = padding + idx * barWidth + barWidth * 0.1;
                  const height = Math.max(0, Math.min(100, item.alignment));
                  const y = 100 - height;
                  return { x, y, height, value: item.alignment };
                });

                const toPoints = (items: typeof recent10) =>
                  items.map((item, idx) => {
                    const x =
                      items.length === 1
                        ? 50
                        : padding + ((idx / (items.length - 1)) * (100 - padding * 2));
                    const y = Math.min(100 - padding, Math.max(padding, 100 - item.alignment));
                    return { x, y, value: item.alignment };
                  });

                const buildSmoothPath = (pts: Array<{ x: number; y: number }>) => {
                  if (pts.length === 0) return '';
                  if (pts.length === 1) return `M ${pts[0].x},${pts[0].y}`;
                  let d = `M ${pts[0].x},${pts[0].y}`;
                  for (let i = 1; i < pts.length; i++) {
                    const prev = pts[i - 1];
                    const curr = pts[i];
                    const mx = (prev.x + curr.x) / 2;
                    const my = (prev.y + curr.y) / 2;
                    d += ` Q ${prev.x},${prev.y} ${mx},${my}`;
                  }
                  d += ` T ${pts[pts.length - 1].x},${pts[pts.length - 1].y}`;
                  return d;
                };

                const weightedAvgPoints = (() => {
                  const weights = recent10.map((_, idx) => (idx >= recent10.length - 5 ? 3 : 1));
                  const cumulativeWeights: number[] = [];
                  let sumW = 0;
                  weights.forEach((w) => {
                    sumW += w;
                    cumulativeWeights.push(sumW);
                  });
                  let cum = 0;
                  return recent10.map((item, idx) => {
                    cum += item.alignment * weights[idx];
                    const avg = cum / (cumulativeWeights[idx] || 1);
                    return { alignment: avg };
                  });
                })();

                const pointsWeighted = toPoints(
                  weightedAvgPoints.map((p) => ({ ...p, text: '', speaker: '' })) as any
                );
                const pathDWeighted = buildSmoothPath(pointsWeighted);

                return (
                  <div
                    className="alignment-card"
                    style={{
                      padding: '20px',
                      backgroundColor: 'rgba(255, 255, 255, 0.08)',
                      borderRadius: '8px',
                      marginBottom: '16px',
                      border: '2px solid #00ffff'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                      <div>
                        <p style={{ margin: '0 0 8px 0', fontSize: '0.9em', color: '#00ffff' }}>
                          会議治安指数
                        </p>
                        <div
                          style={{
                            fontSize: '2.6em',
                            fontWeight: 'bold',
                            color: avgAlignment >= 60 ? '#4caf50' : avgAlignment >= 40 ? '#ff9800' : '#f44336',
                            lineHeight: '1',
                            textShadow: '0 0 12px rgba(0,255,255,0.6)'
                          }}
                        >
                          {avgAlignment}%
                        </div>
                      </div>
                      <div style={{ flex: 1.4 }}>
                        <svg className="alignment-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
                          <defs>
                            <linearGradient id="alignStroke" x1="0%" y1="0%" x2="100%" y2="0%">
                              <stop offset="0%" stopColor="#00ffff" stopOpacity="0.9" />
                              <stop offset="100%" stopColor="#00e676" stopOpacity="0.9" />
                            </linearGradient>
                            <linearGradient id="alignStroke2" x1="0%" y1="0%" x2="100%" y2="0%">
                              <stop offset="0%" stopColor="#ff8a65" stopOpacity="0.9" />
                              <stop offset="100%" stopColor="#ff5252" stopOpacity="0.9" />
                            </linearGradient>
                            <linearGradient id="alignFill" x1="0%" y1="0%" x2="0%" y2="100%">
                              <stop offset="0%" stopColor="rgba(0, 255, 255, 0.35)" />
                              <stop offset="100%" stopColor="rgba(0, 255, 255, 0)" />
                            </linearGradient>
                          </defs>
                          {/* 警告・警察ライン */}
                          <line x1="0" x2="100" y1={100 - 50} y2={100 - 50} stroke="#ff9800" strokeDasharray="4 4" strokeWidth="0.8" />
                          <line x1="0" x2="100" y1={100 - 30} y2={100 - 30} stroke="#ff1744" strokeDasharray="4 4" strokeWidth="0.8" />
                          {/* 棒グラフ: 発話ごとのスコア */}
                          {bars.map((b, idx) => {
                            const barColor =
                              b.value <= 0
                                ? 'rgba(255, 255, 255, 0.2)'
                                : b.value <= 30
                                  ? '#f44336'
                                  : b.value <= 50
                                    ? '#ff9800'
                                    : 'rgba(0,255,255,0.35)';
                            const strokeColor =
                              b.value <= 30 ? '#ff1744' : b.value <= 50 ? '#ffb74d' : 'rgba(0,255,255,0.6)';
                            return (
                              <g key={idx}>
                                <rect
                                  x={b.x}
                                  y={b.y}
                                  width={barWidth * 0.8}
                                  height={b.height}
                                  fill={barColor}
                                  stroke={strokeColor}
                                  strokeWidth="0.8"
                                  rx="1.5"
                                />
                                {b.value <= 0 && (
                                  <text
                                    x={b.x + (barWidth * 0.8) / 2}
                                    y={100 - 2}
                                    textAnchor="middle"
                                    fontSize="9"
                                    fill="#ffca28"
                                    style={{ filter: 'drop-shadow(0 0 3px rgba(0,0,0,0.7))' }}
                                  >
                                    ⚠️
                                  </text>
                                )}
                              </g>
                            );
                          })}
                          {/* ライン（加重平均の推移） */}
                          <path d={pathDWeighted} stroke="url(#alignStroke)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                          {/* ポイント（平均） */}
                          {pointsWeighted.map((p, idx) => (
                            <circle
                              key={idx}
                              cx={p.x}
                              cy={p.y}
                              r={2.2}
                              fill="#00ffff"
                              stroke="#0a0e27"
                              strokeWidth="0.7"
                            />
                          ))}
                        </svg>
                      </div>
                    </div>
                  </div>
                );
              })()}

              <div className="transcript-feed" style={{ maxHeight: '500px', overflowY: 'auto' }}>
                {realtimeClassifications
                  .filter(item => item.text.length >= 10)
                  .map((item, index) => {
                    const isFinal = item.is_final === true;
                    const icon = isFinal ? '✅' : '📊';
                    const bgColor = item.alignment >= 50 ? '#4caf50' : item.alignment >= 20 ? '#ff9800' : '#f44336';

                    return (
                      <article key={index} className="transcript-item">
                        <header>
                          <strong>{displaySpeaker(item.speaker)}</strong>
                          <span className="pill">{item.category}</span>
                          <span className="pill" style={{ backgroundColor: bgColor }}>
                            {icon} {item.alignment}%
                          </span>
                          {isFinal && <span className="pill" style={{ backgroundColor: '#2196f3', color: 'white' }}>AI確定</span>}
                        </header>
                        <p>{item.text}</p>
                      </article>
                    );
                  })}
                {realtimeClassifications.filter(item => item.text.length >= 10).length === 0 && <p className="faded">発言を開始するとリアルタイム分析結果が表示されます。</p>}
              </div>
            </section>
          </div>
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
      {showWarning && (
        <div style={{
          position: 'fixed',
          top: '20px',
          left: '0',
          right: '0',
          margin: '0 auto',
          width: 'fit-content',
          zIndex: 9999,
          padding: '30px 50px',
          backgroundColor: '#ff9800',
          color: 'white',
          borderRadius: '16px',
          fontSize: '2em',
          fontWeight: 'bold',
          boxShadow: '0 12px 32px rgba(255, 152, 0, 0.6)',
          animation: 'pulse 1.5s ease-in-out infinite',
          border: '6px solid #fff'
        }}>
          ⚠️ 一致度が落ちています ⚠️
        </div>
      )}
      {showPoliceWarning && (
        <div style={{
          position: 'fixed',
          top: '20px',
          left: '0',
          right: '0',
          margin: '0 auto',
          width: 'fit-content',
          zIndex: 9999,
          padding: '30px 50px',
          backgroundColor: '#ff1744',
          color: 'white',
          borderRadius: '16px',
          fontSize: '2em',
          fontWeight: 'bold',
          boxShadow: '0 12px 32px rgba(255, 23, 68, 0.6)',
          animation: 'pulse 1s ease-in-out infinite',
          border: '6px solid #fff'
        }}>
          🚨 警察出動！ 🚨
        </div>
      )}
      {content}
    </Layout>
  );
}
