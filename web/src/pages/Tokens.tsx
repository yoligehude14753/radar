import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Card, Button, Alert, Typography, Space, Divider, Tag, Input, Form, Steps,
} from 'antd'
import {
  GithubOutlined, CheckCircleOutlined, ExclamationCircleOutlined,
  ExperimentOutlined, SaveOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { getTokenStatus, testRedditToken, saveRedditToken, testGithubToken, saveGithubToken } from '../api/client'

const { Text, Link } = Typography

// ── 子组件：GitHub Token 配置卡 ───────────────────────────────────────────────

function GithubCard({ configured, masked }: { configured: boolean; masked: string | null }) {
  const [form] = Form.useForm<{ token: string }>()
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const testMut = useMutation({
    mutationFn: (token: string) => testGithubToken(token),
    onSuccess: (res) => setTestResult(res),
  })
  const saveMut = useMutation({
    mutationFn: (token: string) => saveGithubToken(token),
    onSuccess: () => {
      setTestResult({ ok: true, message: '已保存到 .env，重启服务后生效' })
    },
  })

  return (
    <Card
      title={
        <Space>
          <GithubOutlined style={{ color: '#e6edf3' }} />
          <span style={{ color: '#e6edf3' }}>GitHub Personal Access Token</span>
          <Tag color={configured ? 'success' : 'default'} icon={configured ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />}>
            {configured ? `已配置 (${masked})` : '未配置'}
          </Tag>
        </Space>
      }
      bordered={false}
      style={{ background: '#161b22', border: '1px solid #30363d', marginBottom: 16 }}
    >
      <p style={{ color: '#8b949e', marginBottom: 16 }}>
        配置后 API 速率从 <Tag color="orange">60 次/h</Tag> 提升至 <Tag color="green">5000 次/h</Tag>，
        持续抓取强烈推荐配置。
      </p>

      <Steps
        size="small"
        style={{ marginBottom: 16 }}
        items={[
          {
            title: <Text style={{ color: '#8b949e', fontSize: 12 }}>前往 GitHub 创建 Token</Text>,
            description: (
              <Link
                href="https://github.com/settings/tokens/new?description=Radar+AI+Tracker&scopes=public_repo,read:org"
                target="_blank"
                style={{ fontSize: 11 }}
              >
                点击一键跳转 → Token 创建页 ↗
              </Link>
            ),
            status: 'process',
          },
          {
            title: <Text style={{ color: '#8b949e', fontSize: 12 }}>勾选权限</Text>,
            description: <Text style={{ color: '#8b949e', fontSize: 11 }}><code>public_repo</code> + <code>read:org</code></Text>,
            status: 'process',
          },
          {
            title: <Text style={{ color: '#8b949e', fontSize: 12 }}>粘贴到下方并保存</Text>,
            status: 'process',
          },
        ]}
      />

      <Form form={form} layout="vertical">
        <Form.Item name="token" label={<span style={{ color: '#8b949e', fontSize: 12 }}>Personal Access Token</span>}>
          <Input.Password
            placeholder="ghp_xxxxxxxxxxxx"
            style={{ fontFamily: 'monospace', background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
          />
        </Form.Item>
      </Form>

      {testResult && (
        <Alert
          type={testResult.ok ? 'success' : 'error'}
          message={testResult.message}
          showIcon
          style={{ marginBottom: 12 }}
          closable
          onClose={() => setTestResult(null)}
        />
      )}

      <Space>
        <Button
          icon={<ExperimentOutlined />}
          loading={testMut.isPending}
          onClick={async () => {
            const { token } = form.getFieldsValue()
            if (!token) { setTestResult({ ok: false, message: 'Token 不能为空' }); return }
            testMut.mutate(token)
          }}
        >
          测试连接
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saveMut.isPending}
          onClick={async () => {
            const { token } = form.getFieldsValue()
            if (!token) { setTestResult({ ok: false, message: 'Token 不能为空' }); return }
            saveMut.mutate(token)
          }}
        >
          保存
        </Button>
      </Space>
    </Card>
  )
}

// ── 子组件：Reddit OAuth 配置卡 ───────────────────────────────────────────────

function RedditCard({ configured, masked }: { configured: boolean; masked: string | null }) {
  const [form] = Form.useForm<{
    client_id: string
    client_secret: string
    username: string
    password: string
  }>()
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const testMut = useMutation({
    mutationFn: (vals: { client_id: string; client_secret: string; username: string; password: string }) =>
      testRedditToken(vals),
    onSuccess: (res) => setTestResult(res),
  })
  const saveMut = useMutation({
    mutationFn: (vals: { client_id: string; client_secret: string; username: string; password: string }) =>
      saveRedditToken(vals),
    onSuccess: () => {
      setTestResult({ ok: true, message: '已保存到 .env，重启服务后生效' })
    },
  })

  return (
    <Card
      title={
        <Space>
          <span style={{ fontSize: 16 }}>🤖</span>
          <span style={{ color: '#e6edf3' }}>Reddit OAuth App</span>
          <Tag
            color={configured ? 'success' : 'error'}
            icon={configured ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />}
          >
            {configured ? `已配置 (${masked})` : '未配置 — 将导致抓取失败'}
          </Tag>
        </Space>
      }
      bordered={false}
      style={{
        background: '#161b22',
        border: `1px solid ${configured ? '#30363d' : '#f85149'}`,
        marginBottom: 16,
      }}
    >
      {!configured && (
        <Alert
          type="error"
          showIcon
          message="Reddit 已禁止匿名访问，必须配置 OAuth App 才能正常抓取"
          description="免费创建一个 Script App，无需审核，5 分钟完成配置。"
          style={{ marginBottom: 16 }}
        />
      )}

      <p style={{ color: '#8b949e', marginBottom: 16 }}>
        配置后 Reddit 速率从 <Tag color="error">封禁（403）</Tag> 恢复至 <Tag color="green">60 次/min</Tag>。
      </p>

      <Steps
        size="small"
        style={{ marginBottom: 16 }}
        direction="vertical"
        items={[
          {
            title: <Text style={{ color: '#8b949e', fontSize: 12 }}>打开 Reddit App 管理页</Text>,
            description: (
              <Link href="https://www.reddit.com/prefs/apps" target="_blank" style={{ fontSize: 11 }}>
                reddit.com/prefs/apps ↗（需登录）
              </Link>
            ),
            status: 'process',
          },
          {
            title: <Text style={{ color: '#8b949e', fontSize: 12 }}>点击 "are you a developer? create an app"</Text>,
            description: (
              <div style={{ fontSize: 11, color: '#8b949e', lineHeight: 1.8 }}>
                · name: <code>Radar AI Tracker</code><br />
                · 类型选: <code>script</code><br />
                · redirect uri: <code>http://localhost</code><br />
                · 点击 Create app
              </div>
            ),
            status: 'process',
          },
          {
            title: <Text style={{ color: '#8b949e', fontSize: 12 }}>复制凭证，填入下方</Text>,
            description: (
              <Text style={{ fontSize: 11, color: '#8b949e' }}>
                App 名称下方短字符串 = <code>client_id</code>；"secret" 后面的 = <code>client_secret</code>
              </Text>
            ),
            status: 'process',
          },
        ]}
      />

      <Form form={form} layout="vertical">
        <Form.Item name="client_id" label={<span style={{ color: '#8b949e', fontSize: 12 }}>Client ID（App 名称下方的短字符串）</span>}>
          <Input
            placeholder="例：AbCdEfGhIj1234"
            style={{ fontFamily: 'monospace', background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
          />
        </Form.Item>
        <Form.Item name="client_secret" label={<span style={{ color: '#8b949e', fontSize: 12 }}>Client Secret</span>}>
          <Input.Password
            placeholder="例：AbCdEfGhIjKlMnOpQrStUvWxYz1234"
            style={{ fontFamily: 'monospace', background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
          />
        </Form.Item>

        <Divider style={{ borderColor: '#30363d', margin: '8px 0 12px' }}>
          <Text style={{ fontSize: 11, color: '#8b949e' }}>可选：填用户名密码可获取更高权限（也可留空）</Text>
        </Divider>

        <Space style={{ width: '100%' }}>
          <Form.Item name="username" label={<span style={{ color: '#8b949e', fontSize: 12 }}>Reddit 用户名</span>} style={{ flex: 1, marginBottom: 0 }}>
            <Input
              placeholder="u/your_username（可留空）"
              style={{ background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
            />
          </Form.Item>
          <Form.Item name="password" label={<span style={{ color: '#8b949e', fontSize: 12 }}>Reddit 密码</span>} style={{ flex: 1, marginBottom: 0 }}>
            <Input.Password
              placeholder="（可留空）"
              style={{ background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }}
            />
          </Form.Item>
        </Space>
      </Form>

      {testResult && (
        <Alert
          type={testResult.ok ? 'success' : 'error'}
          message={testResult.message}
          showIcon
          style={{ margin: '12px 0' }}
          closable
          onClose={() => setTestResult(null)}
        />
      )}

      <Space style={{ marginTop: 12 }}>
        <Button
          icon={<ExperimentOutlined />}
          loading={testMut.isPending}
          onClick={() => {
            const vals = form.getFieldsValue()
            if (!vals.client_id || !vals.client_secret) {
              setTestResult({ ok: false, message: 'Client ID 和 Secret 不能为空' })
              return
            }
            testMut.mutate({ client_id: vals.client_id, client_secret: vals.client_secret, username: vals.username ?? '', password: vals.password ?? '' })
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
            if (!vals.client_id || !vals.client_secret) {
              setTestResult({ ok: false, message: 'Client ID 和 Secret 不能为空' })
              return
            }
            saveMut.mutate({ client_id: vals.client_id, client_secret: vals.client_secret, username: vals.username ?? '', password: vals.password ?? '' })
          }}
        >
          保存
        </Button>
      </Space>
    </Card>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────

export default function Tokens() {
  const { data: status, isLoading, refetch } = useQuery({
    queryKey: ['token-status'],
    queryFn: getTokenStatus,
    refetchInterval: 30_000,
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ color: '#e6edf3', marginBottom: 4, fontSize: 18 }}>🔑 Token / 凭证管理</h2>
          <p style={{ color: '#8b949e', margin: 0, fontSize: 13 }}>
            配置 API 凭证以解锁数据源访问。Token 仅保存在本地 <code>.env</code> 文件，不上传到任何服务器。
          </p>
        </div>
        <Button
          icon={<ReloadOutlined spin={isLoading} />}
          size="small"
          onClick={() => refetch()}
        >
          刷新状态
        </Button>
      </div>

      <GithubCard
        configured={status?.github_configured ?? false}
        masked={status?.github_masked ?? null}
      />

      <RedditCard
        configured={status?.reddit_configured ?? false}
        masked={status?.reddit_client_masked ?? null}
      />

      <Alert
        message="安全提示"
        description={
          <span>
            Token 仅存储在本地 <code>radar/.env</code> 文件中。<code>.gitignore</code> 已默认排除，
            不会随代码上传到 GitHub。
          </span>
        }
        type="info"
        showIcon
        style={{ marginTop: 8 }}
      />
    </div>
  )
}
