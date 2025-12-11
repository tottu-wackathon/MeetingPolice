import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Layout } from '../components/Layout';

import { useMeetingSession } from '../hooks/useMeetingSession';
import { useTranscripts } from '../hooks/useTranscripts';

export function SessionPage() {
  const {
    session,
    status,
    error,
    joinMeeting,
    leaveMeeting,
    isMuted,
  } = useMeetingSession();
  const sessionStartRef = useRef<number | null>(null);

  const [realtimeClassifications, setRealtimeClassifications] = useState<
    Array<{ index: number; text: string; speaker: string; category: string; alignment: number; method: string; is_final?: boolean }>
  >([]);
  const [speakerStats, setSpeakerStats] = useState<Array<{ speaker: string; count: number; percentage: number; isNew?: boolean }>>([]);
  const knownSpeakersRef = useRef<Set<string>>(new Set());
  const [speakerNames, setSpeakerNames] = useState<{ [key: string]: string }>({});
  const [agendaPreview, setAgendaPreview] = useState<string>('');
  
  // 🔍 CONNECTION HEALTH MONITORING
  const [connectionHealth, setConnectionHealth] = useState({
    lastTranscriptTime: Date.now(),
    transcriptCount: 0,
    isHealthy: true,
    connectionDuration: 0
  });

  // 警察出動とアライメント警告の状態管理（古いロジックのみ使用）

  // useTranscriptsフックを使用してマイクアクセスと文字起こしを処理
  const { transcripts } = useTranscripts(
    session?.meetingId,
    (payload) => {
      // リアルタイム分析結果を受信
      const { index, text, speaker, category, alignment, method, is_final } = payload;
      
      setRealtimeClassifications((prev) => {
        // デバッグ用ログ - 受信したpayloadの詳細を表示
        console.log('[SessionPage] Realtime classification received - RAW payload:', payload);
        console.log('[SessionPage] Extracted values:', { 
          index, 
          text: text ? `"${text.slice(0, 50)}${text.length > 50 ? '...' : ''}"` : 'undefined',
          textLength: text?.length || 0,
          speaker, 
          category, 
          alignment, 
          method, 
          is_final 
        });
        
        // textが存在しない場合の警告
        if (!text || text.length === 0) {
          console.warn('[SessionPage] WARNING: Received classification with empty or missing text!');
          return prev; // 空のテキストの場合は追加しない
        }
        
        // 同じindexの全てのエントリを削除（古いキーワード結果を除去）
        const filteredPrev = prev.filter(item => item.index !== index);
        
        // 新しいエントリを追加
        const newEntry = { index, text, speaker, category, alignment, method, is_final };
        console.log('[SessionPage] Adding new entry:', newEntry);
        
        return [...filteredPrev, newEntry];
      });
    },
    isMuted // ミュート状態を渡す
  );
  
  // 🔍 CONNECTION HEALTH MONITORING
  useEffect(() => {
    if (transcripts.length > 0) {
      const now = Date.now();
      setConnectionHealth(prev => ({
        lastTranscriptTime: now,
        transcriptCount: transcripts.length,
        isHealthy: true,
        connectionDuration: now - (prev.connectionDuration || now)
      }));
    }
  }, [transcripts]);
  
  // 🔍 REALTIME CLASSIFICATIONS MONITORING
  useEffect(() => {
    console.log('[SessionPage] Realtime classifications updated:', realtimeClassifications.length, 'items');
    console.log('[SessionPage] Valid items (length >= 10):', realtimeClassifications.filter(item => item.text && item.text.length >= 10).length);
  }, [realtimeClassifications]);
  
  // 🔍 HEALTH CHECK: Detect if transcription stopped
  useEffect(() => {
    const healthCheckInterval = setInterval(() => {
      const now = Date.now();
      const timeSinceLastTranscript = now - connectionHealth.lastTranscriptTime;
      
      if (timeSinceLastTranscript > 60000 && session) { // 1 minute without transcripts
        console.warn('🚨 Transcription may have stopped - no transcripts for', timeSinceLastTranscript / 1000, 'seconds');
        setConnectionHealth(prev => ({ ...prev, isHealthy: false }));
      }
    }, 10000); // Check every 10 seconds
    
    return () => clearInterval(healthCheckInterval);
  }, [connectionHealth.lastTranscriptTime, session]);
  
  // poc_satominと同じ警告機能
  const [showWarning, setShowWarning] = useState<boolean>(false);
  const [showPoliceWarning, setShowPoliceWarning] = useState<boolean>(false);
  const [policeWarningShownAt, setPoliceWarningShownAt] = useState<number | null>(null);
  const [lowAlignmentStartTime, setLowAlignmentStartTime] = useState<number | null>(null);
  const policeWarningTimeoutRef = useRef<number | null>(null);
  const speechSynthRef = useRef<SpeechSynthesisUtterance | null>(null);
  const alertIntervalRef = useRef<number | null>(null);



  // 話者別の発話ボリュームを計算（判別中は除外）
  useEffect(() => {
    const lengthMap: Record<string, number> = {};
    transcripts.forEach((item) => {
      const speaker = item.speaker || 'Unknown';
      if (speaker === '判別中...') return;
      const length = item.transcript.length;
      lengthMap[speaker] = (lengthMap[speaker] || 0) + length;
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



  const displaySpeaker = (speaker: string) => {
    const name = speakerNames[speaker];
    return name ? `${name}さん` : speaker;
  };
  const { meetingId } = useParams();
  const navigate = useNavigate();

  const [meetingCode, setMeetingCode] = useState('');
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  // アジェンダ関連のstate
  const [selectedAgenda, setSelectedAgenda] = useState<File | null>(null);

  // アジェンダファイル選択ハンドラー
  const handleAgendaSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file && file.type === 'text/plain') {
      setSelectedAgenda(file);
      // 選択したアジェンダをローカルでプレビュー用に保持
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result === 'string') {
          setAgendaPreview(reader.result);
        }
      };
      reader.readAsText(file);
    } else if (file) {
      alert('テキストファイル(.txt)を選択してください');
      event.target.value = '';
    }
  };

  const handleJoin = async (event: FormEvent) => {
    event.preventDefault();
    // Meeting IDが空の場合はデフォルト値を使用
    const finalMeetingCode = meetingCode.trim() || 'mtg-1765456864';
    setJoining(true);
    setJoinError(null);
    try {
      // まずミーティングが存在するかチェック、なければ作成
      try {
        const validateResponse = await fetch(`/api/session/meetings/${finalMeetingCode}/validate`);
        if (!validateResponse.ok) {
          // ミーティングが存在しない場合は作成
          console.log('Meeting not found, creating new meeting...');
          const createResponse = await fetch('/api/session/meetings', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              title: `Auto-created meeting ${finalMeetingCode}`,
              meeting_id: finalMeetingCode
            }),
          });
          
          if (!createResponse.ok) {
            throw new Error('ミーティングの作成に失敗しました');
          }
          console.log('Meeting created successfully');
        }
      } catch (createError) {
        console.error('Error creating meeting:', createError);
        // 作成に失敗してもjoinを試行する
      }
      
      // アジェンダファイルがある場合は先にアップロード
      if (selectedAgenda) {
        const formData = new FormData();
        formData.append('file', selectedAgenda);
        
        const response = await fetch(`/api/session/meetings/${finalMeetingCode}/agenda`, {
          method: 'POST',
          body: formData,
        });
        
        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.detail || 'アジェンダのアップロードに失敗しました');
        }
        
        console.log('Agenda uploaded successfully');
      }
      
      await joinMeeting(finalMeetingCode);
      navigate(`/session/${finalMeetingCode}`);
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

  // セッション開始時刻を記録
  useEffect(() => {
    if (session && !sessionStartRef.current) {
      sessionStartRef.current = Date.now();
    }
  }, [session]);

  const buildResultData = () => {
    const validFinal = realtimeClassifications.filter(item => item.text.length >= 10 && item.is_final === true);
    const avgAlignment = validFinal.length
      ? Math.round(validFinal.reduce((sum, item) => sum + item.alignment, 0) / validFinal.length)
      : 100;
    const speakerCounts: Record<string, number> = {};
    speakerStats.forEach(({ speaker, count }) => {
      speakerCounts[speaker] = count;
    });
    const elapsedSeconds = sessionStartRef.current ? Math.round((Date.now() - sessionStartRef.current) / 1000) : 0;
    return {
      agendaText: agendaPreview,
      elapsedSeconds,
      avgAlignment,
      totalItems: transcripts.length || validFinal.length,
      speakerCounts,
      speakerNames,
    };
  };

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
        
        <div className="agenda-section" style={{ margin: '16px 0' }}>
          <label htmlFor="agenda-file" style={{ 
            display: 'block', 
            marginBottom: '8px', 
            color: '#00ffff',
            fontSize: '0.9em'
          }}>
            📄 アジェンダファイル (オプション)
          </label>
          <input
            id="agenda-file"
            type="file"
            accept=".txt"
            onChange={handleAgendaSelect}
            style={{
              width: '100%',
              padding: '8px',
              backgroundColor: 'rgba(0, 0, 0, 0.3)',
              border: '1px solid #00ffff',
              borderRadius: '4px',
              color: '#00ffff',
              fontSize: '0.9em'
            }}
          />
          {selectedAgenda && (
            <p style={{ 
              margin: '8px 0 0 0', 
              fontSize: '0.8em', 
              color: '#4caf50' 
            }}>
              ✓ 選択済み: {selectedAgenda.name}
            </p>
          )}
        </div>
        
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
    const resultData = buildResultData();
    leaveMeeting();
    navigate('/result', { state: resultData });
  };

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

    // Bedrockで確定した結果のみを使用（is_final: true）
    const validItems = realtimeClassifications.filter(item => 
      item.text.length >= 10 && item.is_final === true
    );
    if (validItems.length < 3) {
      setShowWarning(false);
      return;
    }

    const recentItems = validItems.slice(-5);
    const avgAlignment = Math.round(
      recentItems.reduce((sum, item) => sum + item.alignment, 0) / recentItems.length
    );
    
    // デバッグ用ログ
    console.log('[SessionPage] Warning check:', {
      validItemsCount: validItems.length,
      recentItemsCount: recentItems.length,
      avgAlignment,
      showWarning,
      showPoliceWarning
    });

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
        }, 10000);
      } else if (!shouldShowPolice) {
        setShowWarning(true);
        setShowPoliceWarning(false);
      }
    } else if (avgAlignment <= 50) {
      // 警察出動後5秒以内の場合は警察出動警告を継続
      const timeSincePoliceWarning = policeWarningShownAt ? (now - policeWarningShownAt) : Infinity;
      
      if (timeSincePoliceWarning <= 5000 && showPoliceWarning) {
        // 警察出動警告を継続（何もしない）
        console.log('[SessionPage] Keeping police warning active (within 5s grace period)');
      } else {
        // 5秒経過後または警察出動警告が非アクティブの場合は一致度低下警告に切り替え
        setShowWarning(true);
        setShowPoliceWarning(false);
      }
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

  const renderSecurityIndexPanel = () => {
    // Bedrockで確定した結果のみを使用（is_final: true）
    const validItems = realtimeClassifications.filter(item => 
      item.text.length >= 10 && item.is_final === true
    );

    const recent10 = validItems.slice(-10);
    const hasData = recent10.length > 0;

    const padding = 8;
    const barWidth = hasData ? (100 - padding * 2) / recent10.length : 0;
    const bars = hasData
      ? recent10.map((item, idx) => {
          const xCenter = padding + idx * barWidth + barWidth * 0.4;
          const x = xCenter - (barWidth * 0.8) / 2;
          const height = Math.max(0, Math.min(100, item.alignment));
          const y = 100 - height;
          return { x, y, height, value: item.alignment, center: xCenter };
        })
      : [];

    const toPoints = (items: Array<{ alignment: number }>) =>
      items.map((item, idx) => {
        const x =
          items.length === 1
            ? 50
            : padding + idx * barWidth + barWidth * 0.4;
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

    const weightsForRecent = hasData ? recent10.map((_, idx) => (idx >= recent10.length - 5 ? 3 : 1)) : [];
    const totalWeightForRecent = weightsForRecent.reduce((s, w) => s + w, 0) || 1;
    const avgAlignment = hasData
      ? Math.round(
          recent10.reduce((sum, item, idx) => sum + item.alignment * weightsForRecent[idx], 0) / totalWeightForRecent
        )
      : 100;

    const weightedAvgPoints = hasData
      ? (() => {
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
            const alignment = cum / (cumulativeWeights[idx] || 1);
            return { alignment };
          });
        })()
      : [];

    const pointsWeighted = hasData ? toPoints(weightedAvgPoints) : [];
    const pathDWeighted = hasData ? buildSmoothPath(pointsWeighted) : '';
    const indexColor = hasData ? (avgAlignment >= 60 ? '#4caf50' : avgAlignment >= 40 ? '#ff9800' : '#f44336') : '#00e676';
    const statusText = hasData ? (avgAlignment >= 60 ? '✅ 良好' : avgAlignment >= 40 ? '⚠️ 注意' : '🚨 危険') : '🟢 スタンバイ';
    const statusClass = hasData ? (avgAlignment >= 60 ? 'good' : avgAlignment >= 40 ? 'warn' : 'danger') : 'standby';

    return (
      <section className="panel security-index-panel">
        <div className="panel-header">
          <h2>🚨 会議治安指数</h2>
          {!hasData && <span className="pill slim">初回の発話待ち</span>}
        </div>
        <div className="security-index-content">
          <div className="index-display">
            <div className="index-metrics">
              <div className="index-number" style={{ color: indexColor }}>
                {avgAlignment}%
              </div>
              <div className={`index-status ${statusClass}`}>
                {statusText}
              </div>
            </div>
            {!hasData && (
              <p className="standby-hint">グラフは初回の発話を受信したら更新します。現在は100%でスタンバイ中です。</p>
            )}
          </div>
          <div className="alignment-chart-container">
            <svg className="alignment-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <linearGradient id="alignStroke" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#00ffff" stopOpacity="0.9" />
                  <stop offset="100%" stopColor="#00e676" stopOpacity="0.9" />
                </linearGradient>
              </defs>
              {/* 警告・警察ライン */}
              <line x1="0" x2="100" y1={100 - 50} y2={100 - 50} stroke="#ff9800" strokeDasharray="4 4" strokeWidth="0.8" />
              <line x1="0" x2="100" y1={100 - 30} y2={100 - 30} stroke="#ff1744" strokeDasharray="4 4" strokeWidth="0.8" />
              {/* 棒グラフ */}
              {bars.map((b, idx) => {
                const barColor = b.value <= 30 ? '#f44336' : b.value <= 50 ? '#ff9800' : 'rgba(0,255,255,0.35)';
                return (
                  <rect
                    key={idx}
                    x={b.x}
                    y={b.y}
                    width={barWidth * 0.8}
                    height={b.height}
                    fill={barColor}
                    rx="1.5"
                  />
                );
              })}
              {/* ライン */}
              {hasData && <path d={pathDWeighted} stroke="url(#alignStroke)" strokeWidth="2.6" fill="none" strokeLinecap="round" />}
              {/* ポイント */}
              {hasData && pointsWeighted.map((p, idx) => (
                <circle key={idx} cx={p.x} cy={p.y} r={2.2} fill="#00ffff" stroke="#0a0e27" strokeWidth="0.7" />
              ))}
            </svg>
          </div>
        </div>
      </section>
    );
  };

  let content = joinSection;

  if (session) {
    content = (
      <>
        <section className="session-top-bar">
          <div className="session-meta">
            <span className="pill slim">Meeting: {session.meetingId}</span>
            <span className={`status-chip ${status}`}>{status}</span>
          </div>
          <button 
            type="button" 
            className="pill slim leave-btn" 
            onClick={handleLeave}
            title="退出"
          >
            🚪 退出
          </button>
        </section>

        {/* 2列: 左に文字起こし、右に会議治安指数 */}
        <div className="main-grid">
          <section className="panel transcript-panel">
            <div className="panel-header">
              <h2>📝 リアルタイム文字起こし</h2>
              <span className="transcript-count">{transcripts.length} 行</span>
            </div>
            <div className="transcript-feed large-text">
              {transcripts.map((item, arrayIndex) => (
                <article 
                  key={item.index !== undefined ? `transcript-${item.index}` : `${item.timestamp}-${arrayIndex}`} 
                  className={`transcript-item ${item.isPartial ? 'partial' : 'final'}`}
                >
                  <header>
                    <strong className="speaker-name">{displaySpeaker(item.speaker || 'Unknown')}</strong>
                    <span className="timestamp">{new Date(item.timestamp).toLocaleTimeString()}</span>
                    {item.isPartial && <span className="pill partial-pill">更新中</span>}
                    {!item.isPartial && <span className="pill final-pill">確定</span>}
                  </header>
                  <p className={`transcript-text ${item.isPartial ? 'partial-text' : 'final-text'}`}>
                    {item.transcript}
                    {item.isPartial && <span className="cursor">|</span>}
                  </p>
                </article>
              ))}
              {transcripts.length === 0 && <p className="faded">発言を開始すると文字起こしが表示されます。</p>}
            </div>
          </section>

          {renderSecurityIndexPanel()}
        </div>

        {/* 下段: 分析結果と話者識別 */}
        <section className="panel analysis-results-panel">
          <div className="panel-header">
            <h2>🔍 リアルタイム分析結果</h2>
            <span className="analysis-count">{realtimeClassifications.length} 件</span>
          </div>
          <div className="analysis-feed">
            {realtimeClassifications
              .filter(item => item.text && item.text.length >= 5) // テスト用に5文字以上に変更
              // 最新の10件のみ表示（パフォーマンス向上）
              .slice(-10)
              .reverse() // 最新が上に表示されるように逆順にする
              .map((item, arrayIndex) => {
                const isFinal = item.is_final === true;
                const icon = isFinal ? '✅' : '📊';
                const bgColor = item.alignment >= 50 ? '#4caf50' : item.alignment >= 20 ? '#ff9800' : '#f44336';

                return (
                  <article key={`analysis-${item.index}-${item.text.slice(0, 20)}`} className="analysis-item">
                    <header>
                      <strong>{displaySpeaker(item.speaker)}</strong>
                      <span className="pill category-pill">{item.category}</span>
                      <span className="pill alignment-pill" style={{ backgroundColor: bgColor }}>
                        {icon} {item.alignment}%
                      </span>
                      {isFinal && <span className="pill final-pill">AI確定</span>}
                    </header>
                    <p>{item.text || '[テキストなし]'}</p>
                    <small style={{color: '#666', fontSize: '0.7em'}}>
                      DEBUG: text="{item.text}", length={item.text?.length || 0}
                    </small>
                  </article>
                );
              })}
            {realtimeClassifications.filter(item => item.text.length >= 10).length === 0 && 
              <p className="faded">発言を開始するとリアルタイム分析結果が表示されます。</p>}
          </div>
        </section>

        {speakerStats.length > 0 && (
          <section className="panel speaker-stats-panel">
            <div className="panel-header">
              <h2>👥 話者識別・発言割合</h2>
            </div>
            <div className="speaker-stats-grid">
              {speakerStats.map(({ speaker, percentage, isNew }) => {
                const displayName = speakerNames[speaker] ? `${speakerNames[speaker]}さん` : speaker;
                const barColor = percentage >= 85 ? '#ff4444' : percentage >= 70 ? '#ffaa00' : '#00ff00';

                return (
                  <div key={speaker} className={`speaker-card ${isNew ? 'new-speaker' : ''}`}>
                    <div className="speaker-info">
                      <span className="speaker-display-name">{displayName}</span>
                      <input
                        type="text"
                        placeholder="名前を入力"
                        value={speakerNames[speaker] || ''}
                        onChange={(e) => setSpeakerNames({ ...speakerNames, [speaker]: e.target.value })}
                        className="speaker-name-input"
                      />
                      <span className="speaker-percentage" style={{ color: barColor }}>{percentage}%</span>
                    </div>
                    <div className="speaker-bar-container">
                      <div className="speaker-bar" style={{ width: `${percentage}%`, backgroundColor: barColor }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
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
          top: '180px',
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
          top: '200px',
          left: '0',
          right: '0',
          margin: '0 auto',
          width: 'fit-content',
          maxWidth: '90vw',
          zIndex: 9999,
          padding: '30px 50px',
          backgroundColor: '#ff1744',
          color: 'white',
          borderRadius: '16px',
          fontSize: '2em',
          fontWeight: 'bold',
          boxShadow: '0 12px 32px rgba(255, 23, 68, 0.6)',
          animation: 'pulse 1s ease-in-out infinite',
          border: '6px solid #fff',
          textAlign: 'center'
        }}>
          🚨 警察出動！ 🚨
        </div>
      )}
      {content}
    </Layout>
  );
}
