const API_BASE = '/api';

export interface MeetingSession {
  meeting_id: string;
  title: string;
  status: string;
  session_id: string;
  token: string;
  api_key: string;
}

export async function joinMeeting(meetingId: string): Promise<MeetingSession> {
  console.log('🌐 Joining meeting:', meetingId);
  
  const response = await fetch(`${API_BASE}/session/meetings/${meetingId}/join`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to join meeting: ${errorText}`);
  }

  const data = await response.json();
  console.log('✅ Meeting joined:', data);
  
  return data;
}