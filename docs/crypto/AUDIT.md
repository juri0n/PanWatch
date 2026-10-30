# PanWatch Crypto 源码与依赖审计

审计日期：2026-10-30（UTC+8）。实克隆 `https://github.com/TNT-Likely/PanWatch.git`，基线
`c4b7b2326e6861a3a8b0a3d81dad9c3ea398d677`，提交日期 2026-10-30 17:06:06 +0800。
本文件先于适配器实现编写。审计是针对基线的定向源码审阅，不是全仓安全认证。

## 已核实的源码事实

|证据文件 / 符号|发现与影响|
|---|---|
|`LICENSE`|MIT，版权 2026 sunxiao0721；保留原文。并不表示每个第三方依赖也是 MIT。|
|`requirements-runtime.txt`|多数依赖只有下界，无完整锁；TradingAgents 固定 v0.7.0 tag 而非 commit；5 个本地 editable 包。原生依赖安装、可重复构建、完整传递许可证需要另验。|
|`packages/marketdata/src/marketdata/registry.py:VENDOR_CLASSES_BY_TYPE`|供应商集中注册表可扩展，但没有第三方动态 crypto 插件发现机制。修改该表会形成上游冲突点。|
|`src/platform/marketdata/marketdata_client.py:get_market_data, md_stock_data`|现有配置提供器/缓存可以复用；`md_stock_data` 将市场转换成 MarketCode，不能直接传 CRYPTO。|
|`src/platform/marketdata/models.py:MarketCode, StockData`|只有 CN/HK/US；股票 volume 的单位为手，不能直接承接 CCXT 的 base volume。|
|`src/platform/marketdata/instruments.py:AssetType`|仅 stock/etf，加密币不能伪装成 US 股票。|
|`src/platform/persistence/models.py:Stock, Position`|quantity 为 Integer，价格多为浮点；小数币量需要独立 Decimal 语义与迁移，不能直接截断写入股票表。|
|`src/modules/automation/scheduling_policy.py:market_allowed`|股票交易日/交易时段门控。加密调度必须独立，不能全局绕过交易日判断。|
|`src/platform/scheduling/trading_calendar.py`|有界股票交易日历，未知年份拒绝授权自动执行；不能将 CRYPTO 添加为默认股票市场。|
|`src/modules/research/orchestration/{evidence,gateway,service,reporting}.py`|已有证据准备、模型网关、研究执行、报告和 outbox；推荐在证据准备之前分流，并复用后续流水线。|
|`packages/pan-investment-research/src/pan_investment_research/contracts.py`|Security key 支持 `CRYPTO:exchange:BASE/QUOTE`；quantity 是有限浮点，可以承接研究展示，但账本不能因此转 float。|
|`src/modules/automation/tradingagents/toolkit_adapter.py`|依赖 route_to_vendor monkeypatch，并非公开完整插件 SDK；crypto 不能未经测试放行到 yfinance。|
|`src/platform/marketdata/collectors/kline_collector.py`|已有 MACD/RSI/KDJ/ATR。RSI 为近 N 期简单平均，ATR 也是简单平均，不能宣传为 Wilder 指标。无需新增指标库。|
|`src/modules/paper_trading/paper_trading_engine.py`, `paper_settlement.py`|默认 A 股成本模型、一手 100、股票结算；直接复用会产生错误加密成交。先不开 crypto 模拟成交。|
|`src/platform/notifications/notifier.py`, research repository|已有 Telegram/Apprise 和交付状态，可复用；本次没有获授权的测试接收端，不发送真实通知。|
|`Dockerfile`, `.github/workflows/ci.yml`|Python 3.11 + Debian bookworm、Node 24.14.0、pnpm 9.15.9；已有后端全仓/包测试、前端构建。新功能应保留原 CI。|

## 依赖取舍（官方来源，开发分支信息不是发布版本承诺）

|组件|核实项|决定|
|---|---|---|
|[CCXT](https://github.com/ccxt/ccxt), [MIT](https://github.com/ccxt/ccxt/blob/master/LICENSE.txt), [PyPI](https://pypi.org/pypi/ccxt/json)|实际解析安装候选 4.5.91；公开统一 load_markets/fetch_ticker/fetch_ohlcv；有 Python 3.11/3.13 分类。包含真实下单/提现功能，所以绝不把原 exchange 暴露给 Agent。|唯一新增行情库，精确版本独立可选依赖；仅无密钥公开方法。必须校验真实安装/API，不能以 README 代替验证。|
|[Rotki](https://github.com/rotki/rotki/blob/develop/pyproject.toml), [许可证](https://github.com/rotki/rotki/blob/develop/LICENSE.md)|AGPLv3；当前 develop Python ==3.14.*；独立 Web3/加密 SQL 库和大量依赖。|不安装、不复制源码。未来若需税务/DeFi，评估固定发布版独立服务、认证 API、数据导出和许可证义务；本轮未部署/API 实测。|
|[Freqtrade](https://github.com/freqtrade/freqtrade/blob/develop/pyproject.toml), [许可证](https://github.com/freqtrade/freqtrade/blob/develop/LICENSE)|GPLv3；当前 develop Python >=3.12；已有 CCXT/TA-Lib/ft-pandas-ta 与 dry-run。|不嵌入主进程。模拟执行候选为隔离 dry-run 服务，必须禁止密钥与验证 dry_run 配置，接口和回放待测。|
|[ta](https://github.com/bukosabino/ta), [许可证](https://github.com/bukosabino/ta/blob/master/LICENSE)|MIT；pandas/numpy 指标库。|已有指标满足第一切片，不引入。当前维护活跃度/安装兼容未验证。|
|pandas-ta / VectorBT|未完成当前版本、许可证、维护者与兼容实测。|不引入；不得沿用前序聊天的推荐当审计结果。|
|[TradingAgents v0.7.0](https://github.com/TauricResearch/TradingAgents/blob/v0.7.0/LICENSE)|原有依赖 Apache-2.0，非 PanWatch 的 MIT；重用时保留相关许可/NOTICE。|不增新框架、不改上游 adapter，crypto 的真实模型适用性待验。|

官方源码查询可用，两个猜测的 CCXT pyproject URL 返回 404；以实际 wheel 元数据为准。安装和漏洞扫描结果记录在验收报告，不将“未发现”表述为无漏洞。

## 风险、资源与未验证项

首个切片新增 CCXT 及其传递库；不添加数据库服务、WebSocket 集群、回测平台。公共 REST 轮询按交易所复用单个限速实例，单任务串行、禁止重叠；实际内存/CPU/Unraid 硬件开销尚未测量，不给虚假 MB 数字。交易所可能限制地区/IP；失败不返回零价格，不跨交易所静默换价。USD 与 USDT 永不按 1:1 隐式换算。

未验证：全仓依赖安装/漏洞和 SBOM、全部股票 UI 回归、真实模型和真实 Telegram、所有交易所地域可达性、私有只读余额权限校验、Unraid 实机、Docker 构建/重启、备份恢复、同步 PR 实际运行。不能凭少量单测宣称上述通过。
