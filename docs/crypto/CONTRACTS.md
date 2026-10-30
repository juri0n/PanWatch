# Crypto 最小集成接口 v1

范围：固定数据与宿主连接边界，不提供另一套 Agent、报告、通知或交易引擎。实现集中在 `src/modules/crypto/contracts.py`、`research.py`，仅使用标准库和 PanWatch 已有研究包。独立 worker 不安装研究依赖；只有调用投影时才导入宿主包。

## 数据契约

|对象|必需内容|拒绝条件|
|---|---|---|
|Instrument|exchange + CCXT unified spot pair；key=`CRYPTO:okx:BTC/USDT`|未知交易所、小写/合约 pair、不支持的 quote currency|
|Holding|account_id + Instrument + quantity 十进制字符串|浮点数量、负数/非有限值、重复 account/instrument；跨账户可持有相同标的|
|Quote|沿用 adapter.Quote；Decimal price、source_ms、observed_ms|报价币种不匹配、未来/过期、重复或遗漏的标的|
|Snapshot|schema_version=1、asset_class=crypto_spot、market=CRYPTO、market_hours=24/7、带时区 as_of、positions|空持仓、可变集合、缺少时区、不完整报价；上限 100 持仓|

worker 保留原快照字段，并新增 `host_snapshot`，作为后续 API/UI/研究的统一入口。quantity/price/value 在 v1 输出为固定小数字符串，不用股票 Integer/手数。USD/USDT 不隐式换算。快照不声明成本基础、盈亏、余额或可交易资金。

字段 `capabilities` 固定仅 `market.read`、`portfolio.manual.read`；`unavailable_domains` 明确列出公司基本面、资金流、新闻、链上、成本基础、税务。添加未来能力需要明确版本/字段兼容测试，不能因为模型提出建议而升级权限。

## 宿主连接

1. 行情：`MarketReader` 与现有 SpotReader 相同的 quote/bars 调用；不给 Agent 原生 CCXT 客户端或任意方法调用。
2. 研究：`to_research_input(snapshot, run_id, language)` 直接构造仓库内实际 `pan_investment_research.ResearchInput`，不复制其 schema。证券唯一键含交易所，quote_expires_at 来源于交易所时间。其 Security 使用浮点数作为展示投影，精确数量和估值仍保留在 portfolio.crypto_snapshot 的字符串字段。
3. 模型与报告：后续把投影交给已有 InvestmentResearch、ResearchModelGateway、reporting；目前只完成输入契约兼容验证，没有调用真实模型。
4. 通知：`ReportDelivery` 仅约束现有 `NotifierManager.notify_with_result(title, content)` 的最小调用面。渠道设置、quiet hours、outbox、幂等、重试、送达确认全部由现有宿主实现，adapter 不自行发送。没有绕过静默时段的扩展参数。
5. HTTP/生命周期：后续在 `src/bootstrap/application.py` 注册经过原鉴权的 crypto router。不要新增第二个 FastAPI 工厂；不要通过修改股票 enum 把 crypto 塞进 CN/HK/US。server lifespan 的最小接线待实际实现时审阅。

## 兼容门槛

每次上游升级同时运行：独立数据边界测试、真实 ResearchInput JSON 往返验证、已有研究包测试、股票后端及前端测试。独立 worker 环境没有研究包时，宿主契约测试显式 skip；完整宿主 CI 必须安装原研究包并运行该测试。真实模型、Telegram、数据库迁移、UI 和部署依然需要后续验收，不能由契约测试推断通过。
