# 当前交付状态（2026-10-30）

已完成阶段 0 的定向审计、架构和文件级计划，并实施阶段 A 的独立只读数据切片。
**完整 Crypto MVP 尚未完成**：原 UI/AI Agent/报告/预警/Telegram 的 crypto 接线，以及 crypto 模拟交易仍在 B/C 计划中。本切片不修改原股票核心文件，不把“保留源码”写成“全功能回归通过”。

## 执行证据

|检查|实际结果|证据/命令|
|---|---|---|
|实际克隆/基线|PASS|`git clone https://github.com/TNT-Likely/PanWatch.git PanWatch`；HEAD `c4b7b2326e6861a3a8b0a3d81dad9c3ea398d677`。初次受限网络失败，授权网络访问后成功。|
|上游 remote / 分支|PASS|upstream 指向官方；功能分支 `feature/crypto-readonly-foundation`，没有把官方仓库作为扩展推送目标。|
|可选依赖安装|PASS|实际 CCXT 4.5.91、APScheduler 3.11.2、Python 3.13；通过官方 PyPI 分段下载并校验 SHA256，离线安装。Python 3.11/Linux 验证仍待 CI。|
|依赖一致性|PASS|`python -m pip check` 退出 0。|
|离线 Crypto 测试|PASS|`python -m pytest crypto_tests -q --basetemp=../work/pytest-final --junitxml=../outputs/crypto-tests.xml`；35 passed，退出 0。|
|上游架构回归|PASS（有限范围）|`python -m pytest --noconftest tests/test_architecture_boundaries.py -q -k 'not stock_list' ...`；7 passed、1 deselected。关闭全局 fixture 因它依赖完整应用环境；未执行涉及 stock_list 的依赖加载测试。|
|YAML 解析|PASS（语法级）|用 PyYAML 解析两份工作流和 compose；不等同 GitHub Actions/Docker 实际执行。|
|编译/差异空白检查|PASS|`python -m compileall -q src/modules/crypto scripts/crypto_backup.py crypto_tests`、`git diff --check`。|
|首次真实公共数据|FAIL|无显式代理时 OKX/Binance NetworkError，Kraken RequestTimeout；`public-smoke.json`。定位到 CCXT requests.trust_env 默认 false，直接 DNS 不可达。|
|修复后真实公共数据|部分通过|显式管理员 HTTPS 代理后 OKX/Binance BTC/USDT 报价和已收盘 1h K 线 PASS；Kraken BTC/USD K 线 PASS、报价 DataUnavailable。整体 smoke 退出 1，保留 `public-smoke-proxy.json`。|
|默认样例估值|PASS|`PANWATCH_CRYPTO_HTTPS_PROXY` 配置后运行 `python -m src.modules.crypto --config deploy/crypto/example.json --output ../outputs/demo-snapshot.json`，退出 0，OKX BTC/ETH 手工示例持仓按 USDT 估值。这里的持仓是演示值，不是用户真实资产。|
|漏洞扫描|修复后 PASS（有限范围）|初扫发现旧 pip 25.1.1 的 12 条漏洞记录（重复/别名，6 个唯一 ID）；升级 pip 到 26.2.2 后复扫退出 0，No known vulnerabilities found。范围仅隔离 Crypto/测试环境，不是完整 PanWatch，也不是无漏洞保证。|
|备份恢复|PASS（fixture 文件级）|含模拟 DB/WAL 文件往返、拒绝覆盖、路径穿越/校验失败拒绝；未运行真实 SQLite 或 Unraid 恢复演练。|

初轮 34 项测试中 2 个断言失败：误把字符串 exchange id 当原生客户端、误以为 CCXT public API 参数是字符串（实际为单元素列表）。修正这两个测试假设后 34 项通过；新增代理/.netrc 隔离测试后最终 35 项通过。没有将最初失败隐藏为首次全绿。

## 安全边界

- 无密钥构造 CCXT，只包装 load_markets/fetch_ticker/fetch_ohlcv；不提供任意方法、params、URL 或原生客户端给 Agent。
- JSON 配置只接受 exchange、interval_seconds、positions。下单、提现、私有余额、live 模式均未实现；代理只接受管理员环境变量。
- Python 属性封装不是执行恶意 Python 的安全沙箱；不得另行向 Agent 开放任意代码执行。
- 不伪造价格、source timestamp、USDT/USD 汇率；没有成本基础，不能称作精确盈亏或税务账本。
- 快照更新是原子替换；采集失败写 error，不保留貌似最新的成功估值。消费者仍需判定进程停机造成的 observed_at 过期。

## 未完成与后续门槛

1. 全股票后端/前端回归、真实 UI 验收：未执行。新增工作流保留这些门槛，须在完整依赖环境运行。
2. Crypto 的 UI、持仓持久化表、鉴权 API、研究证据/模型/报告/预警/outbox/Telegram：未接线，见 PLAN B。
3. Crypto 模拟盘：未实现；股票模拟盘仍保持原规则。Freqtrade dry-run 服务待固定版本和接口评估，无实盘后门。
4. 用户 fork/origin、PR 创建和每日自动同步：仅工作流准备完成，尚未远端启用；不声称已经有 PR。
5. Docker/Unraid 构建、CPU/内存、持久化重启、真实 DB 恢复、旧镜像+旧数据回滚：未验证。
6. 完整 PanWatch SBOM/第三方许可公告、全平台传递依赖锁与漏洞扫描：未完成。当前环境 freeze 是 Windows 3.13 的证据，不是 Linux 生产锁文件。
7. Kraken 缺失来源时间戳：严格拒绝，不用抓取时间冒充交易所时间；当前持仓监控采用已实测 OKX/Binance。

上述 B/C 与运维门槛完成前，不应部署为“完整 PanWatch Crypto 已验收版”。
