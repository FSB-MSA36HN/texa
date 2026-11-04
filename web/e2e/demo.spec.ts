import { expect, test } from '@playwright/test'

test('asks a question, displays the result table and inspectable SQL', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Hôm nay bạn muốn đo gì?' })).toBeVisible()
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()

  await expect(page.getByText('Kết quả kiểm thử:', { exact: false })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('table')).toBeVisible()
  await expect(page.getByRole('table')).toContainText('135')
  await page.getByRole('button', { name: /Chi tiết/ }).click()
  await expect(page.locator('pre code')).toContainText('analytics.event_activity')
  await page.screenshot({ path: '../.runtime/e2e-artifacts/demo-success.png', fullPage: true })
})

test('asks a clarification and completes the query after choosing a period', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Doanh thu')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByText(/Chọn|khoảng thời gian|thời kỳ/i).first()).toBeVisible({ timeout: 15_000 })

  await page.getByRole('button', { name: /Toàn bộ|Tất cả|all/i }).click()
  await page.getByRole('button', { name: 'Tính với lựa chọn này' }).click()
  await expect(page.getByRole('table')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('table')).toContainText('135')
})

test('carries relevant conversation memory into a follow-up', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByRole('table')).toContainText('135', { timeout: 15_000 })

  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Chia theo thiết bị')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  const table = page.getByRole('table').last()
  await expect(table).toContainText('mobile', { timeout: 15_000 })
  await expect(table).toContainText('100')
  await expect(table).toContainText('desktop')
})

test('handles a scripted model failure with retry', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Gây lỗi model')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByText(/thử lại|lỗi model|không thành công/i).first()).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Hỏi lại' }).last().click()
  await expect(page.getByRole('table')).toContainText('135', { timeout: 15_000 })
})

test('cancels a running request', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Chạy chậm')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await page.getByRole('button', { name: 'Dừng' }).click()
  await expect(page.getByText('Đã dừng câu hỏi này.')).toBeVisible({ timeout: 10_000 })
})

test('opens model settings without exposing a real credential', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Cài đặt model' }).click()
  await expect(page.getByRole('dialog', { name: 'Cài đặt' })).toBeVisible()
  await expect(page.getByText('Cài đặt model do người tổ chức quản lý.')).toBeVisible()
  await expect(page.getByRole('dialog').getByLabel(/API key/i)).toHaveCount(0)
})

test('keeps conversation history private between two browser sessions', async ({ browser }) => {
  const first = await browser.newContext()
  const second = await browser.newContext()
  try {
    const firstPage = await first.newPage()
    await firstPage.goto('/')
    await firstPage.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
    await firstPage.getByRole('button', { name: 'Gửi câu hỏi' }).click()
    await expect(firstPage.getByRole('table')).toContainText('135', { timeout: 15_000 })
    const firstList = await first.request.get('/api/conversations')
    expect(firstList.ok()).toBeTruthy()
    const firstConversations = await firstList.json() as { id: string }[]
    expect(firstConversations.length).toBeGreaterThan(0)

    const secondPage = await second.newPage()
    await secondPage.goto('/')
    const secondList = await second.request.get('/api/conversations')
    expect(secondList.ok()).toBeTruthy()
    expect(await secondList.json()).toEqual([])

    const crossSessionDelete = await second.request.delete(`/api/conversations/${firstConversations[0].id}`)
    expect(crossSessionDelete.status()).toBe(404)
  } finally {
    await first.close()
    await second.close()
  }
})

test('does not let a demo participant change the shared model connection', async ({ page }) => {
  await page.goto('/')
  const response = await page.request.put('/api/model-connection', {
    data: { provider: 'openai', allowed_models: ['not-a-real-model'], default_model: 'not-a-real-model' },
  })
  expect(response.status()).toBe(403)
})

test('reloads a saved conversation and restores its answer', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByRole('table')).toContainText('135', { timeout: 15_000 })
  await page.locator('nav[aria-label="Lịch sử"] button[title="Tổng doanh thu"]').click()
  await expect(page.getByRole('table')).toContainText('135')

  await page.reload()
  await page.locator('nav[aria-label="Lịch sử"] button[title="Tổng doanh thu"]').click()
  await expect(page.getByRole('table')).toContainText('135', { timeout: 15_000 })
  await expect(page.getByText('Kết quả kiểm thử:', { exact: false })).toBeVisible()
})

test('keeps a slow answer in its original conversation when starting a new one', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByRole('table')).toContainText('135', { timeout: 15_000 })
  const firstList = await page.request.get('/api/conversations')
  const firstConversationId = ((await firstList.json()) as { id: string }[])[0].id

  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Chạy chậm')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByRole('button', { name: 'Dừng' })).toBeVisible({ timeout: 5_000 })
  await page.getByRole('button', { name: 'Cuộc hỏi mới' }).click()
  await expect(page.getByRole('heading', { name: 'Hôm nay bạn muốn đo gì?' })).toBeVisible()
  await expect(page.getByText('Chạy chậm')).toHaveCount(0)

  await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
  await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
  await expect(page.getByRole('table')).toContainText('135', { timeout: 15_000 })
  await expect(page.getByText('Chạy chậm')).toHaveCount(0)

  await expect.poll(async () => {
    const response = await page.request.get(`/api/conversations/${firstConversationId}`)
    const conversation = await response.json() as { turns: { question: string; status: string }[] }
    return conversation.turns.find((turn) => turn.question === 'Chạy chậm')?.status
  }, { timeout: 12_000 }).toBe('answered')
  await expect(page.getByText('Chạy chậm')).toHaveCount(0)
})

test('serves eight independent classmates concurrently without mixing histories', async ({ browser }) => {
  const sessions = await Promise.all(Array.from({ length: 8 }, () => browser.newContext()))
  try {
    const pages = await Promise.all(sessions.map((context) => context.newPage()))
    await Promise.all(pages.map((page) => page.goto('/')))
    await Promise.all(pages.map(async (page) => {
      await page.getByRole('textbox', { name: 'Câu hỏi' }).fill('Tổng doanh thu')
      await page.getByRole('button', { name: 'Gửi câu hỏi' }).click()
    }))
    await Promise.all(pages.map((page) => expect(page.getByRole('table')).toContainText('135', { timeout: 30_000 })))

    const lists = await Promise.all(sessions.map(async (context) => {
      const response = await context.request.get('/api/conversations')
      expect(response.ok()).toBeTruthy()
      return await response.json() as { id: string }[]
    }))
    const ids = lists.map((list) => {
      expect(list).toHaveLength(1)
      return list[0].id
    })
    expect(new Set(ids).size).toBe(8)
  } finally {
    await Promise.all(sessions.map((context) => context.close()))
  }
})
