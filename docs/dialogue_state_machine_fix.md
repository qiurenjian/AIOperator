# 对话状态机修复说明

## 修复内容

### 问题
根据用户反馈，系统存在以下问题：
1. "需求列表"被误判为需求提交，触发澄清流程
2. "介绍一下这个项目"等讨论请求被误判为查询
3. "梳理当前项目结构"被误判为查询而非讨论

### 根本原因
意图识别的关键词优先级错误：
- 查询关键词（包含"当前"）优先级高于讨论关键词
- "梳理当前项目"中的"当前"触发了查询匹配

### 修复方案
调整 `apps/ingress/intent_analyzer.py` 中的关键词优先级：

1. **DISCUSSION关键词检查移到最前（0级优先级）**
   - 关键词：分析、评估、梳理、介绍、建议、方案、优化、改进、探讨、讨论
   - 这些词明确表示用户想要讨论/分析，而非查询具体数据

2. **QUERY关键词优先级降为1级**
   - 移除"当前"关键词（避免误判"梳理当前项目"）
   - 保留：列表、查询、显示、查看、进度、状态、详情、有哪些

3. **CONFIRMATION保持2级优先级**

### 测试结果

**修复前**：16/17通过
- ❌ "梳理当前项目的整体结构" 被误判为QUERY

**修复后**：17/17通过 ✅
- ✅ "需求列表" → QUERY
- ✅ "梳理当前项目的整体结构" → DISCUSSION
- ✅ "介绍一下这个项目" → DISCUSSION
- ✅ "实现用户登录功能" → REQUIREMENT

## 部署步骤

### 1. 备份当前代码
```bash
cd /Users/renjianqiu/projects/AIOperator
git add .
git commit -m "backup before dialogue state machine fix"
```

### 2. 应用修复
修改已完成，文件：
- `apps/ingress/intent_analyzer.py`

### 3. 重启服务

**本地测试**：
```bash
source .venv/bin/activate
python test_intent_recognition.py  # 验证意图识别
python test_dialogue_flow.py       # 验证状态机流程
```

**云端部署**：
```bash
# 推送代码
git add apps/ingress/intent_analyzer.py
git commit -m "fix: adjust intent recognition priority - DISCUSSION before QUERY"
git push origin main

# SSH到服务器
ssh user@your-server

# 拉取最新代码
cd /path/to/AIOperator
git pull origin main

# 重启feishu-connector服务
docker-compose restart feishu-connector

# 查看日志确认启动成功
docker-compose logs -f feishu-connector
```

### 4. 验证部署

在飞书中测试以下场景：

**测试1：查询功能**
```
用户: 需求列表
预期: 返回需求列表（不触发澄清）
```

**测试2：讨论功能**
```
用户: 介绍一下这个项目
预期: 进入DISCUSSING状态，机器人询问项目信息
```

**测试3：需求提交**
```
用户: 实现用户登录功能
预期: 进入CLARIFYING状态，开始澄清需求
```

**测试4：混合场景**
```
用户: 切换到 healthassit
系统: ✅ 已切换到项目: healthassit

用户: 需求列表
预期: 返回healthassit项目的需求列表

用户: 介绍一下这个项目具体做什么的
预期: 进入DISCUSSING状态，介绍项目
```

## 监控指标

部署后监控以下指标（建议观察24小时）：

1. **意图识别准确率**
   - 查询类消息是否正确返回查询结果
   - 讨论类消息是否进入DISCUSSING状态
   - 需求类消息是否进入CLARIFYING状态

2. **误判率**
   - 查询被误判为需求的次数
   - 讨论被误判为查询的次数

3. **用户反馈**
   - 用户是否仍然抱怨"系统太死板"
   - 用户是否能够自然地进行讨论

## 回滚方案

如果出现问题，快速回滚：

```bash
# 方案1：Git回滚
git revert HEAD
git push origin main
docker-compose restart feishu-connector

# 方案2：恢复备份
git reset --hard <backup_commit_hash>
git push -f origin main
docker-compose restart feishu-connector
```

## 后续优化建议

1. **添加更多测试用例**
   - 收集真实用户对话
   - 扩展test_intent_recognition.py

2. **意图识别日志**
   - 记录所有意图识别结果
   - 分析误判模式

3. **动态调整关键词**
   - 根据用户反馈调整关键词列表
   - 考虑使用机器学习模型

4. **上下文理解增强**
   - 当前只看最近5条消息
   - 可以增加到10条，提升上下文理解

## 相关文档

- 技术方案：`docs/dialogue_state_machine_proposal.md`
- 部署指南：`docs/dialogue_state_machine_deployment.md`
- 测试脚本：`test_intent_recognition.py`, `test_dialogue_flow.py`
