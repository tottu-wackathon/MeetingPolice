import { useState } from 'react';

interface VonageDebugPanelProps {
  apiKey?: string;
  sessionId?: string;
  token?: string;
  onClose: () => void;
}

export function VonageDebugPanel({ apiKey, sessionId, token, onClose }: VonageDebugPanelProps) {
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  const runConnectionTest = async () => {
    setTesting(true);
    setTestResult(null);

    try {
      // Test backend connection
      const response = await fetch('/api/admin/vonage/test-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (response.ok) {
        const result = await response.json();
        setTestResult(`✅ バックエンドテスト成功: ${JSON.stringify(result, null, 2)}`);
      } else {
        const error = await response.text();
        setTestResult(`❌ バックエンドテスト失敗: ${error}`);
      }
    } catch (error) {
      setTestResult(`❌ バックエンド接続エラー: ${error}`);
    } finally {
      setTesting(false);
    }
  };

  const validateCredentials = () => {
    const issues: string[] = [];
    
    if (!apiKey) {
      issues.push('APIキーが未設定');
    } else if (apiKey === 'mock_api_key') {
      issues.push('APIキーがモック値');
    } else if (apiKey.length < 8) {
      issues.push('APIキーが短すぎる');
    }
    
    if (!sessionId) {
      issues.push('セッションIDが未設定');
    } else if (sessionId.includes('mock')) {
      issues.push('セッションIDがモック値');
    } else if (!sessionId.startsWith('1_MX') && !sessionId.startsWith('2_MX')) {
      issues.push('セッションIDの形式が無効');
    }
    
    if (!token) {
      issues.push('トークンが未設定');
    } else if (token.startsWith('T1==')) {
      issues.push('トークンがモック値');
    } else if (token.length < 50) {
      issues.push('トークンが短すぎる');
    }
    
    return issues;
  };

  const issues = validateCredentials();

  return (
    <div className="vonage-debug-panel">
      <div className="debug-header">
        <h3>🔧 Vonage接続デバッグ</h3>
        <button onClick={onClose} className="close-btn">×</button>
      </div>
      
      <div className="debug-content">
        <div className="credentials-check">
          <h4>認証情報チェック</h4>
          <div className="credential-item">
            <strong>APIキー:</strong> 
            <span className={apiKey ? 'valid' : 'invalid'}>
              {apiKey ? `${apiKey.substring(0, 8)}...` : '未設定'}
            </span>
          </div>
          <div className="credential-item">
            <strong>セッションID:</strong> 
            <span className={sessionId ? 'valid' : 'invalid'}>
              {sessionId ? `${sessionId.substring(0, 20)}...` : '未設定'}
            </span>
          </div>
          <div className="credential-item">
            <strong>トークン:</strong> 
            <span className={token ? 'valid' : 'invalid'}>
              {token ? `${token.substring(0, 20)}... (長さ: ${token.length})` : '未設定'}
            </span>
          </div>
          
          {issues.length > 0 && (
            <div className="issues-list">
              <h5>⚠️ 検出された問題:</h5>
              <ul>
                {issues.map((issue, index) => (
                  <li key={index}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        
        <div className="backend-test">
          <h4>バックエンドテスト</h4>
          <button 
            onClick={runConnectionTest} 
            disabled={testing}
            className="test-btn"
          >
            {testing ? '🔄 テスト中...' : '🧪 接続テスト実行'}
          </button>
          
          {testResult && (
            <div className="test-result">
              <pre>{testResult}</pre>
            </div>
          )}
        </div>
        
        <div className="troubleshooting">
          <h4>トラブルシューティング</h4>
          <div className="troubleshooting-steps">
            <div className="step">
              <strong>1. 環境変数確認</strong>
              <p>バックエンドの.envファイルで以下を確認:</p>
              <ul>
                <li>VONAGE_API_KEY</li>
                <li>VONAGE_APPLICATION_ID</li>
                <li>VONAGE_PRIVATE_KEY_PATH</li>
              </ul>
            </div>
            <div className="step">
              <strong>2. 秘密鍵ファイル</strong>
              <p>secrets/vonage_private.keyが存在し、正しい内容か確認</p>
            </div>
            <div className="step">
              <strong>3. Vonage Dashboard</strong>
              <p>Vonage Video API Dashboardで認証情報を確認</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}