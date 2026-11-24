import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { api, type Stats, type RunMeta } from '@/lib/api';
import { RUN_STATUS_META } from '@/lib/constants';

const STATUS_COLORS: Record<string, string> = {
  待立案: 'hsl(38, 92%, 45%)',
  已提交: 'hsl(150, 60%, 38%)',
  已驳回: 'hsl(0, 72%, 45%)',
  无需处理: 'hsl(220, 10%, 55%)',
};

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    Promise.all([api.stats(), api.runs()])
      .then(([s, r]) => { setStats(s); setRuns(r.items.slice(0, 6)); })
      .catch((e) => setErr(String(e.message || e)));
  }, []);

  if (err) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
        无法连接后端服务：{err}。请确认 API 服务已启动（npm run dev 会自动拉起）。
      </div>
    );
  }
  if (!stats) {
    return <div className="grid grid-cols-4 gap-4">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28" />)}</div>;
  }

  const pieData = Object.entries(stats.by_status).map(([name, value]) => ({ name, value }));
  const cards = [
    { label: '案件总数', value: stats.total, suffix: '件' },
    { label: '待立案', value: stats.by_status['待立案'] ?? 0, suffix: '件', accent: true },
    { label: '覆盖省份', value: stats.provinces, suffix: '个' },
    { label: '材料 / 代理人', value: `${stats.files} / ${stats.agents}`, suffix: '' },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">概览</h1>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.label} className={c.accent ? 'border-l-4 border-l-[hsl(6,60%,42%)]' : ''}>
            <CardHeader className="pb-1 pt-4">
              <CardTitle className="text-sm font-normal text-muted-foreground">{c.label}</CardTitle>
            </CardHeader>
            <CardContent className="pb-4">
              <span className="tnum text-3xl font-semibold">{c.value}</span>
              {c.suffix && <span className="ml-1 text-sm text-muted-foreground">{c.suffix}</span>}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">案件状态分布</CardTitle></CardHeader>
          <CardContent className="h-64">
            {pieData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85}
                       label={(p) => `${p.name} ${p.value}`} fontSize={12}>
                    {pieData.map((d) => <Cell key={d.name} fill={STATUS_COLORS[d.name] ?? 'hsl(220,10%,60%)'} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            ) : <p className="text-sm text-muted-foreground">暂无案件数据</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">各省份案件量</CardTitle></CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.by_province} layout="vertical" margin={{ left: 8, right: 24 }}>
                <XAxis type="number" allowDecimals={false} fontSize={12} />
                <YAxis type="category" dataKey="province" width={64} fontSize={12} />
                <Tooltip />
                <Bar dataKey="count" fill="hsl(224, 45%, 30%)" radius={[0, 3, 3, 0]} barSize={16} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">最近立案运行</CardTitle>
          <Link to="/runs" className="text-sm text-primary underline-offset-4 hover:underline">查看全部</Link>
        </CardHeader>
        <CardContent>
          {runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">还没有运行记录，去「案件管理」勾选案件发起立案。</p>
          ) : (
            <ul className="divide-y">
              {runs.map((r) => {
                const m = RUN_STATUS_META[r.status];
                return (
                  <li key={r.id} className="flex items-center gap-4 py-2.5 text-sm">
                    <Badge variant={m.variant}>{m.label}</Badge>
                    <span className="tnum text-muted-foreground">{r.started_at}</span>
                    <span className="truncate">{r.case_nos.join('、')}</span>
                    <span className="ml-auto text-muted-foreground">{r.case_nos.length} 案</span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
