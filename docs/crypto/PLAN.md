# 架构、文件计划与验收门槛

## 架构决策

```text
保留的 PanWatch 股票 UI/API/DB/日历/模拟盘
                 （原路径保持隔离）
独立 crypto adapter → CCXT 无凭证公共 REST
    ├─ exchange + unified spot pair + UTC + Decimal
    ├─ 手工现货持仓（按报价币种分别估值）
    └─ APScheduler 24/7 → 原子快照（失败写状态，不伪造成功）
后续：crypto API/UI → 证据适配 → 已有研究 runtime / 报告 / outbox / Telegram
后续：独立 dry-run 服务 → 模拟成交（与研究建议隔离）
```

先做 A，A 的结果可独立验收后才进入 B/C。A 是数据地基，不是完整 Crypto 产品。所有阶段禁止实盘和提现；不存在 live 开关。

## 文件级计划

|阶段|新增 / 修改文件|行为、冲突风险|
|---|---|---|
|0 审计|`docs/crypto/{AUDIT,PLAN}.md`|记录 commit/来源/事实/限制，零核心冲突。|
|A 数据地基|`src/modules/crypto/{__init__,adapter,portfolio,__main__}.py`|独立只读适配、UTC 时效、Decimal 手工现货估值、CLI 与 24/7 采集；不注册到股票接口。|
|A 测试|`crypto_tests/test_readonly.py`|脱离全仓 autouse fixtures，使用真实 CCXT 对象的假 HTTP 方法；另行真实公共接口 smoke。|
|A 部署|`requirements-crypto.txt`, `deploy/crypto/{Dockerfile,compose.yaml,example.json}`|隔离 worker 可选启用，单向读取配置、持久化快照；上游主 Dockerfile 不改。|
|A 维护|`.github/workflows/crypto-{compat,upstream-sync}.yml`, `scripts/crypto_backup.py`|只建同步候选 PR、不自动部署；备份/检查恢复包。必须 fork 和启用 Actions 后方可实际开 PR。|
|B 产品接线|crypto 下新增 `api.py`, `models.py`, `alerts.py`；`research.py` 已提供契约投影；装配注册集中到 `src/bootstrap/application.py`，生命周期接线待检查 server lifespan|独立表使用 Decimal 字符串/NUMERIC、唯一键含交易所；沿用鉴权/CSRF/通知策略；装配入口冲突风险中。先确认既有迁移机制。|
|B 原有研究|`src/modules/research/orchestration/evidence.py` 或新增 crypto evidence adapter|复用 ResearchInput、ResearchModelGateway、InvestmentResearch、reporting、outbox。明确缺少链上/基本面/资金流，crypto 24/7，不编造股票财报；测试并发隔离。核心冲突风险中高。|
|B UI|`frontend/src/pages/Crypto.tsx` + 共享路由/API/i18n 注册|独立 crypto 页面，不扩大股票 enum；读 UI_GUIDELINES 后再实现；小数数量、报价币种、来源和过期状态。|
|C 模拟盘|`deploy/crypto-paper/` 与 `src/modules/crypto/paper_bridge.py`|评估固定发布版 Freqtrade dry-run API，无密钥容器、独立账本，复用其成交/费用引擎，不自写交易平台。若服务过重先交付只读，不假装已有 crypto 模拟盘。|

## 业务验收标准

|编号|门槛|阶段|
|---|---|---|
|A1|实际安装固定 CCXT，允许的 exchange 上确认 unified pair 的 spot 标记；拒绝合约、未知 pair、无效配置；不接收密钥/URL/任意 params。|A|
|A2|报价含交易所、pair、quote currency、UTC source/observed time；缺失/未来/过期时间及 NaN/Inf/非正价格失败；HTTP 故障不产生成功快照。|A|
|A3|K 线含原始毫秒时间，排除未收盘线；拒绝倒序/重复/非法 OHLCV；不使用股票“手”单位。|A|
|A4|0.00000001 等小数持仓不截断；USD 与 USDT 各自汇总；没有行情的持仓明确失败，不静默少算资产。|A|
|A5|周六、周日、UTC 午夜均可调度；单交易所限速、超时、coalesce、max_instances=1；重启可重读配置与上次状态。|A|
|A6|真实公开行情 smoke 与离线 fixture 测试分列；没有访问私有 endpoint、下单或提现。|A|
|B1|原股票/ETF 完整后端与前端 CI 通过，股票 UI 人工流程通过；crypto 数量精度和交易所区分有 API/UI 证据。|B|
|B2|真实 AI 运行产生正确标注缺失数据的 crypto 报告；预算/失败/取消可恢复，Telegram 在获授权的接收端实际送达。|B|
|B3|预警去重、冷却、每日上限、跨 UTC 日期、故障重试与 stale 拒绝有测试。|B|
|C1|模拟买/卖支持小数、手续费/滑点/最小金额、余额约束、幂等与重启；没有交易密钥，dry-run 不可能切换 live。|C|
|O1|upstream remote 保留；定时同步创建 PR；冲突阻止候选分支；兼容 CI 是必需状态检查，未测试不得合并。|运维|
|O2|Unraid appdata 绑定目录，重启数据保留；停服务备份、恢复到独立目录检查、用旧镜像+旧数据回滚演练。|运维|

## 上游升级与回滚策略

本地 upstream 保留官方地址，origin 已指向用户创建并核实的 juri0n/PanWatch fork；扩展发布到 fork 的功能分支。同步工作流默认仅在 fork 运行，使用固定 TNT-Likely/PanWatch main，合并进 sync/upstream 候选，开到 fork 默认分支。冲突使工作流失败；候选 PR 不自动合并。GitHub token 创建的 PR 通常不会触发其它 workflow，因此同步工作流自身也调用兼容检查；正式使用仍需在 fork 配置分支保护及完整回归 required checks。历史阶段报告中的“尚无 fork”描述仅反映当时状态。

后续补强：`scripts/crypto_sync.py` 使用 Git merge-tree 生成确定的候选对象，不切换分支或修改工作区；没有上游变化不推送。有冲突退出 2、没有候选 SHA。同步工作流将 `panwatch-crypto/upstream-compat` 的 pending/success/failure 状态明确写到候选 SHA，避免测试检出目标与检查所属提交错位。状态写入与测试执行分为不同作业，测试作业只有 contents:read。

部署前固定镜像 digest/版本，不使用 latest；停止写入进程后备份整个 appdata（含数据库 WAL 等），保留旧镜像 digest 和源码 commit。升级先用备份副本跑迁移/验收；失败停止新容器、恢复旧数据到独立目录、旧镜像指向恢复目录。数据库 schema 有迁移时不能只回退镜像。备份包含敏感配置，存储权限与异地加密由部署者设置。
