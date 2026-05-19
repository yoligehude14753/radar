import { useState } from 'react'
import { Card, Button, Alert, Typography, Space, Divider, Tag } from 'antd'
import { GithubOutlined, SettingOutlined } from '@ant-design/icons'

const { Text, Link } = Typography

interface TokenCardProps {
  icon: React.ReactNode
  title: string
  description: string
  steps: string[]
  docsUrl: string
  envKey: string
  configured: boolean
}

function TokenCard({ icon, title, description, steps, docsUrl, envKey, configured }: TokenCardProps) {
  const [showSteps, setShowSteps] = useState(false)

  return (
    <Card
      title={
        <Space>
          {icon}
          <span style={{ color: '#e6edf3' }}>{title}</span>
          <Tag color={configured ? 'success' : 'default'}>
            {configured ? '已配置' : '未配置'}
          </Tag>
        </Space>
      }
      bordered={false}
      style={{ background: '#161b22', border: '1px solid #30363d', marginBottom: 16 }}
    >
      <p style={{ color: '#8b949e', marginBottom: 12 }}>{description}</p>

      {!configured && (
        <Alert
          message={`请在 .env 文件中配置 ${envKey}`}
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      <Button
        size="small"
        onClick={() => setShowSteps(!showSteps)}
        icon={<SettingOutlined />}
        style={{ marginBottom: showSteps ? 12 : 0 }}
      >
        {showSteps ? '收起步骤' : '查看配置步骤'}
      </Button>

      {showSteps && (
        <div style={{
          background: '#0d1117',
          border: '1px solid #30363d',
          borderRadius: 8,
          padding: 16,
          marginTop: 8,
        }}>
          <ol style={{ color: '#8b949e', paddingLeft: 20, margin: 0 }}>
            {steps.map((step, i) => (
              <li key={i} style={{ marginBottom: 8, lineHeight: 1.6 }} dangerouslySetInnerHTML={{ __html: step }} />
            ))}
          </ol>
          <Divider style={{ borderColor: '#30363d', margin: '12px 0' }} />
          <div style={{ fontFamily: 'monospace', background: '#161b22', padding: 12, borderRadius: 6, color: '#58a6ff', fontSize: 13 }}>
            {envKey}=your_token_here
          </div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
            写入 <code>radar/.env</code> 文件后重启服务生效
          </Text>
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        <Link href={docsUrl} target="_blank" style={{ fontSize: 12 }}>
          📖 官方文档
        </Link>
      </div>
    </Card>
  )
}

export default function Tokens() {
  // 实际环境中通过 /api/health 的扩展字段判断是否已配置
  const githubConfigured = false  // 占位，实际从 health API 获取
  const redditConfigured = false

  return (
    <div>
      <h2 style={{ color: '#e6edf3', marginBottom: 8, fontSize: 18 }}>
        🔑 Token 管理
      </h2>
      <p style={{ color: '#8b949e', marginBottom: 20 }}>
        配置 API Token 以提升抓取速率和解锁更多功能。所有 Token 保存在本地 .env 文件，不会上传到任何服务器。
      </p>

      <TokenCard
        icon={<GithubOutlined style={{ color: '#e6edf3' }} />}
        title="GitHub Personal Access Token"
        description="配置后速率限制从 60 次/小时提升至 5000 次/小时（83 倍提升）。对于持续抓取功能是强烈推荐的。"
        configured={githubConfigured}
        envKey="GITHUB_TOKEN"
        docsUrl="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens"
        steps={[
          '打开 <a href="https://github.com/settings/tokens/new" target="_blank" style="color:#58a6ff">GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)</a>',
          'Note（备注）填：<code>Radar AI 趋势抓取</code>',
          'Expiration 选：90 days',
          'Scopes 勾选：<code>public_repo</code> 和 <code>read:org</code>',
          '点击「Generate token」，复制 token（只显示一次！）',
        ]}
      />

      <TokenCard
        icon={<span style={{ fontSize: 16 }}>🤖</span>}
        title="Reddit OAuth App"
        description="配置后速率限制从 30 次/10分钟提升至 60 次/分钟。公开 API 无需配置也可使用。"
        configured={redditConfigured}
        envKey="REDDIT_CLIENT_ID"
        docsUrl="https://www.reddit.com/prefs/apps"
        steps={[
          '打开 <a href="https://www.reddit.com/prefs/apps" target="_blank" style="color:#58a6ff">Reddit Preferences → Apps</a>',
          '点击「are you a developer? create an app」',
          'name 填：<code>Radar AI Tracker</code>，类型选：<code>script</code>',
          'redirect uri 填：<code>http://localhost</code>',
          '创建后复制 client id（app 名下方的短字符串）和 secret',
          '同时设置 <code>REDDIT_CLIENT_ID</code> 和 <code>REDDIT_CLIENT_SECRET</code>',
        ]}
      />

      <Alert
        message="安全提示"
        description="Token 仅存储在本地 .env 文件中，请确保不要将 .env 文件提交到 Git 仓库（.gitignore 已默认排除）。"
        type="info"
        showIcon
        style={{ marginTop: 8 }}
      />
    </div>
  )
}
