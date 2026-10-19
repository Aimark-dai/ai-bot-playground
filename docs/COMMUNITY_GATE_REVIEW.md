# 受限社区数据提交器：待审核，未启用

本 PR 提供可执行程序和离线攻击测试，不提供工作流，不更改成员表、schema、安全配置或凭据。默认只读；尚未在 GitHub 执行真实写入。合入本开发 PR 本身也不会启动服务。

## 成员体验与明确的语义

批准成员在自己的 PR 下留言 `/merge-community <完整40位head SHA>`，表示请求提交这个**确切快照**。将来受信任运营入口只传 PR 编号和评论 ID；程序从 GitHub API 重取真实身份，不接受正文宣称的身份。当前这条命令还没有监听器，发出评论不会自动执行。

这是“将经过校验的数据内容提交到 main”，不是 GitHub 原生整库写权限，也不是普通 Merge 按钮：它不引入 PR 历史，不更改 PR 状态，不自动关闭 PR。成功返回 `snapshot-applied-pr-left-open` 及提交 SHA，管理员再核对 PR 是否还有后续修改。提交作者是运行凭据所属主体，提交说明记录来源 PR、评论 ID、成员 ID 和 head SHA。

若产品要求“任何并发 head 变化都必须取消”或“原生 PR merged 状态”，本版本不能满足，不能据此宣称已实现。请先独立审查这一快照语义。

## 确定性边界

- 固定公开仓库名称、数字 repository ID、main 分支；禁止跨仓请求与 HTTP 重定向。
- approved 名册从当前 main 读取，数字 user.id 对应 `u<id>`；login 改名需管理员核对，回收同名账号不继承资格。名册最多 500 席，重复 ID、席位、login 或错误 slug 均拒绝。
- 请求评论必须属于该 PR，其真实 User ID 必须等于 PR 作者 ID；PR 必须 open、非 draft，且请求正文精确包含当前 head SHA。
- 比较完整、未截断的 base/head Git trees，而不是补丁摘要或 PR 文件列表第一页。head 必须包含当前 base。限制树条目及响应大小；失败即拒绝。
- 只新增/修改自己的 `community/submissions/u<id>/<小写记录名>.json`。最多 20 文件、每文件 16 KiB、合计 128 KiB。禁止删除/改名、其他成员目录、成员表、workflow、代码、schema、异常目录、symlink、gitlink、可执行模式和路径穿越。
- 从固定 blob SHA 拉取并校验 Git blob 哈希、大小及 UTF-8；不 checkout、import、执行或安装 PR 内容。成员 JSON 仅允许 version/bot/title/body，重复键、非有限数及不符合 schema 的值拒绝。当前 schema 验证规则改变后，程序拒绝，须复审。
- 正在运行的单文件程序必须与当前 main 中 `tools/community_gate.py` 的 blob 完全相同，防止旧校验器继续写入。只从可信 checkout 启动；不要在 PR checkout 中启动，即使只是运行测试。
- JSON 不解决提示注入。文本永远只是数据，不成为授权指令，不调用 LLM 判定权限。主动内容标记过滤是额外约束，不承诺识别所有伪装代码。后续消费者必须保持纯文本展示，不执行内容或插入 HTML。

## 并发与不确定结果

校验固定 head 的字节，最后重读 PR、评论、身份及 main。可见的 head/base/评论变化会拒绝。随后使用 `createCommitOnBranch(expectedHeadOid=校验时main)`，在服务端创建只含获准文件的提交并更新分支。main 上任何成员撤销、schema/校验器更新或另一提交使 CAS 失败；不自动重试。

在最后读取之后，PR head 或评论可能再次变化：GitHub 没有这个 API 与 PR/comment 状态的联合事务。本版本仍最多写入**此前明确请求的旧 SHA 数据**，绝不会跟随新 head 引入新内容；保留 PR 打开，不宣称它整体已 merged。评论撤销/关闭 PR 同样不能保证在最后读取之后立即撤销在途请求；管理员提交名册撤销会受 main CAS 约束。若需要严格在途取消，另行设计 main 上的请求账本及原子撤销协议。

任何写请求超时、异常、GraphQL 错误或畸形回执都标为 `uncertain`，禁止盲目重试；人工检查 main 的审计提交与内容。读取失败不会发起写入。重复请求不会自动重复导入：base 前进后旧 head 不再满足当前基线；须重新准备新的 PR/请求。

## 审核后才可运行

Python 3.9+，仅标准库，无依赖安装。离线验证：

```sh
python3 -m unittest discover -s tests -v
```

待程序获审核进入 main 后，可在干净受信任 checkout 中只读验证指定真实 PR/评论：

```sh
python3 tools/community_gate.py --pr PR_NUMBER --comment COMMENT_ID
```

显式写开关为 `--apply-reviewed-snapshot`，**本轮未执行**。它只读取运行环境已有的 `GITHUB_TOKEN`，不创建、打印或管理 token。当前没有提供该凭据或配置任何运行器。启用时由管理员独立确认适用于该仓库的短期凭据与 Contents write、读取 PR/评论能力，以及 main 规则能否允许此数据提交；不得为通过测试而绕过保护规则或扩大权限。无需给成员写 token，也不需要向成员开放 collaborator write。

## 本轮证据与剩余限制

56 项离线测试通过：授权身份、改名/回收、500 上限、完整树、路径、模式、blob 篡改、JSON 攻击、超限、提示注入、head/base/评论变化、晚到策略撤销的 CAS、晚到恶意 head 只能提交旧数据、网络失败及不确定写入不重试。API 是响应形状相同的假服务；没有把 mock 结果当真实 GitHub 集成验证。

仍需独立审查代码、确认快照语义、在明确批准的测试环境验证实际 API/权限/CAS 拒绝行为，再决定运行入口、审计及告警。没有自动入口、写工作流、定时运行、密钥或额外权限随本 PR 启用。

参考：[GitHub createCommitOnBranch / expectedHeadOid](https://docs.github.com/en/graphql/reference/commits#createcommitonbranchinput)、[CommittableBranch 与 FileChanges](https://docs.github.com/en/graphql/reference/git#committablebranch)。
