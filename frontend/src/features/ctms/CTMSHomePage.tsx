import { CTMSWorkspacePage } from './WorkspacePage'

/** CTMS landing page. The workspace handles disabled, empty, and unavailable states. */
export function CTMSHomePage() {
  return <CTMSWorkspacePage view="overview" />
}
