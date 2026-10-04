/** 思维导图公式预览回归测试：覆盖行内与块级公式的 SVG 显示。 */
import { expect, test } from '@playwright/test'

test('预览保留行内公式图形', async ({ page }) => {
  await page.goto('/#/tools/mindmap')

  const editor = page.getByRole('textbox', { name: 'Markdown 思维导图编辑器' })
  await expect(editor).toBeVisible()
  await editor.fill(`# 分层结构

## 实体

- 第 $n$ 层中的活动元素称为 **第$n$层实体**`)

  const formulas = page.locator('.mindmap-node-content svg.mindmap-formula')
  await expect(formulas).toHaveCount(2)
  await expect(formulas.locator('path').first()).toBeVisible()
})

test('预览显示附加的块级公式', async ({ page }) => {
  await page.goto('/#/tools/mindmap')

  const editor = page.getByRole('textbox', { name: 'Markdown 思维导图编辑器' })
  await expect(editor).toBeVisible()
  await editor.fill(String.raw`### PDU
- **协议数据单元**
- 对等实体之间传送的数据单位
$$
\text{PDU} = \text{PCI} + \text{SDU}
$$`)

  const formulas = page.locator('.mindmap-node-content svg.mindmap-formula')
  await expect(formulas).toHaveCount(1)
  await expect(formulas.locator('path').first()).toBeVisible()
})

test('粘贴 Markdown 后自动收起编辑器', async ({ page }) => {
  await page.goto('/#/tools/mindmap')

  const editor = page.getByRole('textbox', { name: 'Markdown 思维导图编辑器' })
  await expect(editor).toBeVisible()
  await editor.evaluate((element) => {
    const clipboardData = new DataTransfer()
    clipboardData.setData('text/plain', '# 粘贴的思维导图\\n- 节点')
    element.dispatchEvent(new ClipboardEvent('paste', {
      bubbles: true,
      cancelable: true,
      clipboardData,
    }))
  })

  await expect(editor).toBeHidden()
  await page.getByRole('button', { name: '显示编辑器' }).click()
  await expect(editor).toBeVisible()
})

test('双击节点进入编辑并支持提交和取消', async ({ page }) => {
  await page.goto('/#/tools/mindmap')

  const rootNode = page.getByRole('treeitem', { name: '思维导图', exact: true })
  await expect(rootNode).toBeVisible()
  await rootNode.dblclick()

  const editInput = page.getByRole('textbox', { name: '编辑节点文本' })
  await expect(editInput).toBeVisible()
  await editInput.fill('取消的修改')
  await editInput.press('Escape')
  await expect(rootNode).toBeVisible()

  await rootNode.dblclick()
  const reopenedInput = page.getByRole('textbox', { name: '编辑节点文本' })
  await expect(reopenedInput).toBeVisible()
  await reopenedInput.fill('更新后的主题')
  await reopenedInput.press('Enter')

  await expect(page.getByRole('treeitem', { name: '更新后的主题', exact: true })).toBeVisible()
})
