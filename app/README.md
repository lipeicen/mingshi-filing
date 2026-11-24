# 法院立案管理后台

法院自动立案工具的本地管理界面：案件数据上传入库、案件管理、发起立案（DRY RUN）、运行日志实时查看。

## 运行

```bash
npm install
npm run dev        # 同时启动 FastAPI 后端(8100)与 Vite 前端(默认 3000，可 -- --port 7100)
```

`npm run dev` 由 `scripts/dev.cjs` 拉起两个进程：CLI 参数（host/port）原样转发给 Vite；前端经 Vite 代理 `/api` 访问后端。

生产模式：`npm run build` 后，直接运行 `python server/api.py` 即可（FastAPI 托管 `dist/`）。

## 结构

```
app/
├── server/api.py        FastAPI 后端：直连 MySQL，复用工具链入库/立案脚本
├── server/run_logs/     立案运行日志（增量轮询）
├── scripts/dev.cjs      一键启动前后端
├── src/pages/           概览 / 案件管理 / 数据上传 / 立案运行
├── src/lib/api.ts       API 客户端
└── verify_ui.py         Playwright 界面回归验证脚本
```

## 后端接口

| 接口 | 说明 |
|---|---|
| `GET /api/stats` | 案件/代理人/材料统计、按状态与省份分布 |
| `GET /api/cases` | 案件列表（搜索/状态筛选/分页） |
| `GET /api/cases/{id}` | 案件详情（当事人/代理人/材料） |
| `PATCH /api/cases/{id}/status` | 修改案件状态 |
| `POST /api/cases/import` | 上传案件 JSON / Excel → 校验（必填字段、身份证校验位、材料文件存在性）→ 幂等入库；`?dry=1` 仅解析预览 |
| `GET /api/cases/template` | 下载 Excel 导入模板 |
| `POST /api/files/upload` | 批量上传材料文件（pdf/png/jpg ≤20MB）到 `documents/uploads/`，随带每份文件的类别（起诉状/身份证明/证据/委托书/送达地址确认书/其他），存入文件名→类别索引；Excel「材料文件」列按文件名引用时优先取索引类别 |
| `GET /api/files/list` / `DELETE /api/files/{name}` | 已上传材料列表（含类别）/ 删除材料 |
| `POST /api/filing/run` | 按案件 id 发起立案（`test_filing_flow.py --from-db`，DRY RUN） |
| `GET /api/filing/runs[/{id}[/log]]` | 运行记录 / 详情 / 增量日志 |
| `POST /api/filing/runs/{id}/cancel` | 终止运行 |

工具目录默认取 `../extracted`，可用环境变量 `COURT_TOOL_DIR` 覆盖；数据库连接读取该目录下 `.env`。

## 技术

React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui + Recharts；FastAPI + PyMySQL。
