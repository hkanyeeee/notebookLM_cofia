import { marked, type Token } from 'marked'
import katexExtension from 'marked-katex-extension'

// 配置 marked-katex-extension
marked.use(
  katexExtension({
    throwOnError: false,
    // 非标准分隔符（用于 $...$ 和 $$...$$）
    nonstandard: true
  })
)

marked.setOptions({
  gfm: true,
  breaks: true,
})

/**
 * 预处理数学公式：将 LaTeX 语法转换为 KaTeX 可识别的格式
 * 跳过代码块内容，仅处理非代码块片段
 */
export function preprocessMath(input: string): string {
  if (!input) return ''

  const codeFenceRegex = /```[\s\S]*?```/g
  let lastIndex = 0
  let result = ''
  let match: RegExpExecArray | null

  const transform = (text: string) => {
    // \[ ... \] -> $$ ... $$
    text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_m, p1) => `$$${p1}$$`)
    // \( ... \) -> $ ... $
    text = text.replace(/\\\(([^\n]*?)\\\)/g, (_m, p1) => `$${p1}$`)
    // 以单独一行 [ 开始、单独一行 ] 结束的显示公式块，转换为 $$...$$
    text = text.replace(/(^|\n)\[\s*\n([\s\S]*?)\n\]\s*(?=\n|$)/g, (_m, lead, body) => `${lead}$$${body}$$`)
    return text
  }

  while ((match = codeFenceRegex.exec(input)) !== null) {
    const segment = input.slice(lastIndex, match.index)
    result += transform(segment)
    result += match[0] // 保留代码块原样
    lastIndex = match.index + match[0].length
  }
  result += transform(input.slice(lastIndex))
  return result
}

/**
 * 将 Markdown 文本解析为 Token 数组
 */
export function lexMarkdown(input: string): Token[] {
  return marked.lexer(preprocessMath(input))
}

/**
 * 判断消息是否为状态消息
 */
export function isStatusMessage(content: string): boolean {
  const statusPatterns = [
    /正在思考\.\.\./,
    /搜索中\.\.\./,
    /再次思考中\.\.\./,
  ]
  return statusPatterns.some(pattern => pattern.test(content))
}

/**
 * 导出表格为 CSV
 */
export function exportTableToCSV(token: Token, id: string, tokenIdx: number): void {
  if (token.type !== 'table') return

  // 提取表头并转义 CSV
  const header = token.header.map((headerCell: any) => `"${headerCell.text.replace(/"/g, '""')}"`)

  // 提取行数据
  const rows = token.rows.map((row: any[]) =>
    row.map((cell: any) => {
      const cellContent = cell.tokens.map((token: Token) => token.text).join('')
      return `"${cellContent.replace(/"/g, '""')}"`
    })
  )

  // 组合表头和行
  const csvData = [header, ...rows]
  const csvContent = csvData.map((row) => row.join(',')).join('\n')

  // 添加 BOM 以支持 Unicode 字符
  const bom = '\uFEFF'
  const blob = new Blob([bom + csvContent], { type: 'text/csv;charset=UTF-8' })

  // 创建下载链接
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `table-${id}-${tokenIdx}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * 反转义 HTML 实体
 */
export function unescapeHtml(text: string): string {
  const htmlEntities: Record<string, string> = {
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&#39;': "'",
    '&#x27;': "'",
    '&#x2F;': '/',
  }
  return text.replace(/&(?:amp|lt|gt|quot|#39|#x27|#x2F);/g, (entity) => htmlEntities[entity] || entity)
}

