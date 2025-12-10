export type Participant = {
  id: string;
  name: string;
  role: 'host' | 'guest';
  isSpeaking: boolean;
};

export type MeetingSession = {
  meetingId: string;
  title: string;
  status: string;
  sessionId: string;
  token: string;
  apiKey: string;
  participants: Participant[];
  videoEnabled?: boolean;
};

export type AnalyticsSample = {
  timestamp: string;
  sentiment: 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL' | 'MIXED';
  energyScore: number;
  talkTimeSeconds: number;
};

export type PocTranscript = {
  index: number;
  speaker: string;
  raw_speaker?: string;
  result_id?: string;
  text: string;
  timestamp: string;
};

export type PocCategory =
  | '議事進行'
  | '報告'
  | '提案'
  | '相談'
  | '質問'
  | '回答'
  | '決定'
  | 'コメント'
  | '無関係な雑談';

export type PocClassifiedSegment = {
  index: number;
  speaker: string;
  text: string;
  category: PocCategory;
  alignment?: number;
};

export type PocJobDetail = {
  job_id: string;
  status: string;
  agenda_text: string;
  audio_filename: string;
  transcripts: PocTranscript[];
  classified_segments: PocClassifiedSegment[];
};

export type PocArchivedJob = {
  job_id: string;
  agenda_text: string;
  transcripts: PocTranscript[];
  completed_at: string;
  archive_name?: string;
};

export type PocHistoryItem = {
  job_id: string;
  completed_at: string;
  agenda_preview: string;
  transcript_count: number;
  archive_name?: string;
};

export type PocAnalysisResult = {
  job_id: string;
  agenda_text: string;
  summary: { meeting_id: string; summary: string };
  sentiment: Record<string, unknown>;
  transcript_sample: PocTranscript[];
  guidance: string[];
};

export type LiveTranscript = {
  meetingId: string;
  transcript: string;
  sentiment: string;
  timestamp: string;
  speaker?: string;
  isPartial?: boolean;
};
