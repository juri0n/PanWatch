# 只读数据切片运行与交接

本切片是独立 worker，尚未连接 PanWatch 界面/AI/预警/模拟盘。不会读股票数据库，不接收 API key，只读取公开数据和手工现货持仓。行情严格要求交易所 timestamp；没有时间戳的交易所 ticker 会失败，不用本机抓取时间冒充 source time。

## 本地

在仓库根目录用 Python 3.11+：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-crypto.txt pytest
.venv/Scripts/python -m pytest crypto_tests -q
.venv/Scripts/python -m src.modules.crypto --config deploy/crypto/example.json --output data/crypto/snapshot.json
# 持续运行：追加 --watch；Ctrl+C 停止。配置修改后重启 worker。
```

Linux 使用 `.venv/bin/python`。允许 kraken/binance/okx，但不承诺所有地区都能连接；默认 OKX BTC/USDT、ETH/USDT。本轮实际 Kraken K 线通过，但 ticker 缺少 timestamp 被严格拒绝，不适合作为当前持仓报价源。仅 USD/USDT 报价，不把二者合并。JSON quantity 必须是十进制字符串。失败快照 status=error，没有持仓估值；消费者仍应检查 observed_at 防止读取停机留下的旧快照。输出路径不得与配置相同。

若网络必须经过代理，显式设置 `PANWATCH_CRYPTO_HTTPS_PROXY` 为管理员配置的 HTTP/HTTPS 代理。使用 CCXT 原生 httpsProxy；不自动读取交易所密钥、.netrc 或任意 Agent 参数，不记录代理地址。不要在容器中使用只对宿主有效的 127.0.0.1 代理地址。

## Unraid Compose（配置已提供，实机未验）

1. 创建 `/mnt/user/appdata/panwatch-crypto/config` 和 `data`，由 Unraid nobody:users（99:100）拥有，data 可写。
2. 将 example.json 复制为 config/positions.json，再填自己的**手工**现货持仓。不要填密钥或交易权限。
3. 设置 `CRYPTO_CONFIG_DIR=/mnt/user/appdata/panwatch-crypto/config`、`CRYPTO_DATA_DIR=/mnt/user/appdata/panwatch-crypto/data`。
4. 仓库根目录执行 `docker compose -f deploy/crypto/compose.yaml up -d --build`。主股票容器继续使用原配置，不共享其数据库。
5. 检查 snapshot.json 的 status、observed_at 与报价。执行 restart 后核对配置及上次快照保留；断网后检查 error 状态，恢复网络后自动重试。

生产发布需要构建、测试后固定镜像 digest；示例 `local` tag 只是本机构建标签。无 HTTP 端口，无 Docker socket；不包含 PanWatch 登录/API 服务。

## 备份恢复（停止所有写入者后）

```text
python scripts/crypto_backup.py backup /path/appdata /path/backups/dated.zip --stopped-confirmed
python scripts/crypto_backup.py verify /path/backups/dated.zip
python scripts/crypto_backup.py restore /path/backups/dated.zip /path/new-recovery
```

脚本要求显式确认已停写，不能自己证明服务已停止。逐文件 SHA256 用于完整性校验，不是加密/签名。恢复只允许新目录；备份应放在源目录外。示例测试证明文件往返，不代表 SQLite/Unraid 实机恢复完成。原股票库升级需备份整个股票 appdata，与 crypto 分别管理。回滚使用旧镜像 digest 和旧数据副本，两者缺一不可。

## 同步

已配置本地 upstream；用户 fork `juri0n/PanWatch` 和本地 origin 已核实，功能分支发布与 PR 验证进行中。工作流须合入 fork 的默认分支、启用 Actions 写入及创建 PR 权限，再配置 required checks，才会每日检查官方 main。工作流不自动合并、不发布镜像、不部署。正常同步和冲突阻断已有本地 Git 演练；远端同步 PR 和部署回滚仍待验证。
