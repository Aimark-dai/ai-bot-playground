# 待审 Actions 原生合并模板：尚未启用

## 交付与当前状态

`tools/community_gate.py` 保持只读策略校验。新增 `tools/community_actions.py` 作为可信 main 的运行入口，以及 **`docs/examples/community-merge.workflow.yml`**。模板不在 `.github/workflows`，不会被 GitHub 自动运行。本轮没有启用 Actions、创建环境/凭据、修改权限/保护规则或合并 main。没有真实集成测试，不宣称成员自助合入已经上线。

不再需要独立 GitHub App 服务、账户或长期 token。未来运行只使用每个 job 的临时 `GITHUB_TOKEN`。原来的 createCommitOnBranch 快照写入路径已删除；正常成功结果是 GitHub 原生 squash merge，原 PR 为 merged。

## 两个 job 的职责

1. `issue_comment: created` 仅从默认分支取工作流。模板先按目标仓库、PR 评论及命令前缀过滤；这些条件只是节流，不授予权限。脚本从 `GITHUB_EVENT_PATH` 读取 JSON，只把 PR/评论 ID 当定位线索，再从 API 重取身份和请求内容。正文不插值到 shell。
2. 只读 validate job 在 GitHub 托管的一次性 runner 上 checkout **事件的 main `github.sha`**，从不 checkout PR head/merge ref。不保存 Git 凭据，不取 submodule/LFS，不安装依赖。`python3 -I` 执行可信策略；令牌仅 Contents/Pull requests read。
3. 写 job 在独立新 runner 上重复同样的可信 main checkout，经过 `community-merge-review` 环境的管理员审批后，**重新执行完整策略验证**，不接收上一个 job 的证据 artifact，也不因同名 check 绿灯跳过授权。源提交必须等于当前 main；main 前进则拒绝，成员更新 PR 后发新请求。
4. 写 job 将固定 `community-data-policy` success status 发布到刚验证的**精确 head SHA**，然后再次读取身份、请求、head/base，最后只调用一次原生 `PUT /pulls/N/merge`，固定 `merge_method=squash` 和完整 `sha`。无 update-ref、force push、直接内容提交或 bypass 参数。
5. 必须收到有效 merge receipt，并重读 PR 确认 `merged=true`、`merge_commit_sha` 一致，才报告 merged。已 merged 的重复事件只读退出，不把他人的合并归功于自己。

issue_comment job 的默认运行状态属于 main，不能作为 PR head 的资格检查。显式发布 head status 才用于严格分支保护。GitHub Actions App 身份不唯一对应 workflow，固定 context/source 也不能证明是哪段代码产生结果；本方案的合并 job 必须自行校验全部策略。其他可信管理员/自动化也不得仅凭这个绿灯认定成员请求获授权。禁止另外启用原生 auto-merge 或其他消费该 status 的自动合并器来绕开这条路径。

## 必须由管理员先建立的部署前提

本程序仅从普通分支 API 检查 `protected=true` 及当前 SHA，**没有证明 strict、禁止 bypass、force push 等具体设置**。Get branch protection API 文档要求 Administration read，而工作流的 GITHUB_TOKEN permissions 不提供该管理权限；不为此申请新凭据或扩大权限。完整配置须由管理员在启用前及每次环境审批时核实，不能把仓库变量当作证明。

- main 必须要求 PR、至少一位可信审批者、过期审批失效、严格必需状态检查（Require branches to be up to date）。将 `community-data-policy` 配置为 required context，来源绑定 GitHub Actions（这只是附加约束，不替代运行器验证）。不得设置成 loose，也不能只要求 issue_comment job 名称。
- 对实际 GITHUB_TOKEN 合并主体及管理员执行保护规则，没有 bypass；禁止 force push、删除 main 和直接推送。成员没有整库 write。其他工作流不得以外来代码获得 contents/statuses write。维护成员表、schema、校验器及工作流本身的管理流程必须独立审核。
- 创建 `community-merge-review` environment，限制仅 main，并配置独立管理员 required reviewer；禁止审批绕过。先核实环境保护有效，再设置仓库变量 `COMMUNITY_MERGE_ENABLED=reviewed`。不存在的 environment 可能被自动创建且无保护，所以只写 environment 名称不足够。该版本是**半自动合并**：每次环境管理员审批加 PR 审批，不是成员无人值守合并。
- 禁止仓库自动合并和其他自动消费者，否则写 job 最后复查前或失败后残留的 success status 可能被其他流程使用。启用时检查当前 PR 没有遗留自动合并请求。

在这些前提未被证明、平台不支持环境保护或保护拒绝 GITHUB_TOKEN 合并时，保留人工原生 squash merge 过渡；不要用 admin merge、取消检查或创建 PAT 来跑通。

## 最小权限与启用顺序

| 部分 | 权限 | 用途 |
| --- | --- | --- |
| 工作流全局 | `{}` | 无默认授权 |
| validate job | contents: read、pull-requests: read | 读取可信 main、PR、评论及 blobs |
| merge job | contents: write、statuses: write、pull-requests: read | 原生 squash merge、固定 head status、重新校验 |

PR 评论读取使用 pull-requests:read，不授予多余 issues:read。不需 checks write、pull-requests write、actions write、Administration、id-token 或秘密配置。只使用 GitHub 自带临时令牌；不给成员凭据。checkout 固定到审核过的官方 action commit，`persist-credentials:false`；写 job 的 action 也属于可信计算边界，启用前重审固定版本，不用浮动 tag。

启用由管理员另行完成：独立审核固定代码 → 建立上述保护、环境审批与禁止绕过前提 → 在获准测试场景验证临时 token 读写能力和所有竞态/拒绝案例 → 将模板复制到 `.github/workflows` 并通过受审 PR 合入 → 配置 required context（必要时在禁用写 job 状态安全引入该 context） → 最后设置 enable 变量。若平台要求检查先出现才能选择，使用规则设置界面允许的 context 输入或另行审核的引导流程，不绕过保护。没有在本轮执行这些步骤。

## base、policy、重放与响应不确定

每次运行都要求 PR head 包含当前 main，校验 runner 的 blob 与当前 main 一致；Actions adapter 也验证自己的 blob，且事件可信源码 SHA 必须等于 main。head/base、成员表、schema、源代码发生变化都需重新准备 PR/命令，不复用旧策略。原生 merge 的 `sha` 条件拒绝 late head 变化；base/policy 的晚到变化依赖服务端 **strict up-to-date 且不可绕过**，不是本地 GET 与 merge 的联合事务。

评论撤销和身份外部状态在最后读取后仍可能变化，没有联合 CAS；精确 SHA 请求无法保证严格取消所有在途请求。若必须提供即时原子撤销，本模板不满足。main 上的资格撤销依靠 strict 规则阻断旧 head，前提是禁止回退/force push。

同 SHA status 可在多个 PR 复用，因此写 job 不信任 status 本身，而是重新验证本次 PR 作者、评论 ID/真实用户 ID、成员身份及完整差异，再以明确 PR 编号合并。若其他自动化仅看 status，此保证失效。

工作流不设全局 concurrency。无关评论被 validate 的 job 条件过滤，身份/策略不合格请求在只读阶段失败；merge 仅在 `needs.validate.result == success` 且启用变量满足时才进入固定的写 job concurrency group，`cancel-in-progress:false`。无关事件和验证失败请求不能挤占该组。已验证的合法请求之间仍不保证 FIFO，pending 写 job 可能被后来的已验证请求替换；环境审批等待与 concurrency 的实际调度需实测。这是保守串行化，不是持久队列，也不提供 exactly-once。成员看到未处理请求时由管理员检查后重新请求。`GITHUB_RUN_ATTEMPT != 1` 拒绝写，避免把 Re-run 当自动重试。串行化不覆盖其他 workflow 或管理员操作，服务端保护仍必需。

明确的原生 merge HTTP 403/404/405/409/422 归为拒绝，不重试；网络超时、5xx、异常/畸形 receipt、成功后的确认失败归为 uncertain，不盲重试。status 发布不确定时根本不尝试 merge。管理员必须检查 PR/merge commit/运行日志；未确认前不审批新请求。新 comment 不是绕过不确定结果调查的方式。重复事件在 PR 已 merged 时只读退出；没有声称分布式 exactly-once。

## 数据和启动信任边界

继续验证真实数字 user ID、approved 名册（最多500席）、login 格式、去重和匹配统一按小写比较，保留原始字段；真正改名需管理员核对、精确 SHA 评论、固定公开仓库 ID、完整未截断树、blob 哈希及大小。只准自己 `community/submissions/u<ID>/<小写记录名>.json` 的新增/修改；拒绝删除、其他目录、策略/代码/workflow、symlink/gitlink/执行位和路径穿越。最多20文件、每文件16 KiB、总计128 KiB。JSON严格限定字段类型，拒绝重复键、非法编码、非有限值。最终树审核不包含中间历史，所以选 squash。

外来内容只经 API 取作数据，不 checkout/import/test/eval/install，不下载 PR artifact/cache。JSON正文不成为授权指令，正则只是附加过滤，不是执行或LLM沙箱；后续消费者不得执行文本或插入HTML。

自身 blob 校验发生在 imports 之后，只能发现版本漂移，不能使恶意代码安全。本方案信任**受保护 main 上的工作流和事件固定 main 提交**，用隔离新 runner、可信 Python `-I`、显式同目录导入已受信任的 gate；`-I` 不是脚本本身的沙箱。不要把 ref 改成 PR head、使用外来 action/local action 或把 PR 内容放入可信源码目录。审核和测试文件本身先经过独立审查。

## 验证证据与启用前验收

81 项离线测试通过，Python编译检查通过。测试覆盖授权/路径/完整树/内容攻击，以及事件身份、可信 source、adapter 漂移、成员撤销、重复事件、重新运行阻断、写 job 复验、固定 status SHA、status后 head变化、精确 squash 请求、HTTP拒绝、超时/畸形回执不重试、PR最终状态确认。Fake 只记录请求，**不模拟服务端 strict/CAS 或权限有效性**；旧 Fake CAS 及GraphQL写路径已经删除。

真实 GitHub Actions、环境审批、临时 token、strict 分支规则、status context 及合并竞态均未集成验证。所有真实验收仍待执行，至少包括：无关 issue_comment、格式不符及身份/策略校验失败不占写 job 并发组、不取消合法 pending；多个已验证请求的 pending 替换和环境审批等待行为按文档处理、不假设 FIFO；去除 issues:read 后临时 token 仍能读取 PR 评论；环境无审批或 PR 缺少审批不能写；关闭所有其他 auto-merge/status 消费者，失败后残留 success 不触发合并；管理员实际核实 strict/no-bypass/禁止force push，不能只看 protected=true；伪造同名绿灯不能绕过写 job；late head、late base/policy 被平台阻断；force push/bypass 被禁止；403/405不放松规则；响应不确定只查询；同 SHA 不继承其他 PR 身份；合法请求 squash 后原 PR merged。任一失败维持未启用/人工流程。

```sh
python3 -I -m unittest discover -s tests -v
python3 -I -m py_compile tools/community_gate.py tools/community_actions.py tests/test_community_gate.py tests/test_community_actions.py
```

官方依据：[issue_comment 的默认分支语义](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issue_comment)、[原生 merge SHA 与权限](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)、[commit status](https://docs.github.com/en/rest/commits/statuses#create-a-commit-status)、[strict 分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[保护配置读取权限](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection)、[环境保护](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。
