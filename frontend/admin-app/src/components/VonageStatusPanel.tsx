import { useEffect, useState } from 'react';

interface VonageStatus {
  status: 'connected' | 'mock' | 'disconnected' | 'error';
  auth_method: string;
  api_key: string;
  application_id: string;
  has_private_key: boolean;
  test_session_id?: string;
  error?: string;
}

export function VonageStatusPanel() {
  const [status, setStatus] = useState<VonageStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/admin/vonage/status');
      const data = await response.json();
      setStatus(data);
    } catch (error) {
      console.error('Failed to fetch Vonage status:', error);
      setStatus({
        status: 'error',
        auth_method: 'unknown',
        api_key: 'Error',
        application_id: 'Error',
        has_private_key: false,
        error: 'Failed to fetch status'
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  if (loading) {
    return (
      <section className="panel">
        <h2>Vonage Video API 接続状況</h2>
        <p>読み込み中...</p>
      </section>
    );
  }

  if (!status) {
    return (
      <section className="panel">
        <h2>Vonage Video API 接続状況</h2>
        <p>ステータスを取得できませんでした</p>
      </section>
    );
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'connected': return '#4caf50';
      case 'mock': return '#ff9800';
      case 'disconnected': return '#f44336';
      case 'error': return '#f44336';
      default: return '#9e9e9e';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'connected': return '✅ 接続済み';
      case 'mock': return '🔧 モックモード';
      case 'disconnected': return '❌ 未接続';
      case 'error': return '⚠️ エラー';
      default: return '❓ 不明';
    }
  };

  const getAuthMethodText = (method: string) => {
    switch (method) {
      case 'jwt': return 'JWT認証 (推奨)';
      case 'opentok': return 'OpenTok認証 (レガシー)';
      case 'mock': return 'モック (開発用)';
      default: return method;
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Vonage Video API 接続状況</h2>
        <button 
          type="button" 
          onClick={fetchStatus}
          className="ghost"
          style={{ fontSize: '0.9em' }}
        >
          🔄 更新
        </button>
      </div>
      
      <div style={{ 
        padding: '16px', 
        backgroundColor: 'rgba(255, 255, 255, 0.05)', 
        borderRadius: '8px',
        border: `2px solid ${getStatusColor(status.status)}`
      }}>
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: '12px'
        }}>
          <span style={{ 
            fontSize: '1.1em', 
            fontWeight: 'bold',
            color: getStatusColor(status.status)
          }}>
            {getStatusText(status.status)}
          </span>
          <span style={{ 
            fontSize: '0.9em', 
            color: '#888',
            backgroundColor: 'rgba(0,0,0,0.3)',
            padding: '4px 8px',
            borderRadius: '4px'
          }}>
            {getAuthMethodText(status.auth_method)}
          </span>
        </div>

        <div style={{ fontSize: '0.9em', color: '#ccc' }}>
          <div style={{ marginBottom: '4px' }}>
            <strong>APIキー:</strong> {status.api_key}
          </div>
          <div style={{ marginBottom: '4px' }}>
            <strong>アプリケーションID:</strong> {status.application_id}
          </div>
          <div style={{ marginBottom: '4px' }}>
            <strong>秘密鍵:</strong> {status.has_private_key ? '✅ 設定済み' : '❌ 未設定'}
          </div>
          {status.test_session_id && (
            <div style={{ marginBottom: '4px' }}>
              <strong>テストセッション:</strong> {status.test_session_id}
            </div>
          )}
          {status.error && (
            <div style={{ color: '#f44336', marginTop: '8px' }}>
              <strong>エラー:</strong> {status.error}
            </div>
          )}
        </div>

        {status.status === 'mock' && (
          <div style={{ 
            marginTop: '12px', 
            padding: '8px', 
            backgroundColor: 'rgba(255, 152, 0, 0.1)',
            borderRadius: '4px',
            fontSize: '0.85em',
            color: '#ffb74d'
          }}>
            💡 モックモードで動作中です。実際のビデオ通話は利用できませんが、文字起こし機能は正常に動作します。
          </div>
        )}

        {status.status === 'connected' && (
          <div style={{ 
            marginTop: '12px', 
            padding: '8px', 
            backgroundColor: 'rgba(76, 175, 80, 0.1)',
            borderRadius: '4px',
            fontSize: '0.85em',
            color: '#81c784'
          }}>
            🎉 Vonage Video APIに正常に接続されています。ビデオ通話機能が利用できます。
          </div>
        )}

        {/* セッション作成テストボタン */}
        <div style={{ marginTop: '12px' }}>
          <button 
            onClick={async () => {
              try {
                const response = await fetch('/api/admin/vonage/test-session', { method: 'POST' });
                const result = await response.json();
                if (response.ok) {
                  alert(`セッション作成テスト成功！\nセッションID: ${result.session_id.substring(0, 20)}...\nタイプ: ${result.is_real ? 'リアル' : 'モック'}`);
                } else {
                  alert(`セッション作成テスト失敗: ${result.error}`);
                }
              } catch (error) {
                alert(`テストエラー: ${error}`);
              }
            }}
            style={{
              padding: '8px 12px',
              fontSize: '0.85em',
              backgroundColor: '#007acc',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            🧪 セッション作成テスト
          </button>
        </div>
      </div>
    </section>
  );
}