export interface ToolConfig {
  id: string
  path: string
  name: string
  displayName: string
  description: string
  icon: string[]
  component: () => Promise<{ default: any }>
  sidebarDefaultCollapsed?: boolean
}
