import { useState } from 'react';
import type { MeetingSession, Participant } from '../types';
import { validateMeetingId, joinMeeting } from '../services/api';

export function useMeetingSession() {
  const envApiKey = import.meta.env.VITE_VONAGE_APP_ID as string | undefined;
  const envSessionId = import.meta.env.VITE_VONAGE_SESSION_ID as string | undefined;
  const envToken = import.meta.env.VITE_VONAGE_TOKEN as string | undefined;
  const hasEnvSession = Boolean(envApiKey && envSessionId && envToken);

  const [session, setSession] = useState<MeetingSession | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const [isVideoOff, setIsVideoOff] = useState(false);
  const [handRaised, setHandRaised] = useState(false);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const connect = async (meetingId: string) => {
    setStatus('connecting');
    setError(null);
    const trimmed = meetingId.trim();
    if (!trimmed) {
      setStatus('error');
      setError('Meeting ID を入力してください');
      throw new Error('Meeting ID required');
    }

    // バリデーション
    try {
      await validateMeetingId(trimmed);
    } catch (err) {
      const message = err instanceof Error ? err.message : '入力されたIDのミーティングは開催されていません';
      setStatus('error');
      setError(message);
      throw err;
    }

    // 1) バックエンドから Vonage 資格情報を取得
    try {
      const data = await joinMeeting(trimmed);
      const videoEnabled = Boolean(data.apiKey && data.sessionId && data.token);
      const sessionPayload = { ...data, videoEnabled };
      setSession(sessionPayload);
      setStatus('connected');
      return sessionPayload;
    } catch (err) {
      const message = err instanceof Error ? err.message : '参加に失敗しました';
      setError(message);
      // 2) フロントの固定値でフォールバック
      if (hasEnvSession) {
        const fallbackSession: MeetingSession = {
          meetingId: trimmed || 'static-meeting',
          title: 'Static Vonage Session',
          status: 'live',
          sessionId: envSessionId!,
          token: envToken!,
          apiKey: envApiKey!,
          videoEnabled: true,
          participants: [{ id: 'local', name: 'You', role: 'host', isSpeaking: false }],
        };
        setSession(fallbackSession);
        setStatus('connected');
        return fallbackSession;
      }
      // 3) 音声のみ
      const audioOnly: MeetingSession = {
        meetingId: trimmed || 'audio-only',
        title: 'Audio-only session',
        status: 'audio-only',
        sessionId: '',
        token: '',
        apiKey: '',
        videoEnabled: false,
        participants: [{ id: 'local', name: 'You', role: 'host', isSpeaking: false }],
      };
      setSession(audioOnly);
      setStatus('connected');
      return audioOnly;
    }
  };

  const create = async (title: string, scheduledFor?: string) => {
    setStatus('connecting');
    setError(null);
    // create も固定値のみ使用
    if (hasEnvSession) {
      const fallbackSession: MeetingSession = {
        meetingId: `mtg-${Date.now()}`,
        title: title || 'Static Vonage Session',
        status: 'live',
        sessionId: envSessionId!,
        token: envToken!,
        apiKey: envApiKey!,
        videoEnabled: true,
        participants: [{ id: 'local', name: 'You', role: 'host', isSpeaking: false }],
      };
      setSession(fallbackSession);
      setStatus('connected');
      return fallbackSession;
    }

    const audioOnly: MeetingSession = {
      meetingId: `mtg-${Date.now()}`,
      title: title || 'Audio-only session',
      status: 'audio-only',
      sessionId: '',
      token: '',
      apiKey: '',
      videoEnabled: false,
      participants: [{ id: 'local', name: 'You', role: 'host', isSpeaking: false }],
    };
    setSession(audioOnly);
    setStatus('connected');
    setError('Vonage の環境変数が設定されていません。音声のみで参加します。');
    return audioOnly;
  };

  const leave = () => {
    setSession(null);
    setStatus('idle');
    setIsMuted(false);
    setIsVideoOff(false);
    setHandRaised(false);
  };

  const toggleMute = () => setIsMuted((prev) => !prev);
  const toggleVideo = () => setIsVideoOff((prev) => !prev);
  const toggleHand = () => setHandRaised((prev) => !prev);

  const updateParticipantSpeaking = (id: string, isSpeaking: boolean) => {
    setSession((prev) => {
      if (!prev) return prev;
      const participants: Participant[] = prev.participants.map((p) =>
        p.id === id ? { ...p, isSpeaking } : p
      );
      return { ...prev, participants };
    });
  };

  return {
    session,
    isMuted,
    isVideoOff,
    handRaised,
    status,
    error,
    createMeeting: create,
    joinMeeting: connect,
    leaveMeeting: leave,
    toggleMute,
    toggleVideo,
    toggleHand,
    updateParticipantSpeaking,
  };
}
