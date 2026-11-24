import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Scale, LogIn } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';

export default function Login() {
  const nav = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const doLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setErr('请输入用户名和密码');
      return;
    }
    setBusy(true);
    setErr('');
    try {
      const r = await api.login(username.trim(), password);
      localStorage.setItem('admin_token', r.token);
      nav('/', { replace: true });
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '登录失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[hsl(224,42%,12%)]">
      <Card className="w-96">
        <CardHeader className="items-center space-y-3 pb-2">
          <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-[hsl(6,60%,42%)]">
            <Scale className="h-6 w-6 text-white" />
          </span>
          <CardTitle className="text-lg">法院立案管理后台</CardTitle>
          <p className="text-xs text-muted-foreground">请使用管理员账号登录</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={doLogin} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="login-username" className="text-sm font-medium">用户名</label>
              <input
                id="login-username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="admin"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="login-password" className="text-sm font-medium">密码</label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="••••••"
              />
            </div>
            {err && <p role="alert" className="text-sm text-destructive">{err}</p>}
            <Button type="submit" disabled={busy}
                    className="w-full bg-[hsl(6,60%,42%)] text-white hover:bg-[hsl(6,60%,36%)]">
              <LogIn className="mr-1.5 h-4 w-4" />
              {busy ? '登录中…' : '登 录'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
