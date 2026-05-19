import { useQuery } from '@tanstack/react-query'
import { Card, Row, Col, Statistic, Tag, Alert, Button } from 'antd'
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { getHealth, getSources, getIncidents, getReports } from '../api/client'

export default function Dashboard() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
  })
  const { data: sources = [] } = useQuery({
    queryKey: ['sources'],
    queryFn: getSources,
    refetchInterval: 60_000,
  })
  const { data: incidents = [] } = useQuery({
    queryKey: ['incidents', 'open'],
    queryFn: () => getIncidents('open'),
    refetchInterval: 30_000,
  })
  const { data: reports = [] } = useQuery({
    queryKey: ['reports'],
    queryFn: () => getReports(),
    refetchInterval: 300_000,
  })

  const totalItems = sources.reduce((s, src) => s + src.total_items, 0)
  const openIncidents = incidents.filter(i => i.status === 'open')
  const criticalCount = openIncidents.filter(i => i.severity === 'critical').length

  return (
    <div>
      <h2 style={{ color: '#e6edf3', marginBottom: 20, fontSize: 18 }}>
        🛰️ Radar 仪表盘
      </h2>

      {/* 系统状态 */}
      {criticalCount > 0 && (
        <Alert
          message={`🚨 有 ${criticalCount} 个严重告警需要处理`}
          type="error"
          showIcon
          action={<Button size="small" href="/incidents">查看告警</Button>}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 健康状态 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} md={6}>
          <Card bordered={false} style={{ background: '#161b22', border: '1px solid #30363d' }}>
            <Statistic
              title={<span style={{ color: '#8b949e' }}>API 状态</span>}
              value={health?.status === 'ok' ? '运行中' : (health?.status ?? '—')}
              valueStyle={{ color: health?.status === 'ok' ? '#3fb950' : '#f85149' }}
              prefix={health?.status === 'ok' ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card bordered={false} style={{ background: '#161b22', border: '1px solid #30363d' }}>
            <Statistic
              title={<span style={{ color: '#8b949e' }}>数据条目</span>}
              value={totalItems.toLocaleString()}
              valueStyle={{ color: '#58a6ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card bordered={false} style={{ background: '#161b22', border: '1px solid #30363d' }}>
            <Statistic
              title={<span style={{ color: '#8b949e' }}>活跃告警</span>}
              value={openIncidents.length}
              valueStyle={{ color: openIncidents.length > 0 ? '#f0883e' : '#3fb950' }}
              prefix={openIncidents.length > 0 ? <ExclamationCircleOutlined /> : <CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card bordered={false} style={{ background: '#161b22', border: '1px solid #30363d' }}>
            <Statistic
              title={<span style={{ color: '#8b949e' }}>报告数量</span>}
              value={reports.length}
              valueStyle={{ color: '#58a6ff' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 数据源状态 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card
            title={<span style={{ color: '#e6edf3' }}>数据源状态</span>}
            bordered={false}
            style={{ background: '#161b22', border: '1px solid #30363d' }}
          >
            {sources.length === 0 ? (
              <p style={{ color: '#8b949e', textAlign: 'center', padding: '20px 0' }}>
                暂无数据，请配置数据源
              </p>
            ) : (
              sources.map(src => (
                <div key={src.source} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 0',
                  borderBottom: '1px solid #21262d',
                }}>
                  <div>
                    <span style={{ fontWeight: 600, color: '#e6edf3', marginRight: 8 }}>
                      {src.source.toUpperCase()}
                    </span>
                    <Tag color="blue" style={{ fontSize: 11 }}>{src.total_items.toLocaleString()} 条</Tag>
                  </div>
                  <Tag color={
                    src.last_run_status === 'done' ? 'success' :
                    src.last_run_status === 'failed' ? 'error' :
                    src.last_run_status === 'running' ? 'processing' : 'default'
                  }>
                    {src.last_run_status ?? '未运行'}
                  </Tag>
                </div>
              ))
            )}
          </Card>
        </Col>

        <Col xs={24} md={12}>
          <Card
            title={<span style={{ color: '#e6edf3' }}>近期告警</span>}
            bordered={false}
            style={{ background: '#161b22', border: '1px solid #30363d' }}
          >
            {openIncidents.length === 0 ? (
              <p style={{ color: '#3fb950', textAlign: 'center', padding: '20px 0' }}>
                ✅ 系统运行正常，无活跃告警
              </p>
            ) : (
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                {openIncidents.slice(0, 5).map(inc => (
                  <div key={inc.id} style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 8,
                    padding: '6px 0',
                    borderBottom: '1px solid #21262d',
                  }}>
                    <span style={{ fontSize: 14, marginTop: 2 }}>
                      {inc.severity === 'critical' ? '🔴' : '🟡'}
                    </span>
                    <div>
                      <div style={{ fontSize: 13, color: '#e6edf3' }}>{inc.title}</div>
                      <div style={{ fontSize: 11, color: '#8b949e' }}>
                        {new Date(inc.detected_at).toLocaleString('zh-CN')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* LLM Profile */}
      {health && (
        <div style={{ marginTop: 16, color: '#8b949e', fontSize: 12 }}>
          LLM: <span style={{ color: '#58a6ff' }}>{health.llm_profile}</span>
          &nbsp;·&nbsp; DB: <span style={{ color: '#58a6ff' }}>{health.db_type}</span>
          &nbsp;·&nbsp; v<span style={{ color: '#58a6ff' }}>{health.version}</span>
        </div>
      )}
    </div>
  )
}
