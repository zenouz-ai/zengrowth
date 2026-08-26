import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  // Changing this value (e.g. the current route) clears the error so navigating
  // away recovers without a full reload.
  resetKey?: string
  fallback?: (reset: () => void) => ReactNode
}

interface State {
  error: Error | null
  resetKey: string | undefined
}

// EA-05: a render-time exception in any page used to unmount the whole SPA to a
// blank screen. This boundary catches it, keeps the surrounding chrome alive,
// and offers an in-place retry; it auto-clears when `resetKey` changes so a
// route change is a clean recovery.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey !== state.resetKey) {
      return { error: null, resetKey: props.resetKey }
    }
    return null
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Unhandled render error', error, info.componentStack)
  }

  reset = (): void => this.setState({ error: null })

  render(): ReactNode {
    if (this.state.error === null) return this.props.children
    if (this.props.fallback) return this.props.fallback(this.reset)
    return (
      <div
        role="alert"
        className="rounded-lg border border-loss/40 bg-loss/5 px-4 py-8 text-center"
      >
        <p className="font-heading text-base font-semibold text-text">Something broke on this screen</p>
        <p className="mt-1 text-sm text-muted">
          The rest of the app is still running. Try again, or reload if it persists.
        </p>
        <div className="mt-4 flex justify-center gap-3">
          <button
            onClick={this.reset}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:text-text"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.reload()}
            className="rounded-lg border border-border px-3 py-1.5 text-sm hover:text-text"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
