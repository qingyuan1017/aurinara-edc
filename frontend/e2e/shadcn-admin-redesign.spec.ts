import { test, expect, type Page, type Route } from '@playwright/test'

const STUDY_ID = 'study-visual-001'
const ACCESS_TOKEN = 'e2e-visual-access-token'
const REFRESH_TOKEN = 'e2e-visual-refresh-token'

const visualUser = {
  id: 'user-visual-001',
  email: 'visual@example.com',
  first_name: 'Visual',
  last_name: 'Regression User',
  roles: [],
  permissions: [
    'study.create',
    'study.configure',
    'study.read',
    'version.publish',
    'site.manage',
    'site.read',
    'subject.create',
    'subject.read',
    'form.configure',
    'form.read',
    'form.enter',
    'form.submit',
    'query.create',
    'query.respond',
    'query.close',
    'data.export',
    'ctms.operational_data_read',
    'ctms.operational_study_management',
    'ctms.operational_site_management',
  ],
}

const study = {
  id: STUDY_ID,
  study_code: 'VIS-001',
  title: 'Visual Regression Study',
  phase: 'II',
  status: 'Active',
  description: 'Stable representative study data for browser coverage.',
  created_at: '2024-01-15T10:00:00.000Z',
  updated_at: '2024-02-15T10:00:00.000Z',
}

const studyVersion = {
  id: 'version-visual-001',
  version_number: '1.0',
  status: 'published',
  created_at: '2024-01-20T10:00:00.000Z',
}

const query = {
  id: 'query-visual-001',
  target_type: 'Subject',
  target_id: 'subject-visual-001',
  text: 'Confirm the source date.',
  status: 'Open',
  query_type: 'manual',
  assigned_role: 'Site Coordinator',
  subject_id: 'subject-visual-001',
  created_at: '2024-02-01T10:00:00.000Z',
}

const disabledManifest = {
  module: 'CTMS',
  enabled: false,
  phase: 0,
  capabilities: [],
}

async function fulfillJson(route: Route, data: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(data),
  })
}

/**
 * Uses the application's existing auth/me, capability, and read API contracts.
 * The fixture keeps browser assertions independent of changing database seeds.
 */
async function installVisualFixtures(page: Page, capability: 'disabled' | 'unavailable' = 'disabled') {
  await page.addInitScript(({ accessToken, refreshToken }) => {
    window.localStorage.setItem('access_token', accessToken)
    window.localStorage.setItem('refresh_token', refreshToken)
    window.localStorage.removeItem('edc-theme-mode')
  }, { accessToken: ACCESS_TOKEN, refreshToken: REFRESH_TOKEN })

  await page.route('**/api/v1/auth/me', (route) => fulfillJson(route, visualUser))
  await page.route('**/api/v1/auth/logout', (route) => fulfillJson(route, {}))
  await page.route('**/api/v1/ctms/capabilities', (route) => {
    if (capability === 'unavailable') return fulfillJson(route, { detail: 'Capability service unavailable' }, 503)
    return fulfillJson(route, disabledManifest)
  })
  await page.route('**/api/v1/studies**', async (route) => {
    const url = new URL(route.request().url())

    if (url.pathname === '/api/v1/studies') {
      return fulfillJson(route, { items: [study], page: 1, page_size: 20, total: 1 })
    }
    if (url.pathname === `/api/v1/studies/${STUDY_ID}`) {
      return fulfillJson(route, study)
    }
    if (url.pathname === `/api/v1/studies/${STUDY_ID}/versions`) {
      return fulfillJson(route, [studyVersion])
    }
    if (url.pathname === `/api/v1/studies/${STUDY_ID}/queries`) {
      return fulfillJson(route, { items: [query], page: 1, page_size: 50, total: 1 })
    }

    return route.continue()
  })
}

async function openAuthenticatedShell(page: Page, capability: 'disabled' | 'unavailable' = 'disabled') {
  await installVisualFixtures(page, capability)
  await page.goto('/')
  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
}

test.describe('shadcn-admin redesign browser coverage', () => {
  test('renders the desktop shell, theme choices, focus indicators, and non-hover essentials', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openAuthenticatedShell(page)

    await expect(page.getByTestId('app-sidebar')).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible()
    await expect(page.getByTestId('app-header').getByRole('link', { name: 'Notifications' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Global search unavailable' })).toBeDisabled()
    await expect(page.getByRole('button', { name: /Open user menu for Visual Regression User/ })).toBeVisible()

    const collapseButton = page.getByRole('button', { name: 'Collapse sidebar' })
    await collapseButton.focus()
    await expect(collapseButton).toBeFocused()
    await collapseButton.press('Enter')
    await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
    await expect(page.locator('a[aria-label="Dashboard"]')).toHaveAttribute('title', 'Dashboard')

    const themeTrigger = page.getByRole('button', { name: 'Theme: system' })
    await themeTrigger.focus()
    await themeTrigger.press('Enter')
    await expect(page.getByRole('menu')).toBeVisible()
    await expect(page.getByRole('menuitem', { name: 'Light' })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: 'Dark' })).toBeVisible()
    await page.getByRole('menuitem', { name: 'Dark' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-theme-mode', 'dark')

    await expect(page).toHaveScreenshot('authenticated-shell-desktop-dark.png', {
      animations: 'disabled',
      mask: [page.getByRole('button', { name: /Open user menu for/ })],
    })
  })

  test('supports mobile navigation, keyboard dismissal, focus return, and no overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await openAuthenticatedShell(page)

    await expect(page.getByTestId('app-sidebar')).toBeHidden()
    const menuTrigger = page.getByRole('button', { name: 'Open navigation' })
    await menuTrigger.click()
    const drawer = page.getByRole('dialog', { name: 'Clinical EDC' })
    await expect(drawer).toBeVisible()
    await expect(drawer.getByRole('navigation', { name: 'Mobile primary navigation' })).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()
    await expect(menuTrigger).toBeFocused()

    await menuTrigger.click()
    await drawer.getByRole('link', { name: 'Dashboard' }).click()
    await expect(drawer).toBeHidden()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('app-shell')).toHaveCSS('overflow-x', 'hidden')

    await expect(page).toHaveScreenshot('authenticated-shell-mobile-light.png', {
      animations: 'disabled',
      mask: [page.getByRole('button', { name: /Open user menu for/ })],
    })
  })

  test('covers representative list, table, detail, form, and dialog surfaces with stable data', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openAuthenticatedShell(page)

    await page.goto('/studies')
    await expect(page.getByRole('heading', { name: 'Studies' })).toBeVisible()
    const studyTable = page.getByRole('region', { name: 'Studies' }).getByRole('table')
    await expect(studyTable).toBeVisible()
    await expect(studyTable.getByRole('columnheader', { name: 'Code' })).toBeVisible()
    await expect(studyTable.getByRole('cell', { name: 'VIS-001' })).toBeVisible()
    await expect(studyTable.getByRole('cell', { name: 'Active' })).toBeVisible()

    const createStudy = page.getByRole('button', { name: 'Create Study' })
    await createStudy.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Create Study' })).toBeVisible()
    await expect(dialog.getByRole('textbox', { name: 'Code' })).toBeFocused()
    await expect(dialog.getByRole('textbox', { name: 'Title' })).toBeVisible()
    await expect(dialog.getByRole('combobox', { name: 'Phase' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(createStudy).toBeFocused()

    await page.getByRole('link', { name: 'VIS-001' }).click()
    await expect(page).toHaveURL(new RegExp(`/studies/${STUDY_ID}$`))
    await expect(page.getByRole('heading', { name: 'Visual Regression Study' })).toBeVisible()
    await expect(page.getByText(/EDC · Authoritative/)).toBeVisible()
    await expect(page.getByText('Active')).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Versions' })).toBeVisible()
    await page.getByRole('tab', { name: 'Versions' }).click()
    await expect(page.getByRole('table', { name: 'Study versions' })).toBeVisible()
    await expect(page.getByText('v1.0')).toBeVisible()

    await expect(page).toHaveScreenshot('study-detail-table.png', {
      animations: 'disabled',
      mask: [page.getByText('Created').locator('..'), page.getByText('Last updated').locator('..')],
    })
  })

  test('keeps EDC navigation and explains disabled or unavailable CTMS states', async ({ page }) => {
    await openAuthenticatedShell(page, 'disabled')
    await page.goto(`/studies/${STUDY_ID}/ctms`)
    await expect(page.getByRole('heading', { name: 'CTMS is disabled or unavailable' })).toBeVisible()
    await expect(page.getByText('EDC clinical navigation and indicators remain available.')).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible()

    await page.reload()
    await expect(page.getByRole('heading', { name: 'CTMS is disabled or unavailable' })).toBeVisible()

    await page.route('**/api/v1/ctms/capabilities', (route) => fulfillJson(route, { detail: 'Capability service unavailable' }, 503))
    await page.goto(`/studies/${STUDY_ID}/ctms`)
    await expect(page.getByRole('heading', { name: 'CTMS is unavailable' })).toBeVisible()
    await expect(page.getByText('Retry later or continue working in EDC.')).toBeVisible()
    await expect(page.getByTestId('app-sidebar').getByRole('link', { name: 'Dashboard' })).toBeVisible()
  })
})
