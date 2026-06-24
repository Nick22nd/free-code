# Alma Memory Demo — Memory Index

这个目录是 `alma-memory-demo` 的 project-scoped 持久记忆，与主 Agent 的 Auto Memory 彼此隔离。

## Topics

- [user_preferences.md](user_preferences.md)：Nick 的稳定个人偏好；回答“我喜欢什么”一类问题前读取。
- [collaboration_style.md](collaboration_style.md)：与 Nick 协作时适合采用的表达和执行方式。

## Memory Policy

- 只保存跨任务仍有价值的稳定事实、偏好和协作经验。
- 不保存密码、令牌、隐私原文或未经确认的推测。
- 用户给出更新信息时，以最新明确陈述为准并修正对应 topic。
- 保持本索引简短；具体内容放在 topic 文件中。
