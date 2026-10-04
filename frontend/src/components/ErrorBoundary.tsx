import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  /** What failed, for the card title and the console log (e.g. "Demo C panel"). */
  name: string;
  children: ReactNode;
  /** Called by the Reload button after the boundary resets. Omit for a full page reload. */
  onReload?: () => void;
  /** When this value changes (e.g. new /api/state data), a failed boundary tries to render again. */
  resetKey?: unknown;
}

/**
 * Contains a render error to one part of the UI: shows a card with the message and a Reload button instead of
 * unmounting the whole app. Wrapped around every panel, the console and the app shell.
 */
export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(`[${this.props.name}] render error`, error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  reload = () => {
    if (!this.props.onReload) {
      window.location.reload();
      return;
    }
    this.setState({ error: null });
    this.props.onReload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="errorcard" role="alert">
        <span className="ic" aria-hidden>✕</span>
        <div>
          <p><strong>{this.props.name} could not be displayed.</strong> The rest of the demo still works.</p>
          <p className="mono msg">{error.message || String(error)}</p>
          <button type="button" className="btn" onClick={this.reload}>↻ Reload</button>
        </div>
      </div>
    );
  }
}
