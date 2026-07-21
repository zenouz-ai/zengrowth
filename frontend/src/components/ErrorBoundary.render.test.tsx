import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'

function Boom(): never {
  throw new Error('kaboom')
}

describe('ErrorBoundary', () => {
  it('catches a render error and shows the fallback instead of crashing', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/Something broke on this screen/i)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('renders children when there is no error', () => {
    render(
      <ErrorBoundary>
        <p>healthy content</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('healthy content')).toBeInTheDocument()
  })

  it('clears the error when resetKey changes (route change recovers)', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    function Harness() {
      const [key, setKey] = useState('a')
      return (
        <>
          <button onClick={() => setKey('b')}>navigate</button>
          <ErrorBoundary resetKey={key}>{key === 'a' ? <Boom /> : <p>recovered</p>}</ErrorBoundary>
        </>
      )
    }

    render(<Harness />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await userEvent.click(screen.getByText('navigate'))
    expect(screen.getByText('recovered')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    spy.mockRestore()
  })
})
