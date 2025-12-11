import type { AnalyticsSample } from '../types';

type Props = {
  samples: AnalyticsSample[];
};

export function MetricsPanel({ samples }: Props) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Live sentiment</h2>
        <span>last {samples.length} samples</span>
      </div>
      <table className="metrics-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Sentiment</th>
            <th>Energy</th>
            <th>Talk time (s)</th>
          </tr>
        </thead>
        <tbody>
          {samples.map((sample) => (
            <tr key={sample.timestamp}>
              <td>{sample.timestamp}</td>
              <td>{sample.sentiment}</td>
              <td>{sample.energyScore.toFixed(2)}</td>
              <td>{sample.talkTimeSeconds}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
