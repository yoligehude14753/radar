import { useQuery } from '@tanstack/react-query'
import { Card, Button, Table, Tag, Empty, Spin, Space } from 'antd'
import { EyeOutlined, DownloadOutlined } from '@ant-design/icons'
import { getReports, downloadReport, type ReportInfo } from '../api/client'

export default function ReportsCommunities() {
  const { data: reports = [], isLoading } = useQuery({
    queryKey: ['reports', 'communities'],
    queryFn: () => getReports('communities'),
    refetchInterval: 60_000,
  })

  const columns = [
    {
      title: '日期',
      dataIndex: 'period_key',
      key: 'period_key',
      render: (v: string) => <span style={{ color: '#58a6ff' }}>{v}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => <Tag color={v === 'ok' ? 'success' : 'error'}>{v}</Tag>,
    },
    {
      title: '来源数',
      dataIndex: 'item_count',
      key: 'item_count',
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '生成时间',
      dataIndex: 'generated_at',
      key: 'generated_at',
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: ReportInfo) => (
        <Space>
          <Button
            size="small"
            icon={<EyeOutlined />}
            href={`/outputs/${record.file_path?.split('/').pop()}`}
            target="_blank"
          >
            查看
          </Button>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            href={downloadReport(record.id)}
          >
            下载
          </Button>
        </Space>
      ),
    },
  ]

  const latest = reports[0]

  return (
    <div>
      <h2 style={{ color: '#e6edf3', marginBottom: 20, fontSize: 18 }}>
        🌐 AI 社群地图报告
      </h2>

      {latest && (
        <Card
          style={{ background: '#161b22', border: '1px solid #30363d', marginBottom: 16 }}
          bodyStyle={{ padding: 16 }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#e6edf3', marginBottom: 4 }}>
                最新报告：{latest.period_key}
              </div>
              <div style={{ color: '#8b949e', fontSize: 12 }}>
                {latest.item_count} 个社群 · {new Date(latest.generated_at).toLocaleString('zh-CN')} 生成
              </div>
            </div>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              href={`/outputs/${latest.file_path?.split('/').pop()}`}
              target="_blank"
            >
              查看最新报告
            </Button>
          </div>
        </Card>
      )}

      <Card
        title={<span style={{ color: '#e6edf3' }}>历史报告</span>}
        bordered={false}
        style={{ background: '#161b22', border: '1px solid #30363d' }}
      >
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : reports.length === 0 ? (
          <Empty
            description={<span style={{ color: '#8b949e' }}>
              暂无报告。系统每天自动生成，或在抓取数据后由调度器触发。
            </span>}
          />
        ) : (
          <Table
            dataSource={reports}
            columns={columns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 20 }}
          />
        )}
      </Card>
    </div>
  )
}
