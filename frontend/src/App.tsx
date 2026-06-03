import { useEffect } from 'react'
import { AppShell } from './components/layout/AppShell'
import { useChatStore } from './store/chatStore'

export default function App() {
  const initBoundaries = useChatStore(s => s.initBoundaries)

  useEffect(() => {
    initBoundaries()
  }, [initBoundaries])

  return <AppShell />
}
