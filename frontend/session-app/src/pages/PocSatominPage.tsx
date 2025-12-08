import { FormEvent, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout } from '../components/Layout';
import type {
  PocTranscript,
  PocArchivedJob,
  PocHistoryItem,
} from '../types';
import {
  fetchArchivedSatominJob,
  fetchPocSatominHistory,
  fetchPocSatominJob,
  startPocSatominRun,
} from '../services/api';

const buildWsUrl = (path: string) => {
  const apiBase = import.meta.env.VITE_API_BASE ?? '/api';
  if (apiBase.startsWith('http')) {
    const url = new URL(apiBase);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const basePath = url.pathname.endsWith('/') ? url.pathname.slice(0, -1) : url.pathname;
    return `${url.origin}${basePath}${path}`;
  }
  const origin = window.location.origin.replace(/^http/, 'ws');
  const base = apiBase.endsWith('/') ? apiBase.slice(0, -1) : apiBase;
  return `${origin}${base}${path}`;
};

export function PocSatominPage() {
  const navigate = useNavigate();
  const [agendaFile, setAgendaFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioPreviewUrl, setAudioPreviewUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<PocTranscript[]>([]);
  const [status, setStatus] = useState<'idle' | 'streaming' | 'complete'>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const [jobAgenda, setJobAgenda] = useState<string>('');
  const [history, setHistory] = useState<PocHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyPreview, setHistoryPreview] = useState<PocArchivedJob | null>(null);
  const [realtimeClassifications, setRealtimeClassifications] = useState<Array<{ index: number; text: string; speaker: string; category: string; alignment: number; method: string; is_final?: boolean }>>([]);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [scheduledMinutes, setScheduledMinutes] = useState<number | null>(null);
  const [showWarning, setShowWarning] = useState<boolean>(false);
  const [showPoliceWarning, setShowPoliceWarning] = useState<boolean>(false);
  const [policeWarningShownAt, setPoliceWarningShownAt] = useState<number | null>(null);
  const [lowAlignmentStartTime, setLowAlignmentStartTime] = useState<number | null>(null);
  const policeWarningTimeoutRef = useRef<number | null>(null);
  const [speakerStats, setSpeakerStats] = useState<Array<{ speaker: string; count: number; percentage: number; isNew?: boolean }>>([]);
  const knownSpeakersRef = useRef<Set<string>>(new Set());
  const [speakerNames, setSpeakerNames] = useState<{ [key: string]: string }>({});
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const speechSynthRef = useRef<SpeechSynthesisUtterance | null>(null);
  const alertIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  // タイマー管理
  useEffect(() => {
    if (status === 'streaming') {
      // タイマー開始
      setElapsedSeconds(0);
      timerRef.current = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      // タイマー停止
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [status]);

  useEffect(() => {
    if (!audioFile) {
      setAudioPreviewUrl((prev) => {
        if (prev) {
          URL.revokeObjectURL(prev);
        }
        return null;
      });
      return;
    }
    const url = URL.createObjectURL(audioFile);
    setAudioPreviewUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [audioFile]);

  useEffect(() => {
    const fetchJob = async () => {
      if (status !== 'complete' || !jobId) return;
      try {
        const detail = await fetchPocSatominJob(jobId);
        setJobAgenda(detail.agenda_text);
        extractScheduledTime(detail.agenda_text);
      } catch (err) {
        console.error(err);
      }
    };
    fetchJob();
  }, [jobId, status]);

  // アジェンダから予定時間を抽出
  const extractScheduledTime = (agendaText: string) => {
    if (!agendaText) {
      setScheduledMinutes(null);
      return;
    }
    // 「30分」「1時間」「90分」などのパターンを検索
    const minuteMatch = agendaText.match(/(\d+)\s*分/);
    const hourMatch = agendaText.match(/(\d+)\s*時間/);

    if (minuteMatch) {
      setScheduledMinutes(parseInt(minuteMatch[1], 10));
      console.log(`⏰ 予定時間: ${minuteMatch[1]}分`);
    } else if (hourMatch) {
      setScheduledMinutes(parseInt(hourMatch[1], 10) * 60);
      console.log(`⏰ 予定時間: ${hourMatch[1]}時間`);
    } else {
      setScheduledMinutes(null);
    }
  };

  useEffect(() => {
    const loadHistory = async () => {
      setHistoryLoading(true);
      try {
        const items = await fetchPocSatominHistory();
        setHistory(items);
      } catch (err) {
        console.error(err);
      } finally {
        setHistoryLoading(false);
      }
    };
    loadHistory();
  }, []);

  // 話者別の発話ボリュームを事前計算（判別中は除外）
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

  const handleStart = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    setJobAgenda('');
    setScheduledMinutes(null);
    if (!audioFile) {
      setMessage('音声ファイルを選択してください。');
      return;
    }
    const formData = new FormData();
    if (agendaFile) {
      formData.append('agenda', agendaFile);
      // アジェンダファイルから予定時間を抽出
      const agendaText = await agendaFile.text();
      setJobAgenda(agendaText);
      extractScheduledTime(agendaText);
    }
    formData.append('audio', audioFile);
    try {
      const response = await startPocSatominRun(formData);
      setJobId(response.job_id);
      setTranscripts([]);
      setRealtimeClassifications([]);
      setStatus('streaming');
      connectWebSocket(response.job_id);
      if (audioRef.current && audioPreviewUrl) {
        audioRef.current.currentTime = 0;
        const playPromise = audioRef.current.play();
        if (playPromise) {
          playPromise.catch((err) => console.warn('Audio autoplay blocked', err));
        }
      }
    } catch (err) {
      const text = err instanceof Error ? err.message : 'アップロードに失敗しました';
      setMessage(text);
    }
  };

  const connectWebSocket = (id: string) => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    const wsUrl = buildWsUrl(`/poc_satomin/ws/${id}`);
    console.log('🔌 WebSocket接続開始:', wsUrl);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('✅ WebSocket接続成功！');
    };

    ws.onmessage = (event) => {
      console.log('📨 WebSocketメッセージ受信:', event.data);
      const data = JSON.parse(event.data);
      if (data.type === 'transcript') {
        const payload = data.payload as PocTranscript;
        const action = (data.action as 'append' | 'update' | undefined) ?? 'append';
        setTranscripts((prev) => {
          const key = payload.result_id ?? `idx-${payload.index}`;
          const updateExisting = (items: PocTranscript[]) =>
            items.map((item) => {
              const itemKey = item.result_id ?? `idx-${item.index}`;
              if (itemKey !== key) return item;
              return { ...item, ...payload };
            });
          const exists = prev.some((item) => (item.result_id ?? `idx-${item.index}`) === key);
          if (action === 'append') {
            if (exists) {
              return updateExisting(prev);
            }
            return [...prev, payload];
          }
          if (action === 'update' && exists) {
            return updateExisting(prev);
          }
          return prev;
        });
      } else if (data.type === 'realtime_classification') {
        // リアルタイム分析結果を受信
        const { index, text, speaker, category, alignment, method, is_final } = data.payload;
        const action = (data.action as 'update' | undefined) ?? 'append';

        console.log(`🔍 リアルタイム分析: ${speaker} - ${text} → [${category}] ${alignment}% (${method}${is_final ? ' 確定' : ''})`);

        setRealtimeClassifications((prev) => {
          // indexで既存の項目を探す
          const existingIndex = prev.findIndex((item) => item.index === index);

          if (existingIndex >= 0) {
            // 既存の項目を更新
            const updated = [...prev];
            updated[existingIndex] = { index, text, speaker, category, alignment, method, is_final };
            return updated;
          }

          // 新規追加
          return [...prev, { index, text, speaker, category, alignment, method, is_final }];
        });
      } else if (data.type === 'complete') {
        setStatus('complete');
        setMessage('文字起こしが完了しました。');
        ws.close();
      } else if (data.type === 'error') {
        setMessage(data.message);
      }
    };
    ws.onerror = (error) => {
      console.error('❌ WebSocketエラー:', error);
      setMessage('WebSocket への接続に失敗しました。');
    };
    ws.onclose = (event) => {
      console.log('🔌 WebSocket切断:', event.code, event.reason);
      wsRef.current = null;
    };
  };

  const refreshHistory = async () => {
    setHistoryLoading(true);
    try {
      const items = await fetchPocSatominHistory();
      setHistory(items);
    } catch (err) {
      console.error(err);
    } finally {
      setHistoryLoading(false);
    }
  };

  const loadHistoryPreview = async (id: string) => {
    try {
      const data = await fetchArchivedSatominJob(id);
      setHistoryPreview(data);
      setMessage(`過去ジョブ ${id} を読み込みました。`);
    } catch (err) {
      const text = err instanceof Error ? err.message : '過去の文字起こし取得に失敗しました';
      setMessage(text);
    }
  };

  // 時間を「MM:SS」形式にフォーマット
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // タイマーの状態を判定（normal / warning / danger）
  const getTimerStatus = (): 'normal' | 'warning' | 'danger' => {
    if (!scheduledMinutes) return 'normal';
    const scheduledSeconds = scheduledMinutes * 60;
    const remainingSeconds = scheduledSeconds - elapsedSeconds;
    const remainingPercent = (remainingSeconds / scheduledSeconds) * 100;

    if (remainingSeconds <= 0) return 'danger'; // 超過
    if (remainingPercent <= 15) return 'warning'; // 残り15%以下
    return 'normal';
  };

  // 音声アラートを再生
  const playVoiceAlert = (message: string) => {
    // 既存の音声を停止
    if (speechSynthRef.current) {
      window.speechSynthesis.cancel();
    }

    // 新しい音声を作成
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.lang = 'ja-JP';
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    speechSynthRef.current = utterance;
    window.speechSynthesis.speak(utterance);
  };

  // 直近5件の平均一致度をチェック
  useEffect(() => {
    if (status !== 'streaming' || realtimeClassifications.length === 0) {
      // ストリーミング中でない場合はアラートをクリア
      if (alertIntervalRef.current) {
        clearInterval(alertIntervalRef.current);
        alertIntervalRef.current = null;
      }
      // 音声合成も停止
      if (speechSynthRef.current) {
        window.speechSynthesis.cancel();
      }
      setShowWarning(false);
      return;
    }

    const validItems = realtimeClassifications.filter(item => item.text.length >= 10);
    if (validItems.length < 3) {
      // 最低3件のデータがないとチェックしない
      setShowWarning(false);
      return;
    }

    // 直近5件の平均一致度を計算
    const recentItems = validItems.slice(-5);
    const avgAlignment = Math.round(
      recentItems.reduce((sum, item) => sum + item.alignment, 0) / recentItems.length
    );

    const now = Date.now();

    // 30%以下の状態を追跡
    if (avgAlignment <= 30) {
      // 初めて30%以下になった時刻を記録
      if (lowAlignmentStartTime === null) {
        setLowAlignmentStartTime(now);
      }

      // 警察出動警告の表示判定
      const shouldShowPolice =
        // まだ一度も表示していない、または
        policeWarningShownAt === null ||
        // 前回表示から5分以上経過している
        (now - policeWarningShownAt >= 5 * 60 * 1000);

      if (shouldShowPolice && !showPoliceWarning) {
        setShowPoliceWarning(true);
        setPoliceWarningShownAt(now);
        setShowWarning(false);

        // 15秒後に自動で消す
        if (policeWarningTimeoutRef.current) {
          clearTimeout(policeWarningTimeoutRef.current);
        }
        policeWarningTimeoutRef.current = window.setTimeout(() => {
          setShowPoliceWarning(false);
        }, 15000);
      } else if (!shouldShowPolice) {
        // 5分経過していない場合は通常警告を表示
        setShowWarning(true);
        setShowPoliceWarning(false);
      }
    }
    // 50%以下で通常警告
    else if (avgAlignment <= 50) {
      setShowWarning(true);
      setShowPoliceWarning(false);
      setLowAlignmentStartTime(null); // 30%以下の状態をリセット
    }
    // 50%超えたら警告なし
    else {
      setShowWarning(false);
      setShowPoliceWarning(false);
      setLowAlignmentStartTime(null); // 30%以下の状態をリセット
    }

    // 50%以下で音声アラートを1分ごとに流す
    const shouldAlert = avgAlignment <= 50;
    const isAlertActive = alertIntervalRef.current !== null;

    if (shouldAlert && !isAlertActive) {
      // アラートを開始
      playVoiceAlert('一致度が下がっています');
      alertIntervalRef.current = window.setInterval(() => {
        playVoiceAlert('一致度が下がっています');
      }, 60000);
    } else if (!shouldAlert && isAlertActive) {
      // アラートを停止（インターバルと音声合成の両方）
      clearInterval(alertIntervalRef.current);
      alertIntervalRef.current = null;
      if (speechSynthRef.current) {
        window.speechSynthesis.cancel();
      }
    }
  }, [realtimeClassifications, status]);

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

  // ミーティングを終了してリザルト画面へ遷移
  const handleStopMeeting = () => {
    // 音声を停止
    if (speechSynthRef.current) {
      window.speechSynthesis.cancel();
    }

    // アラートインターバルを停止
    if (alertIntervalRef.current) {
      clearInterval(alertIntervalRef.current);
      alertIntervalRef.current = null;
    }

    // 全ての一致度の平均を計算
    const validItems = realtimeClassifications.filter(item => item.text.length >= 10);
    const avgAlignment = validItems.length > 0
      ? Math.round(validItems.reduce((sum, item) => sum + item.alignment, 0) / validItems.length)
      : 0;

    // 話者ごとの発話ボリューム（文字数）を計算
    const speakerCounts: { [key: string]: number } = {};
    transcripts.forEach(item => {
      if (item.speaker === '判別中...') return;
      const length = item.text.length;
      speakerCounts[item.speaker] = (speakerCounts[item.speaker] || 0) + length;
    });

    navigate('/result', {
      state: {
        agendaText: jobAgenda,
        elapsedSeconds: elapsedSeconds,
        avgAlignment: avgAlignment,
        totalItems: validItems.length,
        scheduledMinutes: scheduledMinutes,
        speakerCounts: speakerCounts,
        speakerNames: speakerNames,
      },
    });
  };

  const displaySpeaker = (speaker: string) => {
    const name = speakerNames[speaker];
    return name ? `${name}さん` : speaker;
  };

  return (
    <Layout title="MeetingPolice PoC Satomin" subtitle="アジェンダと音声をアップロードし、リアルタイム文字起こしを確認できます。">
      {showWarning && (
        <div style={{
          position: 'fixed',
          top: '20px',
          left: '0',
          right: '0',
          margin: '0 auto',
          width: 'fit-content',
          zIndex: 9999,
          padding: '20px 40px',
          backgroundColor: '#ff9800',
          color: 'white',
          borderRadius: '12px',
          fontSize: '1.5em',
          fontWeight: 'bold',
          boxShadow: '0 8px 24px rgba(255, 152, 0, 0.4)',
          animation: 'pulse 1.5s ease-in-out infinite',
          border: '4px solid #fff'
        }}>
          ⚠️ 一致度が落ちています！ ⚠️
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
          border: '6px solid #fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '20px',
          whiteSpace: 'nowrap'
        }}>
          <img
            src="/police-icon.png.png"
            alt="警察官"
            style={{
              width: '80px',
              height: '80px'
            }}
          />
          <span>🚨 警察出動！ 🚨</span>
          <img
            src="/police-icon.png.png"
            alt="警察官"
            style={{
              width: '80px',
              height: '80px'
            }}
          />
        </div>
      )}
      <div className="poc-columns">
        <div className="poc-left">
          <section className="panel poc-upload">
            <h2>PoC Satomin: アジェンダ &amp; 音声のアップロード</h2>
            <p>音声は Transcribe Streaming で処理され、結果が右のパネルにリアルタイムで届きます。</p>
            <form className="poc-form" onSubmit={handleStart}>
              <label className="upload-field">
                <span>アジェンダファイル（任意）</span>
                <input type="file" accept=".txt,.md,.doc,.docx,.pdf" onChange={(event) => setAgendaFile(event.target.files?.[0] ?? null)} />
                {agendaFile && <small>{agendaFile.name}</small>}
              </label>
              <label className="upload-field">
                <span>音声ファイル（必須）</span>
                <input type="file" accept="audio/*" onChange={(event) => setAudioFile(event.target.files?.[0] ?? null)} required />
                {audioFile && <small>{audioFile.name}</small>}
              </label>
              {status === 'idle' ? (
                <button type="submit">
                  文字起こしを開始
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleStopMeeting}
                  style={{
                    width: '100%',
                    backgroundColor: 'rgba(255, 68, 68, 0.3)',
                    borderColor: '#ff4444',
                    color: '#ff4444'
                  }}
                >
                  ⏹️ ミーティングを終了
                </button>
              )}
            </form>
            {message && <p className="info-text">{message}</p>}
            {jobId && (
              <div className="job-meta">
                <p className="label">Job ID</p>
                <code>{jobId}</code>
                <p className="label">ステータス</p>
                <span className={`pill ${status}`}>{status}</span>
                {/* 経過時間表示（将来的に使用する可能性があるためコメントアウト）
                {(status === 'streaming' || status === 'complete') && (
                  <>
                    <p className="label">経過時間</p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                      <span
                        className="pill"
                        style={{
                          fontSize: '1.2em',
                          backgroundColor: getTimerStatus() === 'danger' ? '#f44336' : getTimerStatus() === 'warning' ? '#ff9800' : '#4caf50',
                          color: 'white'
                        }}
                      >
                        ⏱️ {formatTime(elapsedSeconds)}
                      </span>
                      {scheduledMinutes && (
                        <span style={{ fontSize: '0.9em', color: '#666' }}>
                          / {scheduledMinutes}分
                          {getTimerStatus() === 'danger' && ' ⚠️ 超過！'}
                          {getTimerStatus() === 'warning' && ' ⚠️ まもなく終了'}
                        </span>
                      )}
                    </div>
                  </>
                )}
                */}
              </div>
            )}
            {audioPreviewUrl && (
              <div className="audio-preview">
                <p className="label">アップロード音声</p>
                <audio ref={audioRef} src={audioPreviewUrl} controls />
              </div>
            )}
          </section>

          {jobAgenda && (
            <section className="panel">
              <h2>アジェンダ</h2>
              <div className="agenda-preview">
                <pre>{jobAgenda || '（未指定）'}</pre>
              </div>
            </section>
          )}

          <section className="panel history-panel">
            <div className="panel-header">
              <div>
                <p className="label">過去の文字起こし</p>
                <h2>{history.length} 件</h2>
              </div>
              <button type="button" className="ghost" onClick={refreshHistory} disabled={historyLoading}>
                {historyLoading ? '更新中…' : '履歴を更新'}
              </button>
            </div>
            {history.length === 0 && <p className="faded">これまでのアーカイブはまだありません。</p>}
            {history.length > 0 && (
              <div className="history-list">
                {[...history].reverse().map((item) => (
                  <article key={item.job_id} className="history-item">
                    <div>
                      <strong>{item.archive_name || item.job_id}</strong>
                      <p className="label">{item.completed_at || item.job_id}</p>
                      {item.archive_name && <p className="faded mono">{item.job_id}</p>}
                      <p className="agenda-preview-text">{item.agenda_preview || '（アジェンダなし）'}</p>
                    </div>
                    <div className="history-actions">
                      <button type="button" className="ghost" onClick={() => loadHistoryPreview(item.job_id)}>
                        表示
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
            {historyPreview && (
              <div className="history-preview" style={{ fontSize: '0.85em', maxHeight: '400px', overflow: 'auto' }}>
                <p className="label">選択中: {historyPreview.archive_name || historyPreview.job_id}</p>
                <p className="label">アジェンダ（全文）</p>
                <pre style={{ fontSize: '0.9em', maxHeight: '150px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                  {historyPreview.agenda_text || '（なし）'}
                </pre>
                <p className="label">文字起こし（全文）</p>
                <div className="history-transcripts" style={{ fontSize: '0.85em', maxHeight: '200px', overflow: 'auto' }}>
                  {historyPreview.transcripts.map((item) => (
                    <p key={item.index} style={{ margin: '4px 0' }}>
                      <strong>{item.speaker}:</strong> {item.text}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </section>
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
              {transcripts.length === 0 && <p className="faded">アップロード後に文字起こしが表示されます。</p>}
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
              {realtimeClassifications.filter(item => item.text.length >= 10).length === 0 && <p className="faded">文字起こし完了後にリアルタイム分析結果が表示されます。</p>}
            </div>
          </section>
        </div>
      </div>
    </Layout>
  );
}
