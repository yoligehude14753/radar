import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, Table, Tag, Button, Space, Popconfirm, message, Empty, Spin, Select, Tooltip } from 'antd'
import { CheckOutlined, ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import { getIncidents, dismissIncident, executeAction, type IncidentInfo } from '../api/client'
import { useState } from 'react'

const { Option } = Select

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'error',
  warning: 'warning',
  info: 'default',
}

const SEVERITY_LABEL: Record<string, string> = {
  critical: '🔴 严重',
  warning: '🟡 警告',
  info: '⚪ 提示',
}

export default function Incidents() {
  const qc = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [statusFilter, setStatusFilter] = useState<string>('open')

  const { data: incidents = [], isLoading, refetch } = useQuery({
    queryKey: ['incidents', statusFilter],
    queryFn: () => getIncidents(statusFilter || undefined),
    refetchInterval: 15_000,
  })

  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissIncident(id),
    onSuccess: () => {
      messageApi.success('告警已忽略')
      qc.invalidateQueries({ queryKey: ['incidents'] })
    },
    onError: (err: Error) => messageApi.error(`操作失败: ${err.message}`),
  })

  const actionMutation = useMutation({
    mutationFn: ({ id, key }: { id: string; key: string }) => executeAction(id, key),
    onSuccess: (data, { key }) => {
      if (data.result?.status === 'ok') {
        messageApi.success(`动作「${key}」执行成功`)
      } else {
        messageApi.warning(`动作「${key}」已触发，请确认效果`)
      }
      qc.invalidateQueries({ queryKey: ['incidents'] })
    },
    onError: (err: Error) => messageApi.error(`动作执行失败: ${err.message}`),
  })

  const openCount = incidents.filter(i => i.status === 'open').length
  const criticalCount = incidents.filter(i => i.severity === 'critical' && i.status === 'open').length

  const columns = [
    {
      title: '严重程度',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (v: string) => (
        <Tag color={SEVERITY_COLOR[v] ?? 'default'} style={{ minWidth: 70, textAlign: 'center' }}>
          {SEVERITY_LABEL[v] ?? v}
        </Tag>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, record: IncidentInfo) => (
        <div>
          <div style={{ color: '#e6edf3', fontWeight: 500 }}>{title}</div>
          {record.detail && (
            <div style={{ color: '#8b949e', fontSize: 12, marginTop: 2 }}>
              {record.detail.slice(0, 100)}{record.detail.length > 100 ? '…' : ''}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '影响资源',
      dataIndex: 'affected_resource',
      key: 'affected_resource',
      render: (v: string | null) => v ? <Tag>{v.toUpperCase()}</Tag> : '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => (
        <Tag color={v === 'resolved' || v === 'dismissed' ? 'success' : v === 'open' ? 'error' : 'processing'}>
          {v === 'open' ? '待处理' : v === 'resolving' ? '处理中' : v === 'resolved' ? '已解决' : '已忽略'}
        </Tag>
      ),
    },
    {
      title: '发现时间',
      dataIndex: 'detected_at',
      key: 'detected_at',
      render: (v: string) => (
        <span style={{ color: '#8b949e', fontSize: 12 }}>
          {new Date(v).toLocaleString('zh-CN')}
        </span>
      ),
    },
    {
      title: '一键修复',
      key: 'actions',
      render: (_: unknown, record: IncidentInfo) => (
        <Space wrap>
          {record.actions.map(action => (
            <Tooltip key={action.id} title={action.label}>
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={() => actionMutation.mutate({ id: record.id, key: action.action_key })}
                loading={actionMutation.isPending && actionMutation.variables?.id === record.id}
                disabled={record.status !== 'open'}
              >
                {action.label.slice(0, 8)}{action.label.length > 8 ? '…' : ''}
              </Button>
            </Tooltip>
          ))}
          {record.status === 'open' && (
            <Popconfirm
              title="确认忽略此告警？"
              onConfirm={() => dismissMutation.mutate(record.id)}
              okText="忽略"
              cancelText="取消"
            >
              <Button size="small" icon={<CheckOutlined />}>
                忽略
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      {contextHolder}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ color: '#e6edf3', marginBottom: 4, fontSize: 18 }}>
            🚨 告警中心
          </h2>
          {openCount > 0 && (
            <div style={{ color: '#8b949e', fontSize: 13 }}>
              {criticalCount > 0 && (
                <span style={{ color: '#f85149' }}>{criticalCount} 个严重告警，</span>
              )}
              共 {openCount} 个待处理
            </div>
          )}
        </div>
        <Space>
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            style={{ width: 120 }}
            size="small"
          >
            <Option value="open">待处理</Option>
            <Option value="resolved">已解决</Option>
            <Option value="dismissed">已忽略</Option>
            <Option value="">全部</Option>
          </Select>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => refetch()}
          >
            刷新
          </Button>
        </Space>
      </div>

      <Card
        bordered={false}
        style={{ background: '#161b22', border: '1px solid #30363d' }}
      >
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : incidents.length === 0 ? (
          <Empty
            description={
              <span style={{ color: '#8b949e' }}>
                {statusFilter === 'open' ? '✅ 当前没有待处理的告警，系统运行正常' : '暂无告警记录'}
              </span>
            }
          />
        ) : (
          <Table
            dataSource={incidents}
            columns={columns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 20 }}
            rowClassName={(record) => record.severity === 'critical' && record.status === 'open' ? 'critical-row' : ''}
          />
        )}
      </Card>
    </div>
  )
}
