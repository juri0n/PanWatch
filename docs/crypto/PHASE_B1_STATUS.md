# 同步验证与最小集成接口交付

2026-10-30，承接阶段 A。本轮范围为优先步骤 1/2：验证可安全同步的机制，并固定宿主连接接口。不是完整 Crypto UI/AI 产品交付。

## 本轮改动

- 新增 scripts/crypto_sync.py：用真正 Git merge-tree 生成候选提交对象；不改变当前分支、refs、index 或未提交文件。相同父提交生成相同候选 SHA，无新上游提交则无操作；冲突返回 2 且没有候选。
- 补强同步工作流：执行同一本地脚本，兼容结果以 pending/success/failure 明确绑定候选 SHA；写状态、候选发布、测试执行和 PR 创建作业分离。无变化不推送；冲突不发布；失败不新建 PR；不自动合并或部署。
- 新增 contracts.py/research.py：统一包含交易所的标的身份、账户持仓、小数字符串、时效与数据缺口；直接构造真实 pan_investment_research.ResearchInput。worker 增加 host_snapshot，原字段保留。
- 复用原通知入口的最小协议，不实现另一套发送/重试/报告引擎。将后续 HTTP 装配入口纠正为 src/bootstrap/application.py；本轮没有修改该入口或股票核心。

## 验收结果

|检查|结果|证据|
|---|---|---|
|Crypto 数据/契约/同步测试|PASS，48 项|boundary-tests.xml；含 4 项真正 Git 演练与真实宿主 schema JSON 往返；没有 schema 替身。|
|已有研究包回归|PASS，63 项|host-research-tests.xml；脚本模型、真实图运行，不调用外部 AI。|
|真实上游拉取|PASS|git fetch upstream main；仍为 c4b7b2326e6861a3a8b0a3d81dad9c3ea398d677，没有晚于原审计基线的提交。|
|真实仓库同步检查|PASS，无变化|upstream-local.json；changed=false/status=unchanged，未推送。正常新更新与冲突另由真实临时 Git 仓库演练。|
|真实公开数据接口|PASS|boundary-demo.json，默认 OKX BTC/ETH × 示例手工持仓输出 schema_version=1 宿主快照；不是用户真实资产。|
|依赖一致性/漏洞扫描|PASS（限定范围）|pip check；boundary-vulnerability-audit.json 无已知漏洞。测试环境新增的是 PanWatch 原本已有的研究包及其传递依赖；独立 worker 依赖文件未变。|
|工作流 YAML/编译/空白检查|PASS（语法级）|PyYAML、compileall、git diff --check；不等于 GitHub 实际运行。|
|fork/远端同步 PR/分支保护|未完成|已核实 GitHub 账户连接 juri0n；juri0n/PanWatch 查询 404，没有可用 fork。连接器无 fork 工具。浏览器登录/URL 校验阻碍，电脑操作已停止；本地 Git 无已有 GitHub 登录。|

初轮新增契约测试暴露数量字符串为 1E-8，已将 v1 输出改为固定小数，并限制极端零指数，防止格式化造成异常资源消耗；最终 48 项全部通过。研究包最初两次本地运行在 Windows asyncio 自连接初始化处停滞并中止；诊断堆栈指向 socket.accept/_fallback_socketpair。允许本机回环的执行环境中 63 项在 6.49 秒通过，没有修改上游研究代码或缩减测试。

## 仍未验证/未实施

远端 Actions 权限、候选 SHA 状态写入、实际 PR 创建及必需检查配置；完整股票前后端回归；Crypto 登录 API/UI、真实模型、报告持久化/outbox/Telegram、预警；模拟盘；Docker/Unraid 实机与真实数据库回滚。没有交易密钥、实盘下单或提现入口。

## 下一步

需要先在 GitHub 为 juri0n 创建官方 PanWatch 的 fork；之后可用已连接工具发布功能分支和 PR，再验证远端流水线。网页路径为 https://github.com/TNT-Likely/PanWatch/fork 。这一步是外部能力/登录阻碍，不是缺少对本地开发的授权。

接口冻结详见 CONTRACTS.md；同步设计和启用条件详见 SYNC.md。进入 UI/AI 闭环时继续只做最小宿主注册与 crypto 模块内适配，不扩大股票市场枚举。
