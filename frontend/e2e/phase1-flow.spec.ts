import { test, expect } from '@playwright/test'

/**
 * Phase 1 End-to-End Flow
 *
 * Validates the complete Phase 1 clinical workflow:
 *   login → create subject → enter data → submit → create/answer query → CSV export
 *
 * Validates: Requirements 26.1
 *
 * Prerequisites:
 * - Full stack running (frontend on :5173, backend on :8000, PostgreSQL)
 * - Database seeded with:
 *   - A test user (testuser@example.com / password123) with Site Coordinator role
 *   - A study in Active status with a published version
 *   - A site assigned to the test user
 *   - At least one visit definition with a form containing text/date/numeric fields
 */
test.describe('Phase 1 Clinical Flow', () => {
  // Shared state across sequential steps
  let subjectId: string

  test.describe.configure({ mode: 'serial' })

  test('Step 1: Login with valid credentials', async ({ page }) => {
    await page.goto('/login')

    // Fill login form
    await page.getByPlaceholder('Email').fill('testuser@example.com')
    await page.getByPlaceholder('Password').fill('password123')
    await page.getByRole('button', { name: 'Sign In' }).click()

    // Should redirect to dashboard after successful login
    await page.waitForURL('/')
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })

  test('Step 2: Navigate to Subjects and create a new subject', async ({ page }) => {
    await page.goto('/')

    // Navigate to subjects list
    await page.getByRole('link', { name: /subjects/i }).click()
    await expect(page.getByRole('heading', { name: 'Subjects' })).toBeVisible()

    // Open create subject dialog/form
    await page.getByRole('button', { name: /create|add|new/i }).click()

    // Fill subject creation form — site should be pre-selected or selectable
    await page.getByLabel(/site/i).selectOption({ index: 0 })

    // Submit creation
    await page.getByRole('button', { name: /create|save|submit/i }).click()

    // Verify subject was created — capture the subject identifier for later steps
    await expect(page.getByText(/subject.*created/i)).toBeVisible({ timeout: 10_000 })

    // Store the generated subject ID from the page (shown after creation)
    const subjectLink = page.getByRole('link', { name: /SUBJ-|S-/ }).first()
    subjectId = (await subjectLink.textContent()) ?? ''
    expect(subjectId).toBeTruthy()
  })

  test('Step 3: Open casebook and enter data in a form', async ({ page }) => {
    // Navigate to the subject's casebook
    await page.goto('/')
    await page.getByRole('link', { name: /subjects/i }).click()
    await page.getByRole('link', { name: subjectId }).click()

    // Should show casebook with visits and forms
    await expect(page.getByText(/casebook|visits/i)).toBeVisible()

    // Open the first available form (e.g., Demographics or Visit Date)
    await page.getByRole('link', { name: /demographics|visit date/i }).first().click()

    // Fill form fields
    await page.getByLabel(/date/i).first().fill('2025-01-15')

    // For text fields, fill a value
    const textInputs = page.locator('input[type="text"]')
    if ((await textInputs.count()) > 0) {
      await textInputs.first().fill('Test data entry')
    }

    // For numeric fields, fill a numeric value
    const numberInputs = page.locator('input[type="number"]')
    if ((await numberInputs.count()) > 0) {
      await numberInputs.first().fill('72')
    }

    // Save as draft first
    await page.getByRole('button', { name: /save/i }).click()
    await expect(page.getByText(/saved|in progress/i)).toBeVisible({ timeout: 10_000 })
  })

  test('Step 4: Submit the form', async ({ page }) => {
    // Navigate back to the form (in case of page reload)
    await page.goto('/')
    await page.getByRole('link', { name: /subjects/i }).click()
    await page.getByRole('link', { name: subjectId }).click()
    await page.getByRole('link', { name: /demographics|visit date/i }).first().click()

    // Submit the form
    await page.getByRole('button', { name: /submit/i }).click()

    // Confirm submission if there's a confirmation dialog
    const confirmButton = page.getByRole('button', { name: /confirm|yes/i })
    if (await confirmButton.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await confirmButton.click()
    }

    // Verify status changed to Submitted
    await expect(page.getByText(/submitted/i)).toBeVisible({ timeout: 10_000 })
  })

  test('Step 5: Create a query on the submitted form', async ({ page }) => {
    // Navigate to queries section
    await page.goto('/')
    await page.getByRole('link', { name: /queries/i }).click()
    await expect(page.getByRole('heading', { name: /queries/i })).toBeVisible()

    // Create a new query
    await page.getByRole('button', { name: /create|new|open/i }).click()

    // Fill query details
    await page.getByLabel(/subject/i).selectOption({ label: subjectId })

    // Select the target form/field
    const formSelect = page.getByLabel(/form/i)
    if (await formSelect.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await formSelect.selectOption({ index: 0 })
    }

    // Enter query text
    await page.getByLabel(/message|text|description/i).fill(
      'Please verify the date entered — appears outside visit window.'
    )

    // Submit the query
    await page.getByRole('button', { name: /create|submit|send/i }).click()
    await expect(page.getByText(/query.*created|open/i)).toBeVisible({ timeout: 10_000 })
  })

  test('Step 6: Answer the query (site response)', async ({ page }) => {
    // Navigate to queries list
    await page.goto('/')
    await page.getByRole('link', { name: /queries/i }).click()

    // Open the query we just created
    await page.getByRole('link', { name: /verify the date/i }).first().click()

    // Verify query is in Open status
    await expect(page.getByText(/open/i)).toBeVisible()

    // Enter response
    await page.getByLabel(/response|message|reply/i).fill(
      'Confirmed with source documents — date is correct per patient chart.'
    )

    // Submit response
    await page.getByRole('button', { name: /respond|reply|submit/i }).click()

    // Verify query transitioned to Answered
    await expect(page.getByText(/answered/i)).toBeVisible({ timeout: 10_000 })
  })

  test('Step 7: Export data as CSV and verify job completion', async ({ page }) => {
    // Navigate to exports
    await page.goto('/')
    await page.getByRole('link', { name: /exports/i }).click()
    await expect(page.getByRole('heading', { name: /exports/i })).toBeVisible()

    // Create a new CSV export
    await page.getByRole('button', { name: /create|new|export/i }).click()

    // Select CSV format
    await page.getByLabel(/format/i).selectOption('csv')

    // Select study scope (default or first available)
    const studySelect = page.getByLabel(/study/i)
    if (await studySelect.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await studySelect.selectOption({ index: 0 })
    }

    // Submit export request
    await page.getByRole('button', { name: /create|start|submit/i }).click()

    // Wait for export job to complete — poll or wait for status change
    await expect(page.getByText(/completed|ready|download/i)).toBeVisible({ timeout: 30_000 })

    // Verify download link is available
    const downloadLink = page.getByRole('link', { name: /download/i }).or(
      page.getByRole('button', { name: /download/i })
    )
    await expect(downloadLink).toBeVisible()
  })
})
