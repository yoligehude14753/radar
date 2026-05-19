import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
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
import { useState, type FC } from 'react'
import { getIncidents } from './api/client'

import Dashboard from './pages/Dashboard'
import ReportsProjects from './pages/ReportsProjects'
import ReportsCommunities from './pages/ReportsCommunities'
import Sources from './pages/Sources'
import Tokens from './pages/Tokens'
import Incidents from './pages/Incidents'

const { Sider, Content } = Layout
const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } })

const AppLayout: FC = () => {
  const [collapsed, setCollapsed] = useState(false)
  const { data: incidents } = useQuery({
    queryKey: ['incidents', 'open'],
    queryFn: () => getIncidents('open'),
    refetchInterval: 60_000,
  })
  const openCount = incidents?.length ?? 0

  const items = [
    { key: '/', icon: <HomeOutlined />, label: <NavLink to="/">仪表盘</NavLink> },
    { key: '/reports/projects', icon: <FileOutlined />, label: <NavLink to="/reports/projects">项目报告</NavLink> },
    { key: '/reports/communities', icon: <GlobalOutlined />, label: <NavLink to="/reports/communities">社群地图</NavLink> },
    { key: '/sources', icon: <DatabaseOutlined />, label: <NavLink to="/sources">数据源</NavLink> },
    { key: '/tokens', icon: <KeyOutlined />, label: <NavLink to="/tokens">Token 管理</NavLink> },
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
        }}>
          🛰️ {!collapsed && 'Radar'}
        </div>
        <Menu
          mode="inline"
          theme="dark"
          style={{ background: '#161b22', borderRight: 'none', marginTop: 8 }}
          items={items}
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

export default function App() {
  return (
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
  )
}
