import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { ApiOutlined, ClockCircleOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, SettingOutlined, SunOutlined, MoonOutlined } from '@ant-design/icons';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zh from '../../web/locales/zh';
import FinancialAnalysisPage from '../../web/new-components/financial-analysis/FinancialAnalysisPage';
import { mockReportData } from '../../web/new-components/financial-analysis/mock-report';
import { ChatContext } from './adapters/chat-context';
import logoLight from '../../web/public/logo_zh_latest.png';
import logoDark from '../../web/public/logo_s_latest.png';
import logoSmall from '../../web/public/LOGO_SMALL.png';
import explore from '../../web/public/pictures/explore_active.png';
import skills from '../../web/public/pictures/skills.svg';
import datasource from '../../web/public/pictures/datasource.svg';
import knowledge from '../../web/public/pictures/knowledge_sidebar.svg';

void i18n.use(initReactI18next).init({ lng: 'zh', fallbackLng: 'zh', resources: { zh: { translation: zh } }, interpolation: { escapeValue: false }, initImmediate: false });

function App() {
  const [mode, setMode] = useState<'light' | 'dark'>('light');
  const [expanded, setExpanded] = useState(true);
  useEffect(() => { document.documentElement.classList.toggle('dark', mode === 'dark'); }, [mode]);
  const links = [
    { label: '探索', image: explore, active: true },
    { label: '技能', image: skills },
    { label: '数据源', image: datasource },
    { label: '连接器', icon: <ApiOutlined /> },
    { label: '知识库', image: knowledge },
    { label: '定时任务', icon: <ClockCircleOutlined /> },
  ];
  return <ChatContext.Provider value={{ mode }}><ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#0C75FC', borderRadius: 4, fontFamily: 'Segoe UI, Microsoft YaHei, system-ui, sans-serif' }, algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm }}>
    <div className='offline-shell'>
      <aside className='offline-sidebar' data-expanded={expanded} aria-label='DB-GPT 全局侧栏'>
        <div className='offline-logo'><img src={expanded ? mode === 'dark' ? logoDark : logoLight : logoSmall} alt='DB-GPT' /><button type='button' aria-label={expanded ? '收起全局侧栏' : '展开全局侧栏'} onClick={() => setExpanded(value => !value)}>{expanded ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}</button></div>
        <button type='button' className='offline-new' aria-disabled='true' title='此独立文件仅包含财报分析任务'><PlusOutlined />{expanded && '新建任务'}</button>
        <nav aria-label='应用导航'>{links.map(link => <button type='button' aria-disabled='true' title='此独立文件仅包含财报分析任务' key={link.label} className={link.active ? 'active' : ''}>{link.image ? <img src={link.image} alt='' /> : link.icon}{expanded && <span>{link.label}</span>}</button>)}</nav>
        <div className='offline-tasks'>{expanded && <><div className='offline-muted'>全部任务</div><div className='offline-task'>2019 年度报告财务分析</div></>}</div>
        <button type='button' className='offline-settings' aria-disabled='true'><SettingOutlined />{expanded && '设置'}</button>
        <button type='button' className='offline-theme' aria-label={mode === 'dark' ? '切换浅色主题' : '切换深色主题'} onClick={() => setMode(value => value === 'dark' ? 'light' : 'dark')}>{mode === 'dark' ? <SunOutlined /> : <MoonOutlined />}{expanded && (mode === 'dark' ? '浅色模式' : '深色模式')}</button>
      </aside>
      <div className='offline-main'><FinancialAnalysisPage data={mockReportData} /></div>
    </div>
  </ConfigProvider></ChatContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<App />);
