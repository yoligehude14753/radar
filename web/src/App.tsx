import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, Layout, Menu, theme, Badge } from 'antd'
import {
  HomeOutlined,
  FileOutlined,
  GlobalOutlined,
  DatabaseOutlined,
  KeyOutlined,
  AlertOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useState, type FC, Component, type ReactNode } from 'react'
import { getIncidents } from './api/client'

import Dashboard from './pages/Dashboard'
import ReportsProjects from './pages/ReportsProjects'
import ReportsCommunities from './pages/ReportsCommunities'
import Sources from './pages/Sources'
import Tokens from './pages/Tokens'
import Incidents from './pages/Incidents'

const { Sider, Content } = Layout
const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } })

// ── 错误边界 ──────────────────────────────────────────────────────────────────

class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    const { error } = this.state
    if (error) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          background: '#0d1117',
          color: '#e6edf3',
          gap: 16,
          padding: 32,
        }}>
          <div style={{ fontSize: 48 }}>⚠️</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>页面渲染出错</div>
          <div style={{ color: '#8b949e', fontSize: 13, maxWidth: 500, textAlign: 'center' }}>
            {error.message}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '8px 20px',
              background: '#58a6ff',
              border: 'none',
              borderRadius: 6,
              color: '#fff',
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            刷新重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// ── 主布局 ────────────────────────────────────────────────────────────────────

const AppLayout: FC = () => {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const { data: incidents } = useQuery({
    queryKey: ['incidents', 'open'],
    queryFn: () => getIncidents('open'),
    refetchInterval: 60_000,
  })
  const openCount = incidents?.length ?? 0

  const menuItems = [
    { key: '/', icon: <HomeOutlined />, label: <NavLink to="/">仪表盘</NavLink> },
    { key: '/reports/projects', icon: <FileOutlined />, label: <NavLink to="/reports/projects">项目报告</NavLink> },
    { key: '/reports/communities', icon: <GlobalOutlined />, label: <NavLink to="/reports/communities">社群地图</NavLink> },
    { key: '/sources', icon: <DatabaseOutlined />, label: <NavLink to="/sources">数据源</NavLink> },
    { key: '/tokens', icon: <KeyOutlined />, label: <NavLink to="/tokens">凭证管理</NavLink> },
    {
      key: '/incidents',
      icon: <AlertOutlined />,
      label: (
        <NavLink to="/incidents">
          告警
          {openCount > 0 && (
            <Badge count={openCount} size="small" style={{ marginLeft: 6 }} />
          )}
        </NavLink>
      ),
    },
  ]

  // 匹配当前路径到 Menu selectedKey
  const selectedKey = menuItems
    .map(i => i.key)
    .filter(k => k !== '/')
    .find(k => location.pathname.startsWith(k)) ?? '/'

  return (
    <Layout style={{ minHeight: '100vh', background: '#0d1117' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{ background: '#161b22', borderRight: '1px solid #30363d' }}
      >
        <div style={{
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          padding: collapsed ? 0 : '0 16px',
          borderBottom: '1px solid #30363d',
          fontSize: collapsed ? 20 : 14,
          fontWeight: 700,
          color: '#58a6ff',
          gap: 8,
          cursor: 'default',
          userSelect: 'none',
        }}>
          🛰️{!collapsed && <span style={{ marginLeft: 6 }}>Radar</span>}
        </div>
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[selectedKey]}
          style={{ background: '#161b22', borderRight: 'none', marginTop: 8 }}
          items={menuItems}
        />
      </Sider>
      <Layout style={{ background: '#0d1117' }}>
        <Content style={{ padding: '20px 24px', overflowY: 'auto' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/reports/projects" element={<ReportsProjects />} />
            <Route path="/reports/communities" element={<ReportsCommunities />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/tokens" element={<Tokens />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

// ── 应用入口 ──────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={qc}>
        <ConfigProvider
          theme={{
            algorithm: theme.darkAlgorithm,
            token: {
              colorPrimary: '#58a6ff',
              colorBgContainer: '#161b22',
              colorBgElevated: '#21262d',
              colorBorder: '#30363d',
              colorText: '#e6edf3',
              colorTextSecondary: '#8b949e',
              borderRadius: 8,
            },
          }}
        >
          <BrowserRouter>
            <AppLayout />
          </BrowserRouter>
        </ConfigProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
