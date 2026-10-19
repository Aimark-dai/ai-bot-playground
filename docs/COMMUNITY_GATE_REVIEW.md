# 原生受保护 PR 合并：只读审核辅助，自动合入未完成

## 本版决策与现状

删除上一版 createCommitOnBranch 数据快照提交、写开关和所有写接口。程序只做 GET，输出 `manual-review-required`，绝不更新 main、发布成功检查、合并或关闭 PR。没有监听器、工作流或凭据配置。这不是已经完成的成员自助合入服务；本版提供安全审查辅助和最小人工过渡。

目标体验是成员通过 fork/分支提交自己的合规 JSON PR，管理员先人工审核并通过 GitHub 原生受保护合并；以后才由经过审核的可信检查与运营入口承接。成功合并后原 PR 应成为 merged，并核实实际 merge commit。建议使用原生 squash，避免把最终树未显示的中间提交内容带入 main 历史；本校验器只验证最终树，不审计所有历史提交。

## 最小人工过渡

1. 管理员独立检查并维护 main 的保护规则。若保护条件未验证，不执行合并，也不把本程序输出视作平台检查。此 PR 不设置或声称已经存在这些规则。
2. 成员提交 PR，并在自己的 PR 留言 `/merge-community <完整40位head SHA>`。当前没有监听器，管理员按队列人工处理。head 改变后必须重发精确 SHA 请求。
3. 从下述固定可信来源启动校验器，读取真实 PR/评论身份、当前 main 成员表和 schema，校验完整 base/head 树。输出记录 PR、评论、成员 ID、base/head SHA、三个 policy blob SHA、文件 blob 和大小，不输出数据正文。
4. 管理员审阅精确 head 的完整 diff、成员资格、JSON 文本及输出。临近合并时重新读取 PR/base/评论并重跑；任何 head、base、成员表、schema、校验器变化都必须重新审核。程序最后也重读，但输出只是某时刻观察，不能提供之后的事务保证。
5. 仅在 GitHub 严格必需检查、审批及禁止绕过规则实际满足时，使用原生 squash 合并。若通过 API，显式传该次审阅的完整 head `sha`；不要用不带 SHA 的合并请求。不得强推、直接写 main、使用 admin bypass 或放松保护来通过。
6. 核实 PR `merged=true` 和 merge commit；排队/接受请求不是合并成功。失败重新核查原因，超时或结果不明先读 PR/远端状态，不盲目重复提交。新 head 或新 base 是新审核，不重放旧“通过”结果。

这仍需要管理员处理，不能声称普通成员已有 Merge 权限或自动监听。人工复查缩小竞态窗口，但不能代替平台强制约束。

## 自动化前必须实现并实测的平台契约

- main 要求 PR、审核和严格必需检查 `community-data-policy`；检查必须绑定指定可信 GitHub App 来源，不接受 any source。同名成功检查不能由外来代码或一般写权限主体替代。规则适用于实际合并主体，禁止 bypass、force push 和删除；维护 policy 的管理流程也必须受审查。不要给成员整库 collaborator/write 权限。
- 可信检查发布者必须对**精确 PR head SHA**重新执行本校验，输出记录 base SHA、policy blob SHA、PR 编号及作者 ID。报告文本中的 SHA 不是平台强制绑定；check/status 必须确实附着到该 SHA。当前程序没有实现发布者。
- strict up-to-date 使 main 前进后旧 head 不能直接合并。更新 head 后重新取当前 main policy、重新校验并在新 SHA 上发布结果；不能复用先前 base/policy 的绿色检查。main push、PR synchronize/reopen、成员资格或请求变化均需重新处理。不得用 skipped/neutral 代替成功资格校验；失败和缺失检查必须阻断。检查发布前再复核状态，定期修复遗漏事件。
- 同一 head SHA 的检查可被多个 PR 使用，不能把仅附着 SHA 的结果误认为 GitHub 同时绑定了 PR 作者/评论。未来发布者和合并入口必须核实 PR 关联及精确请求，拒绝模糊或跨 PR 重用；在此问题实测解决前不启用自助合并。
- 合并入口使用平台原生接口，传完整 `sha`，没有绕过资格。它不等于“先 GET 检查全绿，再自行写 refs”。本文选择 strict 分支更新流程，不实现 merge queue。若以后选择队列，必须支持 merge_group 的临时 SHA/队列基线验证、可信来源和最终状态查询，不能直接复用 PR-head 检查。

## 平台限制与尚未完成的保证

原生合并的 `sha` 条件绑定 head，不提供 expected base SHA / policy SHA / 评论版本的联合 CAS。严格检查依赖平台保护规则、无绕过主体和可信发布者；本地 JSON 报告不能替代这些。当前程序没有读取/验证保护配置，也没有检查发布者或合并执行器，所以**不能独立安全地自动合并**。

评论删除、PR 状态或成员身份外部状态在最后读取后仍可能改变。通过 main 修改成员资格的撤销可结合 strict 更新要求使旧 head 失效，但即时评论撤销不与 merge 事务绑定。若产品要求所有这些状态都原子取消在途合并，现有简单合并接口不能承诺；保持人工流程，另行评估平台能力，不追加未经审查的复杂账本系统。

目前没有实测本仓库规则、检查来源防伪或合并接口竞态行为。启用前需在明确批准环境验证：旧 head 被拒、base/policy 前进后旧绿灯阻断、新 head 必须新检、伪造来源拒绝、同 SHA 跨 PR 不继承身份授权、无 bypass、结果不明时只查询，以及成功后原 PR merged 状态。任何一项不成立都维持人工待审。

## 校验与执行边界

保留真实数字 user ID、approved 名册（最多500席）、login 改名需管理员核对、精确 SHA 评论、固定公开仓库 ID、完整未截断树、blob 哈希和大小校验。只准自己 `community/submissions/u<ID>/<小写记录名>.json` 的新增/修改；拒绝删除、其他目录、策略/代码/workflow、symlink/gitlink/执行位、路径穿越。最多20文件、每文件16 KiB、总计128 KiB。JSON严格限定字段和类型，拒绝重复键、非法编码、非有限值。

JSON 文本永远只是数据。正则过滤主动内容标记只是附加限制，不是执行沙箱、LLM沙箱或提示注入防护；消费者不得执行内容、插入HTML，或把正文当权限指令。无 LLM 参与授权。

**启动前信任由外部保证。** 自身 blob 与 main 比对发生在 Python imports 之后，只能检测策略版本漂移，不能证明恶意 checkout 启动安全。操作者必须先在进程外核对独立审核的固定提交及文件哈希，把单文件置于仅管理员可写的可信目录；使用可信 Python 3.9+ 和干净临时工作目录，以 `python3 -I /trusted/path/community_gate.py --pr N --comment ID` 启动。`-I` 隔离脚本目录、用户 site 与 PYTHONPATH 的导入影响，仍不能把恶意脚本本身变可信。禁止从 PR checkout 启动、导入、测试或恢复其缓存/artifact；不要将 PR 中的模块放入可信目录。测试文件也必须先独立审查，测试会执行 Python。

## 权限与验证证据

当前只读公开数据可匿名访问（受速率限制）；如使用既有凭据，限目标仓库 Metadata/Contents/Pull requests 读取，以及评论所需 Issues 或 Pull requests 读取能力。本轮未读取或配置凭据。

未来检查发布者需限定本仓库的 Checks write 与上述读取权限；如选择 commit status 则需 Commit statuses write，二者不要无理由同时授予。原生合并运营主体按 GitHub API 需 Contents write，但不给成员、不让 PR 代码接触、不给规则 bypass。管理员配置保护需仓库管理权限，运行器不需 Administration write。精确安装权限及实际端点响应需启用前确认；本 PR 不增加任何权限。

50 项离线测试通过，使用假 API 固定响应验证本地拒绝规则和报告绑定；HTTP传输测试确认只发 GET 且拒绝 GraphQL/写参数。没有把这些测试算作 GitHub 集成验证。原 Fake CAS 曾把冲突直接抛 Rejected，而真实 GraphQL 路径会归类为 uncertain，二者并不一致：本版删除整个写适配器及 Fake CAS 测试，不再声称模拟或验证服务端原子合并。删除的成功案例不能算进本版测试数。

```sh
python3 -I -m unittest discover -s tests -v
python3 -I -m py_compile tools/community_gate.py tests/test_community_gate.py
```

官方依据：[原生合并接口、sha 与权限](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)、[strict 必需检查与指定 App 来源](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。自动化部署需另行独立审核。
