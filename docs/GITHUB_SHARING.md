# 上传 GitHub

建议仓库名：`xianyu-ai-customer-service`。

建议描述：`闲鱼 AI 客服管理系统：多账号、商品知识库、人工接管、自动发货，支持 Mock 演示与实验性真实账号连接。`

项目使用 Apache-2.0，保留根目录 `LICENSE`、`NOTICE` 和 `THIRD_PARTY_NOTICES.md`。

## 方式一：上传整理后的源码包

1. 新建一个 Public 仓库。当前源码已经包含 README、LICENSE 和忽略规则，创建时无需让 GitHub 再生成这些文件。
2. 解压 `outputs/xianyu-ai-source.zip`。
3. 打开解压出的 `xianyu-ai-customer-service` 文件夹，将里面的源码文件和目录上传到仓库根目录，包括 `.github`、`.gitignore` 和 `.gitattributes`。
4. 不要只把 ZIP 作为仓库唯一文件：GitHub 需要源码才能展示 README 和执行 CI。ZIP 也可以作为后续 Release 的附件。

如网页上传限制文件数量，使用下面的 Git 方式。

## 方式二：通过 Git 推送当前项目

在项目根目录执行，将地址替换为你刚创建的空仓库地址：

```bash
git status --short
git add .
git diff --cached --stat
git commit -m "docs: prepare project for public sharing"
git branch --show-current
git remote add origin https://github.com/YOUR_USERNAME/xianyu-ai-customer-service.git
git push -u origin HEAD
```

`git add .` 会遵循项目忽略规则。提交前仍需检查暂存清单，确认没有真实账号信息。已有 `origin` 时先用 `git remote -v` 核对地址，无需再次添加。`HEAD` 会推送当前分支；推送后在 GitHub 设置里确认默认分支。

## 后续重新导出

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File tools/export-source.ps1 -OutputPath outputs/xianyu-ai-source-v2.zip
```

导出器使用 Git 的已跟踪和未忽略文件清单，包含尚未提交的项目修改。检测到已跟踪的私有文件或常见密钥格式会停止导出，只显示文件名。为了防止覆盖已有包，每次指定一个新的 ZIP 名称。格式扫描不能识别所有秘密，上传前仍需检查实际文件清单。

## 上传后的检查

- 仓库首页能显示 README，LICENSE 显示 Apache-2.0。
- Actions 中查看前后端 CI；本地验证结果不代替 GitHub 运行结果。
- 使用全新目录克隆仓库，按 README 执行 Mock 启动。
- 仓库没有 `.env`、本地数据库、`.runtime`、客户聊天记录、个人合同或卡密。
- 在仓库 Security 设置中启用私密漏洞报告；可以按需启用依赖更新与安全扫描。

源码分享不包含现有电脑上的账号、商品、知识、聊天数据和登录状态。新使用者从 Seed 演示数据开始，之后配置自己的账号和模型。
