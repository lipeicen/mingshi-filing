import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { KeyRound, Plus, Link2, Link2Off, UserCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api, type AdminInfo, type CourtAccount } from '@/lib/api';

export default function Accounts() {
  const [me, setMe] = useState<AdminInfo | null>(null);
  const [items, setItems] = useState<CourtAccount[]>([]);
  const [myBoundId, setMyBoundId] = useState<number | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', user_type: '个人用户' });
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [resetPw, setResetPw] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.courtAccounts().then((r) => { setItems(r.items); setMyBoundId(r.my_bound_id); })
      .catch((e) => toast.error(e.message));
    api.me().then(setMe).catch(() => { /* 忽略 */ });
  };
  useEffect(load, []);

  const doAdd = async () => {
    if (!form.username.trim() || !form.password) {
      toast.error('账号和密码不能为空');
      return;
    }
    setBusy(true);
    try {
      await api.createCourtAccount({ ...form, username: form.username.trim(), is_active: true });
      toast.success('已添加法院账号');
      setShowAdd(false);
      setForm({ username: '', password: '', user_type: '个人用户' });
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '添加失败');
    } finally {
      setBusy(false);
    }
  };

  const doToggle = async (acc: CourtAccount) => {
    try {
      await api.updateCourtAccount(acc.id, { is_active: !acc.is_active });
      toast.success(acc.is_active ? '已停用' : '已启用');
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '操作失败');
    }
  };

  const doResetPw = async () => {
    if (!resetFor || resetPw.length < 6) {
      toast.error('新密码至少 6 位');
      return;
    }
    try {
      await api.updateCourtAccount(resetFor, { password: resetPw });
      toast.success('密码已重置');
      setResetFor(null);
      setResetPw('');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '重置失败');
    }
  };

  const doBind = async (id: number) => {
    try {
      await api.bindCourtAccount(id);
      toast.success('已绑定为我的立案账号');
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '绑定失败');
    }
  };

  const doUnbind = async () => {
    try {
      await api.unbindCourtAccount();
      toast.success('已解绑');
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '解绑失败');
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">账号管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            管理法院立案平台账号；当前登录：<b>{me?.display_name || me?.username}</b>
            {myBoundId
              ? <>，立案使用账号：<b className="text-[hsl(150,60%,32%)]">{items.find((a) => a.id === myBoundId)?.username_masked || `#${myBoundId}`}</b></>
              : <span className="text-destructive">，尚未绑定立案账号（立案前必须绑定）</span>}
          </p>
        </div>
        <Button size="sm" onClick={() => setShowAdd(!showAdd)}
                className="bg-primary text-primary-foreground hover:bg-primary/90">
          <Plus className="mr-1 h-4 w-4" /> 添加法院账号
        </Button>
      </div>

      {showAdd && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">新增法院账号</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label htmlFor="acc-username" className="text-xs text-muted-foreground">登录账号（手机号）</label>
              <input id="acc-username" value={form.username}
                     onChange={(e) => setForm({ ...form, username: e.target.value })}
                     className="h-9 w-48 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                     placeholder="13xxxxxxxxx" />
            </div>
            <div className="space-y-1">
              <label htmlFor="acc-password" className="text-xs text-muted-foreground">密码</label>
              <input id="acc-password" type="password" value={form.password}
                     onChange={(e) => setForm({ ...form, password: e.target.value })}
                     className="h-9 w-48 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                     placeholder="登录密码" />
            </div>
            <div className="space-y-1">
              <label htmlFor="acc-type" className="text-xs text-muted-foreground">用户类型</label>
              <input id="acc-type" value={form.user_type}
                     onChange={(e) => setForm({ ...form, user_type: e.target.value })}
                     className="h-9 w-32 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
            </div>
            <Button size="sm" onClick={doAdd} disabled={busy}>{busy ? '保存中…' : '保存'}</Button>
            <Button size="sm" variant="outline" onClick={() => setShowAdd(false)}>取消</Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>账号</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>绑定情况</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((acc) => (
                <TableRow key={acc.id}>
                  <TableCell className="font-medium">{acc.username_masked}</TableCell>
                  <TableCell>{acc.user_type}</TableCell>
                  <TableCell>
                    {acc.is_active
                      ? <Badge className="bg-[hsl(150,60%,32%)] text-white">启用</Badge>
                      : <Badge variant="secondary">停用</Badge>}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {acc.id === myBoundId
                      ? <span className="flex items-center gap-1 text-[hsl(150,60%,32%)]"><UserCheck className="h-3.5 w-3.5" /> 我的立案账号</span>
                      : acc.bound_admins > 0 ? `被 ${acc.bound_admins} 个管理员绑定` : '未绑定'}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1.5">
                      {acc.id === myBoundId ? (
                        <Button size="sm" variant="outline" onClick={doUnbind}>
                          <Link2Off className="mr-1 h-3.5 w-3.5" /> 解绑
                        </Button>
                      ) : (
                        <Button size="sm" variant="outline" disabled={!acc.is_active}
                                onClick={() => doBind(acc.id)}>
                          <Link2 className="mr-1 h-3.5 w-3.5" /> 设为我的立案账号
                        </Button>
                      )}
                      <Button size="sm" variant="outline"
                              onClick={() => { setResetFor(resetFor === acc.id ? null : acc.id); setResetPw(''); }}>
                        <KeyRound className="mr-1 h-3.5 w-3.5" /> 重置密码
                      </Button>
                      <Button size="sm" variant={acc.is_active ? 'outline' : 'default'}
                              onClick={() => doToggle(acc)}>
                        {acc.is_active ? '停用' : '启用'}
                      </Button>
                    </div>
                    {resetFor === acc.id && (
                      <div className="mt-2 flex items-center justify-end gap-2">
                        <input
                          type="password"
                          value={resetPw}
                          onChange={(e) => setResetPw(e.target.value)}
                          placeholder="新密码（至少 6 位）"
                          aria-label={`重置 ${acc.username_masked} 的密码`}
                          className="h-8 w-44 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                        <Button size="sm" onClick={doResetPw}>确认</Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    暂无法院账号，点右上角「添加法院账号」
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        说明：「设为我的立案账号」后，你从本后台发起的所有立案运行都会用该账号登录法院平台；密码仅注入立案子进程，不回显、不写日志。
      </p>
    </div>
  );
}
