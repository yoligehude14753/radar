// 实测结果页 — heyi-eval 对 radar 热点的 project/skill 自动评测结果
//
// 任务：让用户 5 秒内看清「哪些热点项目/Skill 实测通过、哪些失败及原因」。
// Must：outcome 徽章 / full_id / lane / 失败原因（失败行）
// Should：QAG 分 / demos / 时间 / lane+outcome 过滤
// Could（抽屉，按需）：agent 自评 + 步骤 + 阻塞 + 日志尾 + 媒体预览
import { useMemo, useState, type FC } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Table, Tag, Segmented, Space, Typography, Drawer, Descriptions, Empty,
  Spin, Image, Alert, Tooltip, Progress,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  getEvalResults, getEvalDetail, evalArtifactUrl,
  type EvalResult,
} from '../api/client'

const { Text, Paragraph, Title } = Typography

const OUTCOME_COLOR: Record<string, string> = {
  pass: 'success',
  partial: 'warning',
  fail: 'error',
  timeout: 'default',
  report_parse_error: 'default',
  oversize: 'default',
  sandbox_dead: 'default',
  budget_exceeded: 'default',
  needs_gpu: 'default',
  no_readme: 'default',
  skill_clone_attempt: 'error',
}

const OUTCOME_LABEL: Record<string, string> = {
  pass: '通过',
  partial: '部分通过',
  fail: '失败',
  timeout: '超时',
  report_parse_error: '报告解析失败',
  oversize: '超规格',
  sandbox_dead: '沙箱崩溃',
  budget_exceeded: '超预算',
}

function outcomeTag(r: EvalResult) {
  const key = (r.outcome || r.status || 'unknown').toLowerCase()
  const color = OUTCOME_COLOR[key] ?? 'default'
  const label = OUTCOME_LABEL[key] ?? key
  return <Tag color={color}>{label}</Tag>
}

const IMG_EXT = /\.(png|jpe?g|gif|webp|svg)$/i
const AUDIO_EXT = /\.(mp3|wav|ogg|m4a)$/i
const VIDEO_EXT = /\.(mp4|webm|mov)$/i

const ArtifactPreview: FC<{ lane: string; runId: string; rel: string }> = ({ lane, runId, rel }) => {
  const url = evalArtifactUrl(lane, runId, rel)
  if (IMG_EXT.test(rel)) {
    return <Image src={url} alt={rel} style={{ maxHeight: 180 }} />
  }
  if (AUDIO_EXT.test(rel)) {
    return <audio controls src={url} style={{ width: '100%' }} />
  }
  if (VIDEO_EXT.test(rel)) {
    return <video controls src={url} style={{ maxWidth: '100%', maxHeight: 240 }} />
  }
  return <a href={url} target="_blank" rel="noreferrer">{rel}</a>
}

const DetailDrawer: FC<{ runId: string | null; onClose: () => void }> = ({ runId, onClose }) => {
  const { data, isLoading } = useQuery({
    queryKey: ['eval-detail', runId],
    queryFn: () => getEvalDetail(runId as string),
    enabled: !!runId,
  })
  return (
    <Drawer
      title={runId ? `评测详情 · ${runId}` : ''}
      open={!!runId}
      onClose={onClose}
      width={680}
    >
      {isLoading && <Spin />}
      {data && (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="目标">
              {data.summary.target
                ? <a href={data.summary.target} target="_blank" rel="noreferrer">{data.summary.full_id}</a>
                : data.summary.full_id}
            </Descriptions.Item>
            <Descriptions.Item label="车道">{data.summary.lane}</Descriptions.Item>
            <Descriptions.Item label="结论">{outcomeTag(data.summary)}</Descriptions.Item>
            {data.summary.qag_score != null && (
              <Descriptions.Item label="QAG 热度分">{data.summary.qag_score.toFixed(2)}</Descriptions.Item>
            )}
            {data.summary.ended_at && (
              <Descriptions.Item label="完成时间">{data.summary.ended_at}</Descriptions.Item>
            )}
          </Descriptions>

          {data.summary.failure_reason_zh && (
            <Alert type="warning" showIcon message="失败/自评原因"
                   description={data.summary.failure_reason_zh} />
          )}

          {data.report?.self_assessment_zh && (
            <div>
              <Title level={5}>Agent 自评</Title>
              <Paragraph>{data.report.self_assessment_zh}</Paragraph>
            </div>
          )}

          {data.report?.verdict?.core_features_demonstrated?.length ? (
            <div>
              <Title level={5}>已验证能力</Title>
              <Space wrap>
                {data.report.verdict.core_features_demonstrated.map((f) => (
                  <Tag color="green" key={f}>{f}</Tag>
                ))}
              </Space>
            </div>
          ) : null}

          {data.report?.verdict?.blockers?.length ? (
            <div>
              <Title level={5}>阻塞项</Title>
              <Space direction="vertical" size={2}>
                {data.report.verdict.blockers.map((b, i) => (
                  <Text type="danger" key={i}>• {b}</Text>
                ))}
              </Space>
            </div>
          ) : null}

          {data.report?.steps?.length ? (
            <div>
              <Title level={5}>执行步骤</Title>
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                {data.report.steps.map((s, i) => (
                  <Text key={i}>
                    <Tag color={s.status === 'ok' ? 'success' : s.status === 'partial' ? 'warning' : s.status === 'fail' ? 'error' : 'default'}>
                      {s.status}
                    </Tag>
                    {s.name}{s.note ? ` — ${s.note}` : ''}
                  </Text>
                ))}
              </Space>
            </div>
          ) : null}

          {data.summary.artifacts.length > 0 && (
            <div>
              <Title level={5}>产物预览</Title>
              <Space wrap size="middle">
                {data.summary.artifacts.map((rel) => (
                  <ArtifactPreview key={rel} lane={data.summary.lane}
                                   runId={data.summary.run_id} rel={rel} />
                ))}
              </Space>
            </div>
          )}

          {data.agent_log_tail && (
            <div>
              <Title level={5}>Agent 日志（尾部）</Title>
              <pre style={{
                background: '#0d1117', padding: 12, borderRadius: 6,
                maxHeight: 280, overflow: 'auto', fontSize: 12,
              }}>{data.agent_log_tail}</pre>
            </div>
          )}
        </Space>
      )}
    </Drawer>
  )
}

const EvalResults: FC = () => {
  const [lane, setLane] = useState<string>('all')
  const [outcome, setOutcome] = useState<string>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['eval-results', lane, outcome],
    queryFn: () => getEvalResults({
      lane: lane === 'all' ? undefined : lane,
      outcome: outcome === 'all' ? undefined : outcome,
      limit: 500,
    }),
    refetchInterval: 60_000,
  })

  const rows = data ?? []

  const summary = useMemo(() => {
    const by = { pass: 0, partial: 0, fail: 0, other: 0 }
    for (const r of rows) {
      const k = (r.outcome || r.status || '').toLowerCase()
      if (k === 'pass') by.pass++
      else if (k === 'partial') by.partial++
      else if (k === 'fail') by.fail++
      else by.other++
    }
    return by
  }, [rows])

  const columns: ColumnsType<EvalResult> = [
    {
      title: '结论', dataIndex: 'outcome', width: 110,
      render: (_v, r) => outcomeTag(r),
      filters: [
        { text: '通过', value: 'pass' },
        { text: '部分通过', value: 'partial' },
        { text: '失败', value: 'fail' },
      ],
      onFilter: (val, r) => (r.outcome || r.status || '').toLowerCase() === val,
    },
    {
      title: '车道', dataIndex: 'lane', width: 90,
      render: (v: string) => <Tag>{v === 'project' ? '项目' : v === 'skill' ? 'Skill' : v}</Tag>,
    },
    {
      title: '目标', dataIndex: 'full_id',
      render: (v: string, r) => r.target
        ? <a href={r.target} target="_blank" rel="noreferrer">{v}</a>
        : <Text>{v}</Text>,
    },
    {
      title: 'QAG 热度', dataIndex: 'qag_score', width: 120,
      sorter: (a, b) => (a.qag_score ?? -1) - (b.qag_score ?? -1),
      render: (v: number | null) => v == null ? <Text type="secondary">—</Text>
        : <Tooltip title={v.toFixed(3)}><Progress percent={Math.round(v * 100)} size="small" showInfo={false} style={{ width: 80 }} /></Tooltip>,
    },
    {
      title: 'demos', dataIndex: 'demos_passed', width: 80,
      sorter: (a, b) => (a.demos_passed ?? -1) - (b.demos_passed ?? -1),
      render: (v: number | null) => v == null ? '—' : v,
    },
    {
      title: '失败原因', dataIndex: 'failure_reason_zh', ellipsis: true,
      render: (v: string | null) => v ? <Text type="secondary">{v}</Text> : '',
    },
    {
      title: '完成时间', dataIndex: 'ended_at', width: 170,
      sorter: (a, b) => (a.ended_at ?? '').localeCompare(b.ended_at ?? ''),
      defaultSortOrder: 'descend',
      render: (v: string | null) => v ? v.replace('T', ' ').slice(0, 19) : '—',
    },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <Title level={3} style={{ margin: 0 }}>实测结果</Title>
        <Space size="large">
          <Text type="secondary">
            <Tag color="success">{summary.pass} 通过</Tag>
            <Tag color="warning">{summary.partial} 部分</Tag>
            <Tag color="error">{summary.fail} 失败</Tag>
            {summary.other > 0 && <Tag>{summary.other} 其他</Tag>}
          </Text>
        </Space>
      </div>

      <Space wrap>
        <Segmented
          value={lane}
          onChange={(v) => setLane(v as string)}
          options={[
            { label: '全部车道', value: 'all' },
            { label: '项目', value: 'project' },
            { label: 'Skill', value: 'skill' },
            { label: '模型', value: 'model' },
          ]}
        />
        <Segmented
          value={outcome}
          onChange={(v) => setOutcome(v as string)}
          options={[
            { label: '全部结论', value: 'all' },
            { label: '通过', value: 'pass' },
            { label: '部分', value: 'partial' },
            { label: '失败', value: 'fail' },
          ]}
        />
      </Space>

      <Table<EvalResult>
        rowKey="run_id"
        loading={isLoading}
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: true }}
        onRow={(r) => ({ onClick: () => setSelected(r.run_id), style: { cursor: 'pointer' } })}
        locale={{ emptyText: <Empty description="暂无实测结果（等待 heyi-eval 跑批）" /> }}
      />

      <DetailDrawer runId={selected} onClose={() => setSelected(null)} />
    </Space>
  )
}

export default EvalResults
