import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Card, Tabs, Switch, Select, Button, Alert, Form, Input, Radio,
  Space, Divider, Tag, Tooltip, Spin,
} from 'antd'
import {
  SaveOutlined, ExperimentOutlined, ReloadOutlined, KeyOutlined,
  GithubOutlined, InfoCircleOutlined, ThunderboltOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { getSettingsOverview, updateSourceSettings, updateLLMSettings, testLLMSettings } from '../api/client'

const INTERVAL_OPTIONS = [
  { value: '15min', label: '15 分钟' },
  { value: '30min', label: '30 分钟' },
  { value: '1h', label: '1 小时' },
  { value: '3h', label: '3 小时' },
  { value: '6h', label: '6 小时（默认）' },
  { value: '12h', label: '12 小时' },
  { value: 'daily', label: '每天' },
  { value: 'weekly', label: '每周' },
]

const PROFILE_DESCS: Record<string, { label: string; tag: string; tagColor: string; desc: string }> = {
  yunwu: {
    label: '云雾 API',
    tag: '兼容 OpenAI',
    tagColor: 'blue',
    desc: '国内可访问的 OpenAI 兼容代理，支持 GPT-4o / Claude 等模型，需配置 API Key',
  },
  heyi: {
    label: 'Heyi 本地算力',
    tag: '2× RTX 5090',
    tagColor: 'green',
    desc: '专用 GPU 服务器（Qwen3-235B），私有部署，零成本推理，延迟低',
  },
  ollama: {
    label: 'Ollama 本地',
    tag: '完全离线',
    tagColor: 'default',
    desc: '本地运行的开源模型（llama3/qwen/mistral），无需 API Key，需先安装 Ollama',
  },
  openai: {
    label: 'OpenAI 官方',
    tag: '需梯子',
    tagColor: 'orange',
    desc: '官方 API，需 VPN / 代理访问，按量计费',
  },
}

// ── 单个数据源卡片 ────────────────────────────────────────────────────────────

interface SourceCardProps {
  icon: React.ReactNode
  name: string
  config: import('../api/client').SourceConfig
  envEnabled: boolean
  interval: string
  onToggle: (v: boolean) => void
  onIntervalChange: (v: string) => void
  tokenHint?: React.ReactNode  // 已配置 token 时的提示
}

function SourceCard({
  icon, name, config, envEnabled, interval,
  onToggle, onIntervalChange, tokenHint,
}: SourceCardProps) {
  const prereqMet = config.prerequisites_met

  // 真实状态：只有前提条件满足 + env 开关打开 才算"运行中"
  const reallyEnabled = prereqMet && envEnabled

  let statusTag: React.ReactNode
  if (!prereqMet) {
    statusTag = <Tag color="error" icon={<ExclamationCircleOutlined />}>需要配置</Tag>
  } else if (reallyEnabled) {
    statusTag = <Tag color="success" icon={<CheckCircleOutlined />}>运行中</Tag>
  } else {
    statusTag = <Tag color="default">已停用</Tag>
  }

  return (
    <Card
      bordered={false}
      style={{
        background: '#0d1117',
        border: `1px solid ${!prereqMet ? '#f85149' : reallyEnabled ? '#238636' : '#30363d'}`,
        marginBottom: 16,
      }}
      title={
        <Space>
          {icon}
          <span style={{ color: '#e6edf3', fontWeight: 600 }}>{name}</span>
          {statusTag}
        </Space>
      }
      extra={
        <Tooltip title={!prereqMet ? '请先完成下方配置步骤' : undefined}>
          <Switch
            checked={reallyEnabled}
            disabled={!prereqMet}
            onChange={onToggle}
            checkedChildren="启用"
            unCheckedChildren="停用"
          />
        </Tooltip>
      }
    >
      {/* 未满足前提条件：展示引导步骤 */}
      {!prereqMet && config.missing_prerequisite && (
        <Alert
          type="error"
          showIcon
          icon={<ExclamationCircleOutlined />}
          message="启用前需先完成以下配置"
          description={
            <div>
              <div style={{ marginBottom: 8 }}>{config.missing_prerequisite}</div>
              <Button
                size="small"
                type="primary"
                danger
                href="/tokens"
                icon={<KeyOutlined />}
              >
                前往配置凭证 →
              </Button>
            </div>
          }
          style={{ marginBottom: 12 }}
        />
      )}

      <div style={{ color: '#8b949e', fontSize: 12, marginBottom: prereqMet ? 16 : 0 }}>
        {config.description}
      </div>

      {/* 只有前提条件满足时才显示频率等配置 */}
      {prereqMet && (
        <Space align="center" style={{ marginTop: 8 }}>
          <span style={{ color: '#8b949e', fontSize: 13 }}>抓取频率</span>
          <Select
            value={interval}
            onChange={onIntervalChange}
            options={INTERVAL_OPTIONS}
            disabled={!reallyEnabled}
            style={{ width: 160 }}
          />
          {tokenHint}
        </Space>
      )}
    </Card>
  )
}

// ── 数据源 Tab ─────────────────────────────────────────────────────────────────

function SourcesTab() {
  const { data: overview, isLoading, refetch } = useQuery({
    queryKey: ['settings-overview'],
    queryFn: getSettingsOverview,
    refetchInterval: 10_000,  // 定期刷新：用户配置完 token 后自动更新状态
  })
  const [ghEnabled, setGhEnabled] = useState<boolean | undefined>()
  const [ghInterval, setGhInterval] = useState<string | undefined>()
  const [rdEnabled, setRdEnabled] = useState<boolean | undefined>()
  const [rdInterval, setRdInterval] = useState<string | undefined>()
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)

  const saveMut = useMutation({
    mutationFn: updateSourceSettings,
    onSuccess: (res) => { setResult(res); refetch() },
  })

  if (isLoading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
  if (!overview) return null

  const gh = overview.github
  const rd = overview.reddit

  const currentGhEnabled = ghEnabled ?? gh.env_enabled
  const currentGhInterval = ghInterval ?? gh.interval
  const currentRdEnabled = rdEnabled ?? rd.env_enabled
  const currentRdInterval = rdInterval ?? rd.interval

  return (
    <div>
      <Alert
        type="info"
        showIcon
        message="修改配置后点击「保存」写入 .env 文件，重启服务后生效"
        style={{ marginBottom: 20 }}
      />

      <SourceCard
        icon={<GithubOutlined style={{ color: '#e6edf3' }} />}
        name="GitHub"
        config={gh}
        envEnabled={currentGhEnabled}
        interval={currentGhInterval}
        onToggle={setGhEnabled}
        onIntervalChange={setGhInterval}
        tokenHint={
          <Tooltip title="无 Token：60次/h；配置 Token：5000次/h。建议前往「凭证管理」配置">
            <InfoCircleOutlined style={{ color: '#8b949e' }} />
          </Tooltip>
        }
      />

      <SourceCard
        icon={<span style={{ fontSize: 16 }}>🤖</span>}
        name="Reddit"
        config={rd}
        envEnabled={currentRdEnabled}
        interval={currentRdInterval}
        onToggle={setRdEnabled}
        onIntervalChange={setRdInterval}
      />

      {/* 未来平台 */}
      <Card
        bordered={false}
        style={{ background: '#0d1117', border: '1px dashed #30363d', marginBottom: 20 }}
        title={<span style={{ color: '#8b949e', fontSize: 13 }}>即将支持的数据源</span>}
        size="small"
      >
        <Space wrap>
          {['Hacker News', 'Zeli', 'PyPI Trending', 'HuggingFace', 'Product Hunt', 'Zhihu'].map(p => (
            <Tag key={p} color="default" style={{ color: '#8b949e' }}>{p} · 开发中</Tag>
          ))}
        </Space>
      </Card>

      {result && (
        <Alert
          type={result.ok ? 'success' : 'error'}
          message={result.message}
          showIcon
          style={{ marginBottom: 12 }}
          closable
          onClose={() => setResult(null)}
        />
      )}

      <Button
        type="primary"
        icon={<SaveOutlined />}
        loading={saveMut.isPending}
        onClick={() => saveMut.mutate({
          github_enabled: currentGhEnabled,
          github_interval: currentGhInterval,
          reddit_enabled: currentRdEnabled,
          reddit_interval: currentRdInterval,
        })}
      >
        保存数据源配置
      </Button>
    </div>
  )
}

// ── 模型服务 Tab ───────────────────────────────────────────────────────────────

function LLMTab() {
  const { data: overview, isLoading, refetch } = useQuery({
    queryKey: ['settings-overview'],
    queryFn: getSettingsOverview,
  })
  const [form] = Form.useForm()
  const [activeProfile, setActiveProfile] = useState<string | undefined>()
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; model_used?: string } | null>(null)
  const [saveResult, setSaveResult] = useState<{ ok: boolean; message: string } | null>(null)

  const saveMut = useMutation({
    mutationFn: updateLLMSettings,
    onSuccess: (res) => {
      setSaveResult(res)
      refetch()
    },
  })
  const testMut = useMutation({
    mutationFn: testLLMSettings,
    onSuccess: (res) => setTestResult(res),
  })

  if (isLoading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
  if (!overview) return null

  const profile = activeProfile ?? overview.active_profile
  const profileData = overview[profile as 'yunwu' | 'heyi' | 'ollama' | 'openai']
  const desc = PROFILE_DESCS[profile]

  const handleProfileChange = (p: string) => {
    setActiveProfile(p)
    setTestResult(null)
    const pd = overview[p as 'yunwu' | 'heyi' | 'ollama' | 'openai']
    form.setFieldsValue({
      model: pd.model,
      base_url: pd.base_url,
      api_key: '',
    })
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        message={
          <span>
            当前使用：<strong style={{ color: '#58a6ff' }}>{PROFILE_DESCS[overview.active_profile]?.label}</strong>
            {overview.active_profile !== profile && (
              <span style={{ color: '#f0883e', marginLeft: 8 }}>（未保存，点击保存后重启生效）</span>
            )}
          </span>
        }
        style={{ marginBottom: 20 }}
      />

      {/* Profile 选择 */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ color: '#8b949e', fontSize: 12, marginBottom: 10 }}>选择模型服务</div>
        <Radio.Group value={profile} onChange={e => handleProfileChange(e.target.value)}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {Object.entries(PROFILE_DESCS).map(([key, d]) => (
              <Radio key={key} value={key}>
                <Card
                  size="small"
                  bordered={false}
                  style={{
                    background: profile === key ? '#1c2d40' : '#0d1117',
                    border: `1px solid ${profile === key ? '#58a6ff' : '#30363d'}`,
                    display: 'inline-block',
                    minWidth: 480,
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  <Space>
                    {key === 'heyi' && <ThunderboltOutlined style={{ color: '#3fb950' }} />}
                    {key === 'yunwu' && <span style={{ color: '#58a6ff' }}>☁</span>}
                    {key === 'ollama' && <span>🦙</span>}
                    {key === 'openai' && <span>⬡</span>}
                    <span style={{ color: '#e6edf3', fontWeight: 600 }}>{d.label}</span>
                    <Tag color={d.tagColor} style={{ fontSize: 11 }}>{d.tag}</Tag>
                    {key === overview.active_profile && (
                      <Tag color="success" style={{ fontSize: 10 }}>当前激活</Tag>
                    )}
                  </Space>
                  <div style={{ color: '#8b949e', fontSize: 11, marginTop: 4, paddingLeft: 24 }}>
                    {d.desc}
                  </div>
                </Card>
              </Radio>
            ))}
          </Space>
        </Radio.Group>
      </div>

      <Divider style={{ borderColor: '#30363d' }} />

      {/* 当前 Profile 的详细配置 */}
      <div style={{ marginBottom: 8, color: '#8b949e', fontSize: 12 }}>
        配置 — {desc?.label}
        {profileData?.api_key_masked && (
          <span style={{ marginLeft: 8 }}>当前 Key：<code>{profileData.api_key_masked}</code></span>
        )}
      </div>

      <Form
        form={form}
        layout="vertical"
        initialValues={{
          model: profileData?.model,
          base_url: profileData?.base_url,
          api_key: '',
        }}
      >
        {profile !== 'ollama' && (
          <Form.Item
            name="api_key"
            label={<span style={{ color: '#8b949e', fontSize: 12 }}>API Key{profile !== 'heyi' ? '（留空则不修改）' : '（Heyi 本地无需修改）'}</span>}
          >
            <Input.Password
              placeholder={profile === 'heyi' ? 'sk-heyi-local（默认）' : '输入新 Key 覆盖（留空不修改）'}
              disabled={profile === 'heyi'}
              style={{ fontFamily: 'monospace', background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
            />
          </Form.Item>
        )}
        {profile !== 'openai' && (
          <Form.Item
            name="base_url"
            label={<span style={{ color: '#8b949e', fontSize: 12 }}>API Base URL</span>}
          >
            <Input
              style={{ fontFamily: 'monospace', background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
            />
          </Form.Item>
        )}
        <Form.Item
          name="model"
          label={<span style={{ color: '#8b949e', fontSize: 12 }}>模型名称</span>}
        >
          <Input
            style={{ fontFamily: 'monospace', background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
          />
        </Form.Item>
      </Form>

      {testResult && (
        <Alert
          type={testResult.ok ? 'success' : 'error'}
          message={testResult.message}
          description={testResult.ok && testResult.model_used ? `实际模型：${testResult.model_used}` : undefined}
          showIcon
          style={{ marginBottom: 12 }}
          closable
          onClose={() => setTestResult(null)}
        />
      )}
      {saveResult && (
        <Alert
          type={saveResult.ok ? 'success' : 'error'}
          message={saveResult.message}
          showIcon
          style={{ marginBottom: 12 }}
          closable
          onClose={() => setSaveResult(null)}
        />
      )}

      <Space>
        <Button
          icon={<ExperimentOutlined />}
          loading={testMut.isPending}
          onClick={() => {
            const vals = form.getFieldsValue()
            testMut.mutate({ profile, ...vals })
          }}
        >
          测试连接
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saveMut.isPending}
          onClick={() => {
            const vals = form.getFieldsValue()
            saveMut.mutate({ profile, ...vals })
          }}
        >
          保存并切换
        </Button>
      </Space>
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────

export default function Settings() {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ color: '#e6edf3', marginBottom: 4, fontSize: 18 }}>⚙️ 系统设置</h2>
          <p style={{ color: '#8b949e', margin: 0, fontSize: 13 }}>
            配置数据源抓取范围、频率，以及 LLM 分析模型服务。设置保存至本地 <code>.env</code> 文件，重启服务后生效。
          </p>
        </div>
        <Button icon={<ReloadOutlined />} size="small" href="/incidents">
          查看告警
        </Button>
      </div>

      <Card
        bordered={false}
        style={{ background: '#161b22', border: '1px solid #30363d' }}
        styles={{ body: { padding: '8px 24px 24px' } }}
      >
        <Tabs
          defaultActiveKey="sources"
          items={[
            {
              key: 'sources',
              label: (
                <span>
                  🗄️ 数据源配置
                </span>
              ),
              children: <SourcesTab />,
            },
            {
              key: 'llm',
              label: (
                <span>
                  🤖 模型服务
                </span>
              ),
              children: <LLMTab />,
            },
          ]}
        />
      </Card>
    </div>
  )
}
