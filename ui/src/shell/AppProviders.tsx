import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider } from 'antd'
import enUS from 'antd/locale/en_US'
import { useState } from 'react'
import { createQueryClient } from '../kit/queryClient'

/** Everything a screen needs around it: the query cache and antd's context. */
export function AppProviders({
  children,
  queryClient,
  motion = true,
}: {
  children: React.ReactNode
  queryClient?: QueryClient
  /** false in tests: jsdom never ends an animation */
  motion?: boolean
}) {
  const [client] = useState(() => queryClient ?? createQueryClient())
  return (
    <QueryClientProvider client={client}>
      <ConfigProvider locale={enUS} theme={{ token: { fontSize: 15, motion } }}>
        <AntApp>{children}</AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  )
}
