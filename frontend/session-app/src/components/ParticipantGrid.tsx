import type { Participant } from '../types';

type Props = {
  participants: Participant[];
};

export function ParticipantGrid({ participants }: Props) {
  return (
    <section className="panel video-stage">
      <div className="panel-header">
        <h2>参加者ビデオ</h2>
        <span>{participants.length} 名</span>
      </div>
      <div className="video-grid">
        {participants.map((participant) => (
          <div key={participant.id} className={`video-tile ${participant.isSpeaking ? 'speaking' : ''}`}>
            <div className="video-feed" aria-label={`${participant.name} の映像 placeholder`} />
            <div className="video-meta">
              <div>
                <p className="name">{participant.name}</p>
                <p className="role">{participant.role}</p>
              </div>
              <span className="badge">{participant.isSpeaking ? 'Speaking' : 'Listening'}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
