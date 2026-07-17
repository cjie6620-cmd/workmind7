import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  resetBusinessStores: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/utils/http.js', () => ({
  default: { post: mocks.post },
}))

vi.mock('@/stores/session.js', () => ({
  resetBusinessStores: mocks.resetBusinessStores,
}))

import { useAuthStore } from '@/stores/auth.js'

describe('auth logout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('clears credentials synchronously for a local-only logout', async () => {
    localStorage.setItem('wm_access_token', 'access-token')
    localStorage.setItem('wm_refresh_token', 'refresh-token')
    localStorage.setItem('wm_user', JSON.stringify({ userId: 'u1', role: 'user' }))

    let finishCleanup
    mocks.resetBusinessStores.mockImplementation(() => new Promise((resolve) => {
      finishCleanup = resolve
    }))

    const store = useAuthStore()
    const logoutPromise = store.logout({ remoteCleanup: false })

    expect(store.accessToken).toBe('')
    expect(store.refreshToken).toBe('')
    expect(store.user).toBeNull()
    expect(localStorage.getItem('wm_access_token')).toBeNull()
    expect(localStorage.getItem('wm_refresh_token')).toBeNull()
    expect(localStorage.getItem('wm_user')).toBeNull()

    await vi.waitFor(() => {
      expect(mocks.resetBusinessStores).toHaveBeenCalledWith({ remoteCleanup: false })
    })
    finishCleanup()
    await logoutPromise
  })
})
