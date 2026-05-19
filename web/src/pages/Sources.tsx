import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, Table, Tag, Button, message, Tooltip, Empty, Spin } from 'antd'
import { SyncOutlined, CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { getSources, triggerCrawl, type SourceInfo } from '../api/client'

export default function Sources() {
  const qc = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['sources'],
    queryFn: getSources,
    refetchInterval: 15_000,
  })

  const crawlMutation = useMutation({
    mutationFn: (source: string) => triggerCrawl(source),
    onSuccess: (_, source) => {
      messageApi.success(`${source.toUpperCase()} 抓取任务已触发`)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['sources'] }), 3000)
    },
    onError: (err: Error) => messageApi.error(`触发失败: ${err.message}`),
  })

  const statusIcon = (status: string | null) => {
    switch (status) {
      case 'done': return <CheckCircleOutlined style={{ color: '#3fb950' }} />
      case 'failed': return <CloseCircleOutlined style={{ color: '#f85149' }} />
      case 'running': return <SyncOutlined spin style={{ color: '#58a6ff' }} />
      default: return <ClockCircleOutlined style={{ color: '#8b949e' }} />
    }
  }

  const columns = [
    {
      title: '数据源',
      dataIndex: 'source',
      key: 'source',
      render: (v: string) => (
        <span style={{ fontWeight: 600, color: '#e6edf3', fontSize: 15 }}>
          {v.toUpperCase()}
        </span>
      ),
    },
    {
      title: '总条目数',
      dataIndex: 'total_items',
      key: 'total_items',
      render: (v: number) => <span style={{ color: '#58a6ff' }}>{v.toLocaleString()}</span>,
    },
    {
      title: '最近运行',
      key: 'last_run',
      render: (_: unknown, row: SourceInfo) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {statusIcon(row.last_run_status)}
          <Tag color={
            row.last_run_status === 'done' ? 'success' :
            row.last_run_status === 'failed' ? 'error' :
            row.last_run_status === 'running' ? 'processing' : 'default'
          }>
            {row.last_run_status ?? '未运行'}
          </Tag>
        </div>
      ),
    },
    {
      title: '本次抓取',
      key: 'last_run_stats',
      render: (_: unknown, row: SourceInfo) => row.last_run_status ? (
        <span style={{ color: '#8b949e', fontSize: 12 }}>
          抓取 {row.last_run_items_in} 条，新增 {row.last_run_items_new} 条
        </span>
      ) : '—',
    },
    {
      title: '最近运行时间',
      dataIndex: 'last_run_at',
      key: 'last_run_at',
      render: (v: string | null) => v
        ? <span style={{ color: '#8b949e', fontSize: 12 }}>{new Date(v).toLocaleString('zh-CN')}</span>
        : '—',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, row: SourceInfo) => (
        <Tooltip title={`立即抓取 ${row.source.toUpperCase()}`}>
          <Button
            size="small"
            icon={<SyncOutlined spin={crawlMutation.isPending && crawlMutation.variables === row.source} />}
            onClick={() => crawlMutation.mutate(row.source)}
            loading={crawlMutation.isPending && crawlMutation.variables === row.source}
          >
            立即抓取
          </Button>
        </Tooltip>
      ),
    },
  ]

  return (
    <div>
      {contextHolder}
      <h2 style={{ color: '#e6edf3', marginBottom: 20, fontSize: 18 }}>
        🗄️ 数据源管理
      </h2>

      <Card
        title={<span style={{ color: '#e6edf3' }}>数据源状态</span>}
        bordered={false}
        style={{ background: '#161b22', border: '1px solid #30363d' }}
        extra={
          <Button
            icon={<SyncOutlined />}
            size="small"
            onClick={() => qc.invalidateQueries({ queryKey: ['sources'] })}
          >
            刷新
          </Button>
        }
      >
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : sources.length === 0 ? (
          <Empty
            description={<span style={{ color: '#8b949e' }}>
              暂无数据源记录。请先配置 Token 并运行 <code>radar crawl github</code>
            </span>}
          />
        ) : (
          <Table
            dataSource={sources}
            columns={columns}
            rowKey="source"
            pagination={false}
          />
        )}
      </Card>

      <div style={{ marginTop: 16, color: '#8b949e', fontSize: 12 }}>
        💡 系统每 6 小时自动抓取一次，也可点击「立即抓取」手动触发
      </div>
    </div>
  )
}
