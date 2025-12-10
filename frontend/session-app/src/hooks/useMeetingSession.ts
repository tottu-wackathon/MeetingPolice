import { useState } from 'react';
import type { MeetingSession, Participant } from '../types';

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
    // Vonage 接続は .env の固定値のみを使う
    if (hasEnvSession) {
      const fallbackSession: MeetingSession = {
        meetingId: meetingId.trim() || 'static-meeting',
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

    // 環境変数が無ければ音声のみのローカルセッション
    const audioOnly: MeetingSession = {
      meetingId: meetingId.trim() || 'audio-only',
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
    setError('Vonage の環境変数が設定されていません。音声のみで参加します。');
    return audioOnly;
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
