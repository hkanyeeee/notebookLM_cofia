# 向量数据修复工具使用指南

## 概述

`fix_vector_data.py` 是一个通用的向量数据库数据修复脚本，基于原有的 `fix_collection6_embeddings.py` 扩展而来，支持修复指定集合或全部集合的向量数据。

## 主要功能

- ✅ **指定集合修复**：修复单个指定的集合
- ✅ **批量修复**：自动扫描并修复所有需要修复的集合
- ✅ **状态检查**：列出所有集合的状态
- ✅ **验证功能**：验证集合的向量数据完整性
- ✅ **强制重新生成**：可强制重新生成已存在的向量数据
- ✅ **预览模式**：支持 dry-run 模式预览操作
- ✅ **详细统计**：提供详细的处理统计信息

## 使用方法

### 基本语法

```bash
python fix_vector_data.py --session-id <SESSION_ID> [选项]
```

### 命令行参数

| 参数 | 类型 | 必需 | 描述 |
|------|------|------|------|
| `--session-id` | string | 是 | Session ID，用于标识数据会话 |
| `--collection-id` | int | 否 | 指定要修复的集合ID |
| `--all` | flag | 否 | 修复所有需要修复的集合 |
| `--list` | flag | 否 | 列出所有集合状态 |
| `--verify` | int | 否 | 验证指定集合的状态 |
| `--force` | flag | 否 | 强制重新生成所有向量数据 |
| `--dry-run` | flag | 否 | 仅预览操作，不实际执行 |

### 使用示例

#### 1. 列出所有集合状态

```bash
python fix_vector_data.py --session-id "your_session_id" --list
```

输出示例：
```
=== 扫描所有集合 ===
✅ 找到 5 个集合

=== 集合状态详情 ===
✅ ✓ ID: 1, 标题: 文档A, Chunks: 150, 向量: 150
❌ 🔧 ID: 6, 标题: 文档B, Chunks: 200, 向量: 0
✅ ✓ ID: 7, 标题: 文档C, Chunks: 100, 向量: 100
```

#### 2. 修复指定集合

```bash
python fix_vector_data.py --session-id "your_session_id" --collection-id 6
```

#### 3. 修复所有需要修复的集合

```bash
python fix_vector_data.py --session-id "your_session_id" --all
```

#### 4. 验证集合状态

```bash
python fix_vector_data.py --session-id "your_session_id" --verify 6
```

输出示例：
```
=== 验证Collection 6 ===
数据库chunks: 200
Qdrant向量: 200
状态: complete

前3条记录预览:
  1. Point 12345: 这是一段文档内容...
  2. Point 12346: 另一段文档内容...
  3. Point 12347: 更多文档内容...
```

#### 5. 强制重新生成（预览模式）

```bash
python fix_vector_data.py --session-id "your_session_id" --all --force --dry-run
```

## 状态说明

### 集合状态图标

- ✅ **已有向量数据**
- ❌ **缺少向量数据**
- 🔧 **需要修复**
- ✓ **状态正常**

### 验证状态

- `complete`：向量数据完整
- `missing`：完全缺少向量数据
- `partial`：部分向量数据缺失
- `error`：验证过程中出错
- `unknown`：未知状态

## 工作流程

### 1. 扫描阶段
- 连接数据库获取所有集合信息
- 检查每个集合的 chunks 数量
- 查询 Qdrant 中对应的向量数据数量
- 确定哪些集合需要修复

### 2. 修复阶段
- 分批处理 chunks（默认批次大小：4）
- 调用 embedding 服务生成向量
- 将向量数据存储到 Qdrant
- 实时显示处理进度

### 3. 验证阶段
- 对比数据库和向量数据库的数据量
- 检查数据完整性
- 显示处理统计信息

## 配置说明

脚本使用以下配置（来自 `app/config.py`）：

- **批次大小**：`EMBEDDING_BATCH_SIZE`（默认：4）
- **向量维度**：`EMBEDDING_DIMENSIONS`（默认：1024）
- **嵌入模型**：`DEFAULT_EMBEDDING_MODEL`（默认：Qwen/Qwen3-Embedding-0.6B）
- **集合名称**：`QDRANT_COLLECTION_NAME`（默认：notebooklm_prod）

## 注意事项

1. **Session ID**：必须提供正确的 session ID，否则无法找到对应的数据
2. **权限要求**：确保有数据库和 Qdrant 的访问权限
3. **资源消耗**：修复大量数据时会消耗较多计算资源
4. **中断处理**：支持 Ctrl+C 中断操作，已处理的数据不会丢失
5. **错误恢复**：单个批次失败不会影响其他批次的处理

## 故障排除

### 常见问题

1. **集合不存在**
   ```
   错误：Collection X 不存在
   解决：检查 collection_id 和 session_id 是否正确
   ```

2. **Qdrant 连接失败**
   ```
   错误：Qdrant client is not available
   解决：检查 QDRANT_URL 和 QDRANT_API_KEY 配置
   ```

3. **Embedding 服务错误**
   ```
   错误：批次 X embedding生成失败
   解决：检查 EMBEDDING_SERVICE_URL 和网络连接
   ```

### 调试模式

使用 `--dry-run` 参数可以预览操作而不实际执行：

```bash
python fix_vector_data.py --session-id "your_session_id" --all --dry-run
```

## 扩展功能

如果需要添加更多功能，可以：

1. **添加新的命令行参数**
2. **修改批次处理逻辑**
3. **增加更多的验证规则**
4. **支持不同的 embedding 模型**
5. **添加进度条显示**

## 对比原有脚本

| 功能 | 原脚本 `fix_collection6_embeddings.py` | 新脚本 `fix_vector_data.py` |
|------|------------------------------------|---------------------------|
| 支持集合数量 | 仅支持 Collection 6 | 支持任意数量的集合 |
| 操作模式 | 仅修复模式 | 修复、验证、列表等多种模式 |
| 错误处理 | 基础错误处理 | 完善的错误处理和统计 |
| 用户交互 | 无命令行参数 | 丰富的命令行参数支持 |
| 验证功能 | 基础验证 | 详细的状态验证和统计 |
| 灵活性 | 硬编码参数 | 可配置的参数和选项 |

这个新脚本完全向后兼容原有功能，同时提供了更强大的功能和更好的用户体验。
