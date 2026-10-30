# 上游同步验证与远端启用

## 本地实现

`python scripts/crypto_sync.py --base HEAD --upstream upstream/main --output sync-result.json`

此命令不联网、不推送、不修改 refs/index/工作区；先由管理员 `git fetch upstream main`。Git 需支持 merge-tree --write-tree。候选提交时间/身份固定由父提交推导，同样输入重复运行得到相同 SHA，避免无意义反复更新 PR。

- unchanged：上游已包含在 base；退出 0，changed=false，不推送。
- ready：合并成功；退出 0，给出 candidate_sha，保留 base 和 upstream 两条父链。
- conflict：冲突；退出 2，candidate_sha=null，保留冲突路径，不发布带冲突的树。
- 无效 ref、Git 失败、无共同历史等：报错，不假装完成同步。

`crypto_tests/test_sync.py` 用真实临时 Git 仓库验证正常更新、确定性、再次同步无变化、冲突阻断、未提交工作不受影响、非法 ref。它证明本地合并逻辑，不证明 GitHub 权限/PR 创建成功。

## 远端流程

默认每天 UTC 02:23（UTC+8 10:23）及手动触发。官方仓库不运行此 fork 同步作业。

拉取官方 → 用同一脚本生成候选 → 显式 force-with-lease 更新专用 sync/upstream 分支 → 候选 SHA 写 pending → 只读权限运行 Crypto/股票/前端兼容检查 → 候选 SHA 写 success/failure → 成功才创建 PR。

只更新专用候选分支，不直接推送默认分支、不合并、不部署。冲突保留报告 artifact。GitHub token 产生的 push/PR 通常不会再触发普通 CI，所以这里显式调用兼容工作流，并单独给候选 SHA 写状态。测试作业不继承写权限或 secrets；写状态/开 PR 作业不运行候选源码。

依据：[Git merge-tree](https://git-scm.com/docs/git-merge-tree)、[GitHub commit statuses](https://docs.github.com/en/rest/commits/statuses)。工作流远端行为尚待真实账户验证。

## 远端准备与启用条件

用户已创建个人 fork https://github.com/juri0n/PanWatch ，已通过 GitHub 连接器核实账户与仓库写入权限。本地 origin 指向该 fork，upstream 保留官方地址；fork main 基线为 c4b7b2326e6861a3a8b0a3d81dad9c3ea398d677。正在发布本地功能分支并创建 PR；PR/Actions 实际结果另存交付证据，不预先声称成功。

定时同步工作流须经审核合入 fork 默认分支，且 Actions 具备创建 PR 所需权限后才能启用。发布功能分支不会自动完成这些步骤；本轮不自动合并或部署。此前网页操作阻碍是历史情况，不再作为 GitHub 账户连接或 fork 缺失的结论。

基础 PR #1 已经用户授权合并。补强后的普通仓库内 PR 和同步候选均写入同一个 `panwatch-crypto/upstream-compat` 提交状态，作为 main 的统一必需检查。普通 PR 的状态汇总作业等待两个 Python worker 测试、完整宿主回归和前端回归全部成功，不检出候选代码，只获 statuses:write 权限；有失败/取消/跳过时不能写成功。同步作业使用自身的独立状态写入作业，避免 GitHub token 创建 PR 不触发普通 CI 的问题。

main 保护应要求 PR、统一状态检查及合并前更新到最新 base，并禁止强推/删除及管理员绕过；不要求单人维护者无法满足的自我审批。外部 fork PR 没有提交状态写权限，因此保持阻断，需维护者将其导入仓库内分支并重新测试；不使用 pull_request_target 执行外部源码。不得通过关闭门槛绕过缺失状态。

不设置自动合并。测试、迁移复核、完整备份和回滚演练通过后才部署。
