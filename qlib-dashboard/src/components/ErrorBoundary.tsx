import { Component, ErrorInfo, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  componentStack: string | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, componentStack: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo);
    this.setState({ componentStack: errorInfo.componentStack || null });
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex flex-col items-center justify-center min-h-[400px] p-8 text-center">
          <div className="flex items-center justify-center w-16 h-16 rounded-full bg-destructive/10 mb-6">
            <AlertTriangle className="h-8 w-8 text-destructive" />
          </div>
          <h2 className="text-lg font-semibold mb-2">Something went wrong</h2>
          <p className="text-sm text-muted-foreground mb-1 max-w-md">
            An unexpected error occurred while rendering this page.
          </p>
          {this.state.error && (
            <pre className="text-xs text-muted-foreground bg-muted rounded-md p-3 mt-2 mb-6 max-w-lg overflow-auto font-mono whitespace-pre-wrap">
              {this.state.error.message}
              {this.state.componentStack && (
                <>
                  {'\n\n--- Component Stack ---'}
                  {this.state.componentStack}
                </>
              )}
              {'\n\n--- Error Stack ---'}
              {this.state.error.stack}
            </pre>
          )}
          <div className="flex gap-3">
            <Button variant="outline" onClick={this.handleReset}>
              Try Again
            </Button>
            <Button onClick={this.handleReload}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Reload Page
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
