import { useEffect, useState } from 'react';
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router';
import { LayoutDashboard, Files, UploadCloud, PlayCircle, Scale, KeyRound, LogOut } from 'lucide-react';
import { Toaster } from '@/components/ui/sonner';
import { api, type AdminInfo } from '@/lib/api';
import Dashboard from './pages/Dashboard';
import Cases from './pages/Cases';
import Upload from './pages/Upload';
import Runs from './pages/Runs';
import Login from './pages/Login';
import Accounts from './pages/Accounts';

const NAV = [
  { to: '/', label: '概览', icon: LayoutDashboard, end: true },
  { to: '/cases', label: '案件管理', icon: Files },
  { to: '/upload', label: '数据上传', icon: UploadCloud },
  { to: '/runs', label: '立案运行', icon: PlayCircle },
  { to: '/accounts', label: '账号管理', icon: KeyRound },
];

function Shell() {
  const nav = useNavigate();
  const [me, setMe] = useState<AdminInfo | null>(null);
  useEffect(() => { api.me().then(setMe).catch(() => { /* 401 会自行跳登录 */ }); }, []);

  const doLogout = async () => {
    try { await api.logout(); } catch { /* 忽略 */ }
    localStorage.removeItem('admin_token');
    nav('/login', { replace: true });
  };

  return (
    <div className="flex min-h-dvh">
      <aside className="flex w-56 shrink-0 flex-col bg-[hsl(224,42%,16%)] text-[hsl(220,20%,88%)]">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[hsl(6,60%,42%)]">
            <Scale className="h-5 w-5 text-white" />
          </span>
          <div>
            <div className="text-sm font-semibold tracking-wide text-white">法院立案管理后台</div>
            <div className="text-[11px] text-[hsl(220,15%,60%)]">Court Filing Admin</div>
          </div>
        </div>
        <nav className="mt-2 flex flex-col gap-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-md px-3 py-2.5 text-sm transition-colors outline-none
                 focus-visible:ring-2 focus-visible:ring-white/60 ${
                   isActive
                     ? 'bg-[hsl(6,60%,42%)] font-medium text-white'
                     : 'text-[hsl(220,18%,75%)] hover:bg-white/10 hover:text-white'
                 }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2 px-5 py-4 text-[11px] leading-relaxed text-[hsl(220,15%,55%)]">
          {me && (
            <div className="rounded-md bg-white/5 p-2.5">
              <div className="text-[hsl(220,20%,80%)]">{me.display_name || me.username}</div>
              <div>
                立案账号：{me.bound_court_account
                  ? <span className="text-[hsl(140,50%,60%)]">{me.bound_court_account}</span>
                  : <span className="text-[hsl(40,70%,60%)]">未绑定</span>}
              </div>
              <button
                type="button"
                onClick={doLogout}
                className="mt-1.5 flex items-center gap-1 text-[hsl(220,15%,60%)] transition-colors hover:text-white outline-none focus-visible:ring-1 focus-visible:ring-white/60"
              >
                <LogOut className="h-3 w-3" /> 退出登录
              </button>
            </div>
          )}
          数据源：本地 MySQL
          <br />
          立案模式：DRY RUN（不提交）
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/accounts" element={<Accounts />} />
        </Routes>
      </main>
      <Toaster richColors position="top-right" />
    </div>
  );
}

export default function App() {
  const loc = useLocation();
  const hasToken = !!localStorage.getItem('admin_token');
  if (loc.pathname === '/login') {
    return (
      <>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
        <Toaster richColors position="top-right" />
      </>
    );
  }
  if (!hasToken) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return <Shell />;
}
