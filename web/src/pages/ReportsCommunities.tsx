import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Drawer, Table, Tag, Space, Spin, Alert } from 'antd'
import { HistoryOutlined, DownloadOutlined, FullscreenOutlined } from '@ant-design/icons'
import { getReports, downloadReport, type ReportInfo } from '../api/client'

export default function ReportsCommunities() {
  const [drawerOpen, setDrawerOpen] = useState(false)

  const { data: reports = [], isLoading } = useQuery({
    queryKey: ['reports', 'communities'],
    queryFn: () => getReports('communities'),
    refetchInterval: 60_000,
  })

  const hasReport = reports.length > 0
  const iframeUrl = '/outputs/communities_latest.html'

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
    },
    {
      title: '生成时间',
      dataIndex: 'generated_at',
      key: 'generated_at',
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '下载',
      key: 'dl',
      render: (_: unknown, r: ReportInfo) => (
        <Button size="small" icon={<DownloadOutlined />} href={downloadReport(r.id)}>
          下载
        </Button>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 80px)', gap: 0 }}>
      {/* 顶栏 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingBottom: 12,
        flexShrink: 0,
      }}>
        <div>
          <span style={{ color: '#e6edf3', fontWeight: 600, fontSize: 16 }}>
            🌐 AI 社群地图
          </span>
          {hasReport && (
            <span style={{ color: '#8b949e', fontSize: 12, marginLeft: 12 }}>
              最新：{reports[0].period_key} · {reports[0].item_count} 个社群
            </span>
          )}
        </div>
        <Space>
          <Button
            icon={<FullscreenOutlined />}
            size="small"
            href={iframeUrl}
            target="_blank"
            disabled={!hasReport}
          >
            新标签页打开
          </Button>
          <Button
            icon={<HistoryOutlined />}
            size="small"
            onClick={() => setDrawerOpen(true)}
            disabled={!hasReport}
          >
            历史记录 {reports.length > 0 && `(${reports.length})`}
          </Button>
        </Space>
      </div>

      {/* 报告展示区 */}
      <div style={{
        flex: 1,
        border: '1px solid #30363d',
        borderRadius: 8,
        overflow: 'hidden',
        background: '#161b22',
        minHeight: 0,
      }}>
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
            <Spin size="large" />
          </div>
        ) : !hasReport ? (
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100%', gap: 16 }}>
            <div style={{ fontSize: 48 }}>🌐</div>
            <div style={{ color: '#8b949e', textAlign: 'center' }}>
              <div style={{ fontSize: 15, marginBottom: 8 }}>暂无报告</div>
              <div style={{ fontSize: 13 }}>
                系统每天自动生成。可先完成 GitHub + Reddit 抓取后触发。
              </div>
            </div>
            <Alert
              type="info"
              showIcon
              message={<code style={{ fontSize: 12 }}>radar crawl github && radar crawl reddit</code>}
              style={{ background: 'transparent', border: '1px solid #30363d' }}
            />
          </div>
        ) : (
          <iframe
            src={iframeUrl}
            style={{ width: '100%', height: '100%', border: 'none' }}
            title="AI 社群地图"
          />
        )}
      </div>

      {/* 历史记录抽屉 */}
      <Drawer
        title="历史报告"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={580}
        styles={{ body: { padding: 16 } }}
      >
        <Table
          dataSource={reports}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 20 }}
        />
      </Drawer>
    </div>
  )
}
