import type { RunMeta } from './api';

export const RUN_STATUS_META: Record<
  RunMeta['status'],
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }
> = {
  running: { label: '运行中', variant: 'default' },
  success: { label: '已完成', variant: 'secondary' },
  failed: { label: '失败', variant: 'destructive' },
  cancelled: { label: '已取消', variant: 'outline' },
  interrupted: { label: '已中断', variant: 'outline' },
};

export const CASE_STATUS = [
  { value: 0, label: '待立案' },
  { value: 1, label: '已提交' },
  { value: 2, label: '已驳回' },
  { value: 9, label: '无需处理' },
];

export const CASE_STATUS_BADGE: Record<number, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  0: 'default',
  1: 'secondary',
  2: 'destructive',
  9: 'outline',
};

export const fmtAmount = (n: number) =>
  n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
